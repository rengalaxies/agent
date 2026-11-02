"""Full Jira listings are a retryable unit; no completion from partial pages."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

from agent_service import __main__ as entry
from agent_service.http import ClientError, Response, ServerError
from tools.agent_service.box import preflight
from tests.service.helpers import Crash, ServiceCase


def response(page):
    return Response(200, {}, json.dumps(page).encode())


class FullListingCase(ServiceCase):
    def setUp(self):
        super().setUp()
        self.github.prs.clear()
        self.jira.search_page_size = 2
        for i in range(10002, 10006):
            self.jira.add_issue(i, f'ORD-{i-10000}', 'ORD', 'Orders GET /orders', 'Reduce default page size')
        for issue in self.jira.issues.values():
            issue['fields']['_epoch'] -= 30 * 86400
        self.ids = {f'jira:{i}' for i in range(10001, 10006)}
        root = Path(self.tmp.name)
        self.policy = root / 'policy.json'
        self.policy.write_text('{"repositories":[]}')
        self.config = root / 'service.json'
        self.config.write_text(json.dumps({'core': {'policy_path': str(self.policy)}}))

    def preflight(self):
        query = SimpleNamespace(source_freshness=lambda: [{'status': 'OK'}])
        with patch.object(entry, '_service', return_value=(self.service, None)), \
                patch.object(self.analyzer, 'query', return_value=query, create=True), \
                patch.object(sys, 'path', list(sys.path)), \
                patch.object(sys, 'argv', ['preflight', self.tmp.name, str(self.config), 'digest', 'backup']):
            return preflight.main()

    def assert_complete_once(self):
        self.drain(max_steps=1000)
        self.assertEqual({r['resource_id'] for r in self.service.store.resources('jira')}, self.ids)
        for rid in self.ids:
            self.assertEqual(len(self.service.store.jobs(rid)), 1)
            self.assertEqual(self.service.store.resource(rid)['generation'], 1)
        self.assertEqual(sum(len(v) for v in self.jira.comments.values()), 5)


class BootstrapListingTest(FullListingCase):
    def test_real_http_pages_and_restart_have_no_duplicate_jobs_or_comments(self):
        connector = self.service.connectors['jira']
        with patch.object(connector, '_call', wraps=connector._call) as call:
            self.assertEqual(self.service.reconcile()['enqueued'], 5)
        calls = [c for c in call.call_args_list if c.args[1] == '/rest/api/3/search/jql']
        self.assertEqual(len(calls), 3)
        self.assertNotIn('nextPageToken', calls[0].kwargs['query'])
        self.assertEqual([c.kwargs['query'].get('nextPageToken') for c in calls], [None, '2', '4'])
        self.assert_complete_once()
        before = {rid: self.service.store.resource(rid)['comment_id'] for rid in self.ids}
        self.restart()
        self.service.reconcile()
        self.assert_complete_once()
        self.assertEqual(before, {rid: self.service.store.resource(rid)['comment_id'] for rid in self.ids})

    def test_second_page_api_error_does_not_commit_partial_listing_and_retry_starts_from_page_one(self):
        connector = self.service.connectors['jira']
        original = connector._call
        def fail(method, path, **kwargs):
            if path == '/rest/api/3/search/jql' and kwargs['query'].get('nextPageToken') == '2':
                raise ServerError(status=503)
            return original(method, path, **kwargs)
        with patch.object(connector, '_call', side_effect=fail):
            self.service.reconcile()
        self.assertIsNone(self.service.store.checkpoint('reconcile:jira'))
        self.assertEqual(self.service.store.resources('jira'), [])
        self.restart()
        self.service.reconcile()
        self.assert_complete_once()
        self.assertNotIn('reconcile_failed', {n['kind'] for n in self.service.store.notices()})

    def test_interrupt_after_durable_first_event_retries_without_duplicates(self):
        original = self.service._synthetic
        def interrupt(provider, rid, event_id):
            result = original(provider, rid, event_id)
            if provider == 'jira':
                raise Crash('power loss after first durable event')
            return result
        with patch.object(self.service, '_synthetic', side_effect=interrupt):
            with self.assertRaises(Crash):
                self.service.reconcile()
        self.assertIsNone(self.service.store.checkpoint('reconcile:jira'))
        self.restart()
        self.service.reconcile()
        self.assert_complete_once()
        with self.service.store._connect() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM events WHERE provider='jira'").fetchone()[0], 5)

    def test_invalid_or_incomplete_page_never_advances_checkpoint(self):
        pages = [{'issues': [], 'isLast': False}, {'issues': [], 'isLast': True, 'nextPageToken': 'more'},
                 {'issues': []}, {'isLast': True}, {'issues': {}, 'isLast': True}, [],
                 {'issues': [], 'isLast': 'true'}, {'issues': [], 'isLast': False, 'nextPageToken': 42},
                 {'issues': [None], 'isLast': True}, {'issues': [{'fields': None}], 'isLast': True},
                 {'issues': [{'id':'10001', 'key':'ORD-1', 'fields':{}}], 'isLast': True}]
        for page in pages:
            with self.subTest(page=page), patch.object(self.service.connectors['jira'], '_call', return_value=response(page)):
                self.service.reconcile()
                self.assertIsNone(self.service.store.checkpoint('reconcile:jira'))
                self.assertIn('reconcile_failed', {n['kind'] for n in self.service.store.notices()})

    def test_invalid_json_does_not_advance_checkpoint(self):
        with patch.object(self.service.connectors['jira'], '_call', return_value=Response(200, {}, b'not-json')):
            self.service.reconcile()
        self.assertIsNone(self.service.store.checkpoint('reconcile:jira'))
        self.assertIn('reconcile_failed', {n['kind'] for n in self.service.store.notices()})

    def test_twentieth_page_can_complete_when_explicitly_terminal(self):
        calls = 0
        def page(*args, **kwargs):
            nonlocal calls
            calls += 1
            return response({'issues': [], 'isLast': True} if calls == 20 else
                            {'issues': [], 'isLast': False, 'nextPageToken': str(calls)})
        with patch.object(self.service.connectors['jira'], '_call', side_effect=page):
            self.service.reconcile()
        self.assertEqual(calls, 20)
        self.assertIsNotNone(self.service.store.checkpoint('reconcile:jira'))

    def test_repeated_cursor_and_page_bound_fail_closed(self):
        for repeated in (True, False):
            count = 0
            def page(*args, **kwargs):
                nonlocal count
                count += 1
                return response({'issues': [], 'isLast': False, 'nextPageToken': 'same' if repeated else str(count)})
            with self.subTest(repeated=repeated), patch.object(self.service.connectors['jira'], '_call', side_effect=page):
                self.service.reconcile()
            self.assertIsNone(self.service.store.checkpoint('reconcile:jira'))
            self.assertEqual(count, 2 if repeated else 20)


class RecoveryListingTest(FullListingCase):
    def test_real_http_full_scan_repeated_preflight_and_restart_are_idempotent(self):
        self.service.store.checkpoint('reconcile:jira', str(self.clock()))
        self.assertEqual(self.preflight(), 0)
        self.assertEqual(self.service.store.checkpoint('box_recovery'), 'digest:backup')
        self.assertEqual(self.analyzer.requests, [])
        self.assertEqual(sum(len(v) for v in self.jira.comments.values()), 0)
        self.assertEqual(self.preflight(), 0)
        self.assert_complete_once()
        before = {rid: self.service.store.resource(rid)['comment_id'] for rid in self.ids}
        self.restart()
        self.assertEqual(self.preflight(), 0)
        self.assert_complete_once()
        self.assertEqual(before, {rid: self.service.store.resource(rid)['comment_id'] for rid in self.ids})

    def test_second_page_error_and_retry_do_not_mark_partial_preflight_complete(self):
        connector = self.service.connectors['jira']
        original = connector._call
        def fail(method, path, **kwargs):
            if path == '/rest/api/3/search/jql' and kwargs['query'].get('nextPageToken') == '2':
                raise ServerError(status=503)
            return original(method, path, **kwargs)
        with patch.object(connector, '_call', side_effect=fail), self.assertRaises(ServerError):
            self.preflight()
        self.assertIsNone(self.service.store.checkpoint('box_recovery'))
        self.assertEqual(self.service.store.resources('jira'), [])
        self.restart()
        self.assertEqual(self.preflight(), 0)
        self.assert_complete_once()

    def test_error_in_second_reconcile_pass_cannot_be_swallowed(self):
        connector = self.service.connectors['jira']
        original = connector._call
        listings = 0
        def fail(method, path, **kwargs):
            nonlocal listings
            if path == '/rest/api/3/search/jql' and not kwargs['query'].get('nextPageToken'):
                listings += 1
                if listings == 2:
                    raise ServerError(status=503)
            return original(method, path, **kwargs)
        with patch.object(connector, '_call', side_effect=fail), self.assertRaises(preflight.PreflightError):
            self.preflight()
        self.assertIsNone(self.service.store.checkpoint('box_recovery'))
        self.assertEqual(self.analyzer.requests, [])
        self.assertEqual(sum(len(v) for v in self.jira.comments.values()), 0)
        self.restart()
        self.assertEqual(self.preflight(), 0)
        self.assert_complete_once()

    def test_partial_snapshot_apply_is_safe_to_repeat_after_interruption(self):
        self.service.store.checkpoint('reconcile:jira', str(self.clock()))
        original = self.service._apply
        def interrupt(snapshot, event_id):
            original(snapshot, event_id)
            raise Crash('power loss after first snapshot transaction')
        with patch.object(self.service, '_apply', side_effect=interrupt), self.assertRaises(Crash):
            self.preflight()
        self.assertIsNone(self.service.store.checkpoint('box_recovery'))
        self.assertEqual(len(self.service.store.resources('jira')), 1)
        self.restart()
        self.assertEqual(self.preflight(), 0)
        self.assert_complete_once()

    def test_interrupt_before_completion_checkpoint_does_not_reopen_twice(self):
        self.service.reconcile()
        self.assert_complete_once()
        original = self.service.store.checkpoint
        def interrupt(name, value=None):
            if name == 'box_recovery' and value is not None:
                raise Crash('power loss after reopen commit')
            return original(name, value)
        with patch.object(self.service.store, 'checkpoint', side_effect=interrupt), self.assertRaises(Crash):
            self.preflight()
        self.assertIsNone(self.service.store.checkpoint('box_recovery'))
        self.restart()
        self.assertEqual(self.preflight(), 0)
        self.drain(max_steps=1000)
        for rid in self.ids:
            self.assertEqual(len(self.service.store.jobs(rid)), 2)
            self.assertEqual(self.service.store.resource(rid)['generation'], 2)
        self.assertEqual(sum(len(v) for v in self.jira.comments.values()), 5)

    def test_incomplete_page_or_limit_never_sets_recovery_completion(self):
        for page in ({'issues': [], 'isLast': False},
                     {'issues': [], 'isLast': True, 'nextPageToken': 'more'},
                     {'issues': [], 'isLast': False, 'nextPageToken': 'same'}):
            with self.subTest(page=page), patch.object(self.service.connectors['jira'], '_call', return_value=response(page)), \
                    self.assertRaises(ClientError):
                self.preflight()
            self.assertIsNone(self.service.store.checkpoint('box_recovery'))

    def test_fetch_error_after_full_listing_keeps_recovery_incomplete(self):
        connector = self.service.connectors['jira']
        original = connector.fetch
        def fail(rid):
            if rid == 'jira:10003':
                raise ServerError(status=503)
            return original(rid)
        with patch.object(connector, 'fetch', side_effect=fail), self.assertRaises(ServerError):
            self.preflight()
        self.assertIsNone(self.service.store.checkpoint('box_recovery'))
        self.assertEqual(self.service.store.resources('jira'), [])
        self.restart()
        self.preflight()
        self.assert_complete_once()

    def test_graph_api_failure_then_repair_cannot_use_a_previous_fresh_graph(self):
        github = self.service.connectors['github']
        with patch.object(self.analyzer, 'reconcile_graph', return_value=[], create=True):
            with patch.object(github, 'pin_revisions', side_effect=[{}, ServerError(status=503)]), \
                    self.assertRaises(preflight.PreflightError):
                self.preflight()
            self.assertIsNone(self.service.store.checkpoint('box_recovery'))
            self.assertIn('graph_reconcile_failed', {n['kind'] for n in self.service.store.notices()})
            self.preflight()
            self.assertNotIn('graph_reconcile_failed', {n['kind'] for n in self.service.store.notices()})
        self.assert_complete_once()

    def test_twenty_first_page_is_refused_and_a_fresh_retry_can_complete(self):
        calls = 0
        def page(*args, **kwargs):
            nonlocal calls
            calls += 1
            return response({'issues': [], 'isLast': False, 'nextPageToken': str(calls)})
        with patch.object(self.service.connectors['jira'], '_call', side_effect=page), self.assertRaises(ClientError):
            self.preflight()
        self.assertEqual(calls, 20)
        self.assertIsNone(self.service.store.checkpoint('box_recovery'))
        self.assertIsNone(self.service.store.checkpoint('reconcile:jira'))
        self.preflight()
        self.assert_complete_once()

    def test_removed_provider_notice_does_not_block_current_providers(self):
        self.service.store.note('reconcile_failed', 'removed-provider', 'old failure')
        self.assertEqual(self.preflight(), 0)


def killed_child():
    """Fresh interpreter; its only providers are the parent's synthetic local stands."""
    import signal
    from agent_service.connectors.jira import BasicAuth, JiraConnector
    from agent_service.http import HttpClient
    from agent_service.queue import ServiceStore
    from agent_service.service import Service
    from tests.service.helpers import ScriptedAnalyzer
    args = json.loads(sys.argv[1])
    clock = lambda: args['clock']
    connector = JiraConnector(HttpClient(args['url'], allow_loopback_http=True),
        BasicAuth('bot@example.invalid', 'jira-test-token'), project_keys=['ORD'],
        bot_account_id='bot-account', webhook_secret=b'none', clock=clock)
    analyzer = ScriptedAnalyzer()
    analyzer.query = lambda: SimpleNamespace(source_freshness=lambda: [{'status': 'OK'}])
    service = Service(store=ServiceStore(Path(args['db']), clock=clock), connectors={'jira': connector},
        analyzer=analyzer, installation_id='inst-1', environment='test')
    def stop():
        Path(args['marker']).write_text('durable fault point reached')
        signal.pause()
    if args['point'] == 'page':
        original = connector._call
        def call(method, path, **kwargs):
            if path == '/rest/api/3/search/jql' and kwargs['query'].get('nextPageToken'):
                stop()
            return original(method, path, **kwargs)
        connector._call = call
    else:
        original = service._apply if args['mode'] == 'recovery' else service._synthetic
        def apply(*a, **kw):
            original(*a, **kw)
            stop()
        if args['mode'] == 'recovery':
            service._apply = apply
        else:
            service._synthetic = apply
    if args['mode'] == 'bootstrap':
        service.reconcile()
    else:
        with patch.object(entry, '_service', return_value=(service, None)), \
                patch.object(sys, 'argv', ['preflight', str(Path(args['db']).parent), args['config'], 'digest', 'backup']):
            preflight.main()


