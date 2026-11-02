"""Explicit CI qualification of manager paging with real immutable target code.

Not auto-discovered: --target must name verified extracted published/candidate
archives. Every provider is a synthetic local HTTP stand; no model or VM.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import unittest


TARGETS = []


def child():
    import importlib.util
    from types import SimpleNamespace
    args = json.loads(sys.argv[2])
    target = Path(args['target']).resolve()
    sys.path[:0] = [str(target / 'app/src'), str(target / 'app')]
    from agent_service import __main__ as entry
    from agent_service.connectors import jira as target_jira
    from agent_service.http import HttpClient, Response, ServerError
    from agent_service.queue import ServiceStore
    from agent_service.service import Service
    assert Path(target_jira.__file__).resolve().is_relative_to(target / 'app')
    clock = lambda: 1_800_000_000.0
    connector = target_jira.JiraConnector(HttpClient(args['url'], allow_loopback_http=True),
        target_jira.BasicAuth('bot@example.invalid', 'jira-test-token'), project_keys=['ORD'],
        bot_account_id='bot-account', webhook_secret=b'none', clock=clock)
    store = ServiceStore(Path(args['db']), clock=clock)
    analyzer = SimpleNamespace(query=lambda: SimpleNamespace(source_freshness=lambda: [{'status':'OK'}]))
    service = Service(store=store, connectors={'jira':connector}, analyzer=analyzer,
                      installation_id='inst-1', environment='test')
    entry._service = lambda namespace: (service, None)
    spec = importlib.util.spec_from_file_location('manager_preflight', args['manager'])
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    config = Path(args['config'])
    config.write_text(json.dumps({'core':{'policy_path':args['policy']}}))
    Path(args['policy']).write_text('{"repositories":[]}')
    def run():
        sys.argv = ['preflight', str(target), str(config), 'digest', 'matching-backup']
        return manager.main()
    original = connector._call
    calls, listings = [], 0
    if args['fault'] != 'none':
        def call(method, path, **kwargs):
            nonlocal listings
            calls.append((method,path))
            if path == '/rest/api/3/search/jql' and not kwargs['query'].get('nextPageToken'):
                listings += 1
                if args['fault'] == 'second503' and listings == 2:
                    raise ServerError(status=503)
            if path == '/rest/api/3/search/jql' and kwargs['query'].get('nextPageToken') and args['fault'] != 'second503':
                if args['fault'] == '503':
                    raise ServerError(status=503)
                return Response(200, {}, b'{"issues":[],"isLast":false}')
            return original(method,path,**kwargs)
        connector._call = call
        try:
            run()
        except (ServerError, manager.PreflightError):
            pass
        else:
            raise AssertionError('partial recovery was accepted')
        assert store.checkpoint('box_recovery') is None
        assert store.resources('jira') == []
        connector._call = original
    assert run() == 0
    assert store.checkpoint('box_recovery') == 'digest:matching-backup'
    before = [(r['resource_id'],r['generation']) for r in store.resources('jira')]
    assert set(before) == {('jira:10001',1),('jira:10002',1)}
    assert run() == 0
    assert before == [(r['resource_id'],r['generation']) for r in store.resources('jira')]
    assert all(len(store.jobs(rid)) == 1 and store.jobs(rid)[0]['state'] == 'QUEUED' for rid,_ in before)
    assert all(method == 'GET' for method,_ in calls)
    print(json.dumps({'ok':True,'target':args['commit'],'fault':args['fault'],
                      'full_old_issues':len(before),'repeat_without_duplicates':True}))


if __name__ == '__main__' and sys.argv[1:2] == ['--child']:
    child()
    raise SystemExit(0)

from tests.service.helpers import ServiceCase  # noqa: E402
from tools.agent_service.box.release import verify_tree  # noqa: E402


class Compatibility(ServiceCase):
    def check_targets(self, fault):
        self.github.prs.clear()
        self.jira.add_issue(10002,'ORD-2','ORD','Orders GET /orders','Old task without PR')
        self.jira.search_page_size = 1
        for issue in self.jira.issues.values():
            issue['fields']['_epoch'] -= 30 * 86400
        manager = Path(__file__).resolve().parents[2] / 'tools/agent_service/box/preflight.py'
        for number,target in enumerate(TARGETS):
            manifest,_ = verify_tree(target)
            with self.subTest(commit=manifest['code']['commit'], fault=fault):
                root = Path(self.tmp.name)/str(number)
                root.mkdir()
                args = dict(target=str(target),manager=str(manager),url=self.jira.url,
                    db=str(root/'service.sqlite'),config=str(root/'config.json'),policy=str(root/'policy.json'),
                    fault=fault,commit=manifest['code']['commit'])
                result = subprocess.run([sys.executable,'-I','-B',str(Path(__file__).resolve()),'--child',json.dumps(args)],
                    capture_output=True,text=True,timeout=30)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                evidence = json.loads(result.stdout)
                self.assertTrue(evidence['ok'])
                print(result.stdout.strip())
                self.assertEqual(sum(len(v) for v in self.jira.comments.values()),0)

    def test_full_paged_recovery_and_repeat(self):
        self.check_targets('none')

    def test_later_page_503_then_retry(self):
        self.check_targets('503')

    def test_second_reconcile_503_then_retry(self):
        self.check_targets('second503')

    def test_incomplete_page_then_retry(self):
        self.check_targets('invalid')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--child']:
        child()
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--target',action='append',type=Path,required=True)
        args = parser.parse_args()
        TARGETS[:] = [p.resolve() for p in args.target]
        unittest.main(argv=[sys.argv[0]],verbosity=2)
