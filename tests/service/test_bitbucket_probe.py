"""Configuration and actual read-only HTTP/CLI boundaries of the Bitbucket probe."""
from contextlib import redirect_stdout
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
import subprocess
import sys
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from pydantic import ValidationError

from agent_service.__main__ import main
from agent_service.config import ServiceConfig, build, build_connectors
from agent_service.http import AuthError, ClientError, NotFound, ServerError
from tests.service import test_bitbucket_read as fixtures
try:
    from agent_service.bitbucket_probe import probe
except ModuleNotFoundError as exc:
    if exc.name != 'agent_service.bitbucket_probe':
        raise
    probe = None


class ProbeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.requests = []
        self.routes = {
            fixtures.ROOT: fixtures.repository(),
            fixtures.PINNED + '/refs/branches/main': {'name': 'main', 'target': {'hash': 'b'*40}},
            fixtures.PINNED + '/pullrequests': {'values': [fixtures.pull_request()]},
        }
        self.failure = None
        case = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                path = urlsplit(self.path).path
                case.requests.append((self.command, path, self.headers.get('Authorization')))
                status = case.failure or (200 if path in case.routes else 404)
                body = json.dumps(case.routes.get(path, {'error': {'message': 'fixture missing'}})).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        thread.start()
        self.addCleanup(thread.join, 2)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.document = {
            'installation_id': 'probe-1', 'environment': 'test',
            'state_path': str(self.root / 'must-not-exist' / 'state.sqlite'),
            'allow_loopback_http': True,
            'bitbucket': {
                'api_base': f'http://127.0.0.1:{self.server.server_port}/2.0',
                'workspace': 'pilot', 'workspace_uuid': fixtures.WS,
                'repositories': {'orders': {'uuid': fixtures.REPO, 'repository_id': 'bb.orders'}},
                'auth': {'email_env': 'TEST_BB_EMAIL', 'token_env': 'TEST_BB_TOKEN'},
            },
        }
        self.secrets = {'TEST_BB_EMAIL': 'pilot@example.invalid', 'TEST_BB_TOKEN': 'bb-test-token'}

    def config(self):
        return ServiceConfig.model_validate(self.document)

    def run_probe(self):
        self.assertIsNotNone(probe, 'Bitbucket configuration probe is not implemented')
        return probe(self.config(), env_secret=self.secrets.__getitem__)

    def test_complete_probe_exposes_identity_refs_and_pr_version_without_state(self):
        result = self.run_probe()
        self.assertEqual(result['schema'], 'agent-service-bitbucket-probe/1')
        self.assertEqual(result['status'], 'READ_ONLY_VERIFIED')
        self.assertFalse(result['runtime_ready'])
        [repo] = result['repositories']
        self.assertEqual((repo['repository_id'], repo['default_branch'], repo['default_head_sha']),
                         ('bb.orders', 'main', 'b'*40))
        [pr] = repo['open_pull_requests']
        self.assertEqual(pr['resource_id'], 'bitbucket:11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222#7')
        self.assertEqual((pr['head_sha'], pr['destination_tip_sha']), ('a'*40, 'b'*40))
        self.assertTrue(pr['version'].startswith('bitbucket:'))
        self.assertNotIn('base_sha', pr)  # destination tip is not a computed Git merge-base
        self.assertNotIn('bb-test-token', json.dumps(result))
        self.assertNotIn('pilot@example.invalid', json.dumps(result))
        self.assertFalse((self.root / 'must-not-exist').exists())
        self.assertEqual([method for method, _, _ in self.requests], ['GET']*3)
        self.assertTrue(all(auth == 'Basic cGlsb3RAZXhhbXBsZS5pbnZhbGlkOmJiLXRlc3QtdG9rZW4='
                            for _, _, auth in self.requests))

    def test_empty_repository_is_reported_without_branch_or_pr_fetch(self):
        self.routes[fixtures.ROOT]['mainbranch'] = None
        [repo] = self.run_probe()['repositories']
        self.assertTrue(repo['empty'])
        self.assertIsNone(repo['default_head_sha'])
        self.assertEqual(repo['open_pull_requests'], [])
        self.assertEqual(len(self.requests), 1)

    def test_wrong_pinned_repository_uuid_refuses_before_followup_reads(self):
        self.routes[fixtures.ROOT]['uuid'] = fixtures.OTHER
        with self.assertRaisesRegex(ClientError, 'bitbucket_repository_identity_mismatch'):
            self.run_probe()
        self.assertEqual(len(self.requests), 1)

    def test_wrong_workspace_uuid_is_refused(self):
        self.routes[fixtures.ROOT]['workspace']['uuid'] = fixtures.OTHER
        with self.assertRaises(ClientError):
            self.run_probe()
        self.assertEqual(len(self.requests), 1)

    def test_public_repository_is_refused_for_private_pilot(self):
        self.routes[fixtures.ROOT]['is_private'] = False
        with self.assertRaisesRegex(ClientError, 'bitbucket_private_repository_required'):
            self.run_probe()
        self.assertEqual(len(self.requests), 1)

    def test_later_repository_failure_cannot_return_partial_success(self):
        self.document['bitbucket']['repositories']['reporting'] = {
            'uuid': fixtures.OTHER, 'repository_id': 'bb.reporting'}
        with self.assertRaises(NotFound):
            self.run_probe()
        self.assertFalse((self.root / 'must-not-exist').exists())

    def test_partial_pr_listing_is_not_a_success_report(self):
        self.routes[fixtures.PINNED + '/pullrequests']['next'] = 'https://evil.invalid/next'
        with self.assertRaisesRegex(ClientError, 'bitbucket_pagination_invalid'):
            self.run_probe()

    def test_api_errors_keep_safe_classification(self):
        for status, expected in [(401, AuthError), (503, ServerError)]:
            self.failure = status
            with self.assertRaises(expected):
                self.run_probe()

    def test_runtime_commands_refuse_before_state_or_secret_loading(self):
        cfg = self.config()
        def no_secrets(name):
            self.fail('runtime loaded credentials instead of refusing unsupported Bitbucket')
        for factory in [build, build_connectors]:
            with self.assertRaisesRegex(ValueError, 'bitbucket_runtime_not_available_use_probe'):
                factory(cfg, env_secret=no_secrets)
        self.assertFalse((self.root / 'must-not-exist').exists())
        self.assertEqual(self.requests, [])

    def test_invalid_scope_and_inline_credentials_are_rejected_before_http(self):
        original = deepcopy(self.document)
        changes = [lambda b: b.update(workspace='../pilot'),
                   lambda b: b.update(workspace_uuid='invalid'),
                   lambda b: b.update(repositories={}),
                   lambda b: b['repositories'].update({'../orders': b['repositories']['orders']}),
                   lambda b: b['repositories']['orders'].update(uuid='invalid'),
                   lambda b: b['repositories']['orders'].update(repository_id='bad/id'),
                   lambda b: b['auth'].update(token='inline-secret'),
                   lambda b: b['auth'].update(email_env='pilot@example.invalid'),
                   lambda b: b.update(api_base='https://evil.invalid/2.0'),
                   lambda b: b.update(api_base='http://127.0.0.1:2/2.0', unexpected=True)]
        for change in changes:
            self.document = deepcopy(original)
            change(self.document['bitbucket'])
            with self.assertRaises(ValidationError):
                self.config()
        self.assertEqual(self.requests, [])

    def test_loopback_needs_existing_explicit_test_opt_in(self):
        self.document['allow_loopback_http'] = False
        with self.assertRaises(ValidationError):
            self.config()
        self.assertEqual(self.requests, [])

    def test_cli_without_bitbucket_is_explicit_configuration_failure(self):
        self.document.pop('bitbucket')
        code, text = self.cli()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(text)['error'], 'bitbucket_probe_configuration_invalid')
        self.assertFalse((self.root/'must-not-exist').exists())
        self.assertEqual(self.requests, [])

    def test_cli_validation_error_does_not_echo_inline_secret(self):
        self.document['bitbucket']['auth']['token'] = 'private-inline-value'
        code, text = self.cli()
        self.assertEqual(code, 1)
        self.assertNotIn('private-inline-value', text)
        self.assertNotIn('repositories', json.loads(text))
        self.assertEqual(self.requests, [])

    def test_duplicate_uuid_or_graph_id_is_rejected(self):
        for repo in [{'uuid': fixtures.REPO, 'repository_id': 'bb.reporting'},
                     {'uuid': fixtures.OTHER, 'repository_id': 'bb.orders'}]:
            self.document['bitbucket']['repositories']['reporting'] = repo
            with self.assertRaises(ValidationError):
                self.config()

    def test_github_explicit_and_default_graph_id_collisions_are_rejected(self):
        self.document['github'] = {'repositories': ['acme/orders'], 'bot_login': 'pilot[bot]',
            'webhook_secret_env': 'GH_WEBHOOK', 'auth': {'kind': 'token', 'token_env': 'GH_TOKEN'}}
        for repo_id, mapping in [('orders', {'acme/orders': 'orders'}), ('acme.orders', {})]:
            self.document['github']['repository_ids'] = mapping
            self.document['bitbucket']['repositories']['orders']['repository_id'] = repo_id
            with self.assertRaises(ValidationError):
                self.config()

    def cli(self):
        path = self.root / 'probe.json'
        path.write_text(json.dumps(self.document))
        out = io.StringIO()
        with patch.dict(os.environ, self.secrets), redirect_stdout(out):
            code = main(['bitbucket-probe', '--config', str(path)])
        return code, out.getvalue()

    def test_cli_probe_skips_other_provider_credentials_and_invalid_core_paths(self):
        self.document['github'] = {'repositories': ['acme/orders'], 'bot_login': 'pilot[bot]',
            'webhook_secret_env': 'ABSENT_GH_WEBHOOK', 'auth': {'kind': 'token', 'token_env': 'ABSENT_GH_TOKEN'}}
        self.document['core'] = {'policy_path': str(self.root/'absent-policy'), 'state_dir': str(self.root/'absent-core')}
        code, text = self.cli()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(text)['status'], 'READ_ONLY_VERIFIED')
        self.assertFalse((self.root/'absent-core').exists())
        self.assertFalse((self.root/'must-not-exist').exists())

    def test_cli_failure_prints_only_safe_reason_and_nonzero(self):
        self.failure = 401
        code, text = self.cli()
        self.assertEqual(code, 1)
        result = json.loads(text)
        self.assertEqual(result['error'], 'connection_unauthorized')
        self.assertNotIn('repositories', result)
        self.assertNotIn('bb-test-token', text)

    def test_cli_malformed_yaml_returns_safe_json_without_traceback_content(self):
        path = self.root/'bad.yaml'
        path.write_text('bitbucket: [INLINE_SECRET_CANARY')
        result = subprocess.run([sys.executable, '-m', 'agent_service', 'bitbucket-probe',
                                 '--config', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertNotIn('INLINE_SECRET_CANARY', result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)['error'], 'bitbucket_probe_configuration_invalid')
        self.assertFalse((self.root/'must-not-exist').exists())

    def test_missing_secret_reports_name_without_opening_state(self):
        self.secrets.pop('TEST_BB_TOKEN')
        with patch.dict(os.environ, self.secrets):
            os.environ.pop('TEST_BB_TOKEN', None)
            with self.assertRaisesRegex(ValueError, 'missing_secret_env:TEST_BB_TOKEN'):
                self.assertIsNotNone(probe)
                probe(self.config())
        self.assertFalse((self.root/'must-not-exist').exists())


if __name__ == '__main__':
    unittest.main()
