"""Author probe regressions, scripted HTTP responses; never LIVE App proof."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from agent_service.http import Response

PATH = Path(__file__).resolve().parents[2] / 'docs/implementation/autonomous-mvp/m2-a-2026-10-28'
spec = importlib.util.spec_from_file_location('pilot_probe', PATH / 'probe_connections.py')
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)
PERMS = dict(metadata='read', contents='read', pull_requests='read', issues='write')

class ProbeBoundary(unittest.TestCase):
    def run_probe(self, wrong_install=False, foreign=False, error=False):
        calls = []
        auth = SimpleNamespace(_jwt=lambda: 'JWT-SENTINEL', _token=None)
        repos = ['rengalaxies/agent-pilot-orders', 'rengalaxies/agent-pilot-reporting']
        def request(method, path, **kwargs):
            calls.append((method, path))
            if error:
                raise RuntimeError('JWT-SENTINEL PEM-SENTINEL TOKEN-SENTINEL')
            data = {}
            if path == '/app':
                data = dict(id=5515659, slug='rengalaxies-agent-pilot', permissions=PERMS)
            elif path.startswith('/app/installations/'):
                data = dict(id=999 if wrong_install else 176298402, app_id=5515659,
                            account=dict(login='rengalaxies'), permissions=PERMS, repository_selection='selected')
            elif path == '/installation/repositories':
                auth._token = 'TOKEN-SENTINEL'
                data = dict(total_count=2, repositories=[dict(full_name=n, private=True) for n in
                             (['other/private', repos[1]] if foreign else repos)])
            elif path.startswith('/users/'):
                data = dict(id=349497413, login='rengalaxies-agent-pilot[bot]', type='Bot')
            elif '/branches/' in path:
                data = dict(name='main', commit=dict(sha='a'*40))
            elif path.endswith('/pulls'):
                data = []
            return Response(204 if method == 'DELETE' else 200, {'x-github-request-id':'scripted'}, json.dumps(data).encode())
        gh = SimpleNamespace(auth=auth, client=SimpleNamespace(request=request), _call=request,
                             _repo=lambda n:'/repos/'+n)
        with patch.object(probe, 'build_connectors', return_value=({'github':gh}, {})):
            result = probe.probe(PATH / 'box.github-only.yaml')
        self.assertNotIn('SENTINEL', json.dumps(result))
        return result, calls

    def test_wrong_installation_refuses_before_token_or_repository_reads(self):
        result, calls = self.run_probe(wrong_install=True)
        self.assertEqual(result['status'], 'FAIL')
        self.assertFalse(any(p == '/installation/repositories' or p.startswith('/repos/') for _,p in calls))

    def test_foreign_repository_scope_refuses_reads_and_revokes_token(self):
        result, calls = self.run_probe(foreign=True)
        self.assertEqual(result['status'], 'FAIL')
        self.assertFalse(any(p.startswith('/repos/') for _,p in calls))
        self.assertIn(('DELETE','/installation/token'), calls)

    def test_valid_scope_reads_prs_and_refs_and_revokes_without_secret_output(self):
        result, calls = self.run_probe()
        self.assertEqual(result['status'], 'PASS')
        self.assertEqual(sum(p.endswith('/pulls') for _,p in calls), 2)
        self.assertEqual(sum('/branches/' in p for _,p in calls), 2)
        self.assertEqual(calls[-1], ('DELETE','/installation/token'))

    def test_provider_exception_details_do_not_reach_report(self):
        result, calls = self.run_probe(error=True)
        self.assertEqual(result['status'], 'FAIL')
        self.assertEqual(result['checks'][0]['error_type'], 'RuntimeError')
        self.assertEqual(len(calls), 1)
