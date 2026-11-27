"""Configured PR scope fences intake, queued analysis and tracker writes."""
import unittest
from unittest.mock import Mock

from pydantic import ValidationError

from agent_service.config import BitbucketConfig
from agent_service.connectors.base import ResourceNotAllowed
from agent_service.connectors.bitbucket_analysis import BitbucketLocalAnalysisConnector
from agent_service.connectors.bitbucket_jira import BitbucketJiraBackend
from agent_service.connectors.bitbucket_kaiten import BitbucketKaitenBackend, BitbucketKaitenConnector
from tests.service import test_bitbucket_queue as queue
from tests.service import test_bitbucket_read as data


class ConfigTest(unittest.TestCase):
    def config(self, **extra):
        return BitbucketConfig.model_validate(dict(
            workspace='pilot', workspace_uuid=data.WS,
            repositories={'orders': {'uuid': data.REPO, 'repository_id': 'orders'}},
            auth={'email_env': 'BB_EMAIL', 'token_env': 'BB_TOKEN'}, **extra))

    def test_omitted_scope_preserves_unrestricted_default(self):
        self.assertIsNone(self.config().pull_request_ids)

    def test_default_config_round_trip_retains_unrestricted_scope(self):
        config = self.config()
        self.assertIsNone(BitbucketConfig.model_validate(config.model_dump()).pull_request_ids)

    def test_nonempty_unique_positive_ids_are_preserved(self):
        self.assertEqual(self.config(pull_request_ids={'orders': [4, 7]}).pull_request_ids,
                         {'orders': [4, 7]})

    def test_configured_invalid_scopes_are_rejected(self):
        for scope in ({}, {'orders': []}, {'orders': [4, 4]}, {'unknown': [4]},
                      {'orders': [True]}, {'orders': ['4']}, {'orders': [4.0]},
                      {'orders': [0]}, {'orders': [-1]}, {'orders': [2**63]},
                      {'orders': '4'}, {'orders': (4,)}):
            with self.subTest(scope=scope), self.assertRaises(ValidationError):
                self.config(pull_request_ids=scope)