class ProcessInterruptionTest(FullListingCase):
    def kill_and_retry(self, mode, point):
        import subprocess
        import time
        import signal
        import unittest
        if not sys.platform.startswith('linux'):
            raise unittest.SkipTest('Linux SIGKILL recovery path')
        marker = Path(self.tmp.name) / 'killed-at'
        args = dict(mode=mode, point=point, db=str(self.db), clock=self.clock(), url=self.jira.url,
                    marker=str(marker), config=str(self.config))
        child = subprocess.Popen([sys.executable, '-c',
            'from tests.service.test_jira_listing_recovery import killed_child; killed_child()', json.dumps(args)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
                time.sleep(.02)
            self.assertTrue(marker.exists(), 'child did not reach fault point')
            child.kill()
            stdout, stderr = child.communicate(timeout=5)
            self.assertEqual(child.returncode, -signal.SIGKILL, (stdout, stderr))
        finally:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=5)
        self.assertIsNone(self.service.store.checkpoint('box_recovery'))
        if mode == 'bootstrap' or point == 'page':
            self.assertIsNone(self.service.store.checkpoint('reconcile:jira'))
        with self.service.store._connect() as db:
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchone()[0], 'ok')
        self.restart()
        if mode == 'bootstrap':
            self.service.reconcile()
        else:
            self.preflight()
        self.assert_complete_once()

    def test_sigkill_bootstrap_during_pagination(self):
        self.kill_and_retry('bootstrap', 'page')

    def test_sigkill_bootstrap_after_durable_event(self):
        self.kill_and_retry('bootstrap', 'apply')

    def test_sigkill_preflight_during_pagination(self):
        self.kill_and_retry('recovery', 'page')

    def test_sigkill_preflight_after_durable_snapshot(self):
        self.service.store.checkpoint('reconcile:jira', str(self.clock()))
        self.kill_and_retry('recovery', 'apply')