class FenceTest(unittest.TestCase):
    def setUp(self):
        self.q = queue.QueueTest()
        self.q.setUp()
        self.addCleanup(self.q.doCleanups)
        self.f = self.q.fixture

    def restrict(self):
        self.f.document['bitbucket']['pull_request_ids'] = {'orders': [4]}
        return self.q.service().connectors['bitbucket']

    def test_omission_fetches_existing_pr(self):
        self.assertEqual(self.q.service().connectors['bitbucket'].fetch(queue.RID).data['pr_id'], 7)

    def test_fetch_rejects_excluded_pr_before_any_http(self):
        connector = self.restrict()
        with self.assertRaisesRegex(ResourceNotAllowed, "bitbucket_pull_request_not_allowed"):
            connector.fetch(queue.RID)
        self.assertEqual(self.f.requests, [])

    def test_reconcile_only_enqueues_allowlisted_pr(self):
        pr4 = data.pull_request()
        pr4['id'] = 4
        self.f.routes[data.PINNED + '/pullrequests']['values'].append(pr4)
        self.f.routes[data.PINNED + '/pullrequests/4'] = pr4
        self.restrict()
        service = self.q.service()
        self.assertEqual(service.reconcile()['enqueued'], 1)
        service.run_until_idle()
        self.assertIsNone(service.store.resource(queue.RID))
        self.assertEqual(service.store.resource(queue.RID.replace('#7', '#4'))['snapshot']['pr_id'], 4)

    def test_repository_omitted_from_partial_mapping_cannot_supply_prs(self):
        self.f.document['bitbucket']['repositories']['reporting'] = {
            'uuid': data.OTHER, 'repository_id': 'reporting'}
        connector = self.restrict()
        rid = queue.RID.replace('22222222-2222-2222-2222-222222222222',
                                '33333333-3333-3333-3333-333333333333').replace('#7', '#4')
        with self.assertRaisesRegex(ResourceNotAllowed, "bitbucket_pull_request_not_allowed"):
            connector.fetch(rid)
        self.assertEqual(self.f.requests, [])
        connector.reconcile_candidates(None)
        self.assertFalse(any('/reporting' in path for _, path, _ in self.f.requests))

    def restricted_analysis_service(self):
        self.restrict()
        self.f.document['bitbucket']['mode'] = 'local_analysis'
        policy = self.f.root / 'policy.json'
        policy.write_text('{"repositories":[{"id":"bb.orders","root":"/tmp/allowlist-mirror"}]}')
        self.f.document['core'] = {'policy_path': str(policy), 'state_dir': str(self.f.root / 'core')}
        return self.q.service()

    def test_worker_supersedes_queued_off_list_job_without_analysis_or_publication(self):
        previous = self.q.service()
        self.q.ingest(previous)
        current = self.restricted_analysis_service()
        analyzer = Mock()
        analyzer.analyze.side_effect = AssertionError('off-list PR reached analysis')
        current.analyzer = analyzer
        self.f.requests.clear()
        self.assertEqual(current.step(), 'analyze:superseded')
        [job] = current.store.jobs(queue.RID)
        self.assertEqual((job['state'], job['reason']),
                         ('SUPERSEDED', 'bitbucket_pull_request_not_allowed'))
        self.assertEqual(current.store.intents(queue.RID), [])
        self.assertEqual(analyzer.mock_calls, [])
        self.assertEqual(self.f.requests, [])
        self.assertIsNone(current.step())

    def test_worker_fails_queued_off_list_intent_before_backend(self):
        previous = self.q.service()
        self.q.ingest(previous)
        job = previous.store.claim_job('setup', providers={'bitbucket'})
        previous.store.complete_job(job, state='ANALYZED', result=None, reason='ready', intent={
            'kind': 'result', 'body': '{}', 'body_digest': 'a'*64, 'marker': 'b'*16})
        current = self.restricted_analysis_service()
        current.connectors['bitbucket'].publication_ready = True
        backend = Mock()
        current.publisher.backends['bitbucket'] = backend
        self.f.requests.clear()
        self.assertEqual(current.step(), 'publish:failed')
        [intent] = current.store.intents(queue.RID)
        self.assertEqual(intent['state'], 'FAILED')
        self.assertEqual(backend.mock_calls, [])
        self.assertEqual(self.f.requests, [])

    def test_stale_snapshot_cannot_prepare_refresh_or_read_git(self):
        old = self.q.service().connectors['bitbucket'].fetch(queue.RID)
        self.f.requests.clear()
        connector = self.restricted_analysis_service().connectors['bitbucket']
        self.assertIsInstance(connector, BitbucketLocalAnalysisConnector)
        with self.assertRaisesRegex(ResourceNotAllowed, "bitbucket_pull_request_not_allowed"):
            connector.prepare(old)
        self.assertEqual(self.f.requests, [])

    def test_stale_jira_delivery_cannot_create_update_or_read_comments(self):
        self.q.ingest(self.q.service())  # persist an open PR before narrowing config
        connector = self.restrict()
        self.f.requests.clear()
        jira = Mock(bot_identity='bot')
        backend = BitbucketJiraBackend(connector, jira)
        backend.bind_store(self.q.service().store)
        for operation in (lambda: backend.list_comments(queue.RID),
                          lambda: backend.create_comment(queue.RID, {}, 'marker'),
                          lambda: backend.update_comment(queue.RID, 'jira:10022|100', {}, 'marker')):
            with self.assertRaisesRegex(ResourceNotAllowed, "bitbucket_pull_request_not_allowed"):
                operation()
        self.assertEqual(self.f.requests, [])
        self.assertEqual(jira.mock_calls, [])

    def test_stale_kaiten_delivery_and_prepare_are_fenced(self):
        old = self.q.service().connectors['bitbucket'].fetch(queue.RID)
        connector = self.restrict()
        self.f.requests.clear()
        kaiten = Mock(bot_identity='bot')
        wrapped = BitbucketKaitenConnector(connector, kaiten, bindings={queue.RID: '123'})
        backend = BitbucketKaitenBackend(wrapped, kaiten)
        store = Mock()
        store.intent_is_current.return_value = True
        store.resource.return_value = {'version': old.version}
        backend.bind_store(store)
        intent = {'resource_id': queue.RID, 'resource_version': old.version}
        for operation in (lambda: wrapped.prepare(old),
                          lambda: backend.list_comments(queue.RID),
                          lambda: backend.create_comment(queue.RID, {}, 'marker', expected_intent=intent),
                          lambda: backend.update_comment(queue.RID, 'old', {}, 'marker', expected_intent=intent)):
            with self.assertRaisesRegex(ResourceNotAllowed, "bitbucket_pull_request_not_allowed"):
                operation()
        self.assertEqual(self.f.requests, [])
        self.assertEqual(kaiten.mock_calls, [])
