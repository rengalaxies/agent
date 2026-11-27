import json
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from agent_service.http import HttpClient, TransportError
from tools.agent_service.tracker_api_probe import run_probe, ProbeError, validate_config


class Stand:
    def __init__(self, provider):
        self.provider = provider
        self.comments = []
        self.requests = []
        self.foreign_link = False
        self.loop_page = False
        self.page_size = 2
        self.wrong_author = False
        self.scope = '20'
        stand = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self): self.handle_request('GET')
            def do_POST(self): self.handle_request('POST')
            def do_PATCH(self): self.handle_request('PATCH')
            def handle_request(self, method):
                u = urlsplit(self.path)
                query = parse_qs(u.query)
                body = json.loads(self.rfile.read(int(self.headers.get('content-length', 0))) or b'null')
                stand.requests.append((method, u.path, query, body, dict(self.headers)))
                headers = {}
                if u.path.endswith('/users/current'):
                    data = {'id': 7}
                elif '/comments' not in u.path:
                    data = {'id': 12, 'board_id': int(stand.scope), 'archived': False, 'title': 'Authored test card', 'description': 'Local test context'} if stand.provider == 'kaiten' else {'id': '12', 'queue': {'id': stand.scope}}
                elif method == 'POST':
                    cid = str(len(stand.comments) + 1)
                    data = stand.comment(cid, body['text'])
                    stand.comments.append(data)
                elif method == 'PATCH':
                    cid = u.path.rsplit('/', 1)[1]
                    data = next(c for c in stand.comments if stand.cid(c) == cid)
                    data['text'] = body['text']
                else:
                    if stand.provider == 'kaiten':
                        start = int(query.get('offset', ['0'])[0])
                        headers['X-Pagination-Limit'] = str(stand.page_size)
                    else:
                        after = query.get('id', [''])[0]
                        start = next((i + 1 for i, c in enumerate(stand.comments) if str(c['id']) == after), len(stand.comments)) if after else 0
                    if stand.loop_page: start = 0
                    data = stand.comments[start:start + stand.page_size]
                    if stand.provider == 'yandex_tracker' and start + stand.page_size < len(stand.comments):
                        host = 'https://evil.invalid' if stand.foreign_link else 'https://api.tracker.yandex.net'
                        headers['Link'] = f'<{host}{u.path}?perPage=2&id={data[-1]["id"]}>; rel="next"'
                raw = json.dumps(data).encode()
                self.send_response(201 if method == 'POST' and stand.provider == 'yandex_tracker' else 200)
                for k, v in headers.items(): self.send_header(k, v)
                self.send_header('Content-Length', str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.client = HttpClient(f'http://127.0.0.1:{self.server.server_port}', allow_loopback_http=True)

    def cid(self, c): return str(c['id']) if self.provider == 'kaiten' else c['longId']
    def comment(self, cid, text):
        author = 'intruder' if self.wrong_author else '7'
        if self.provider == 'kaiten':
            return {'id': int(cid), 'card_id': 12, 'author_id': author, 'text': text, 'deleted': False}
        return {'id': int(cid), 'longId': 'opaque-' + cid, 'createdBy': {'id': author}, 'text': text, 'version': 1}
    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class ProbeTest(unittest.TestCase):
    def config(self, provider):
        cfg = dict(provider=provider, base_url='https://demo.kaiten.ru' if provider == 'kaiten' else 'https://api.tracker.yandex.net', task_id='12', scope_id='20', bot_id='7', token_env='IM_TEST_TOKEN')
        if provider == 'yandex_tracker': cfg.update(org_id='org1', org_header='X-Cloud-Org-ID', auth_scheme='OAuth')
        return cfg

    def execute(self, stand, directory, write=True):
        return run_probe(self.config(stand.provider), Path(directory), token='secret-test-value', write=write, client=stand.client)

    def test_both_providers_create_update_same_comment_and_resume_without_duplicate(self):
        for p in ('kaiten', 'yandex_tracker'):
            with self.subTest(provider=p), tempfile.TemporaryDirectory() as d:
                stand = Stand(p)
                self.addCleanup(stand.close)
                for i in range(1, 5): stand.comments.append(stand.comment(str(i), 'unrelated'))
                result = self.execute(stand, d)
                self.assertEqual(result['status'], 'PASS')
                self.assertEqual(result['environment'], 'LOCAL_HTTP')
                self.assertEqual(len(stand.comments), 5)
                self.execute(stand, d)
                writes = [r for r in stand.requests if r[0] != 'GET']
                self.assertEqual([w[0] for w in writes], ['POST', 'PATCH'])
                self.assertTrue(writes[1][1].endswith('/5' if p == 'kaiten' else '/opaque-5'))
                self.assertEqual(writes[0][3].keys(), {'text'})
                auth = next(v for k, v in writes[0][4].items() if k.lower() == 'authorization')
                self.assertEqual(auth, ('Bearer' if p == 'kaiten' else 'OAuth') + ' secret-test-value')
                if p == 'yandex_tracker': self.assertEqual(writes[0][4]['X-Cloud-Org-Id'], 'org1')
                self.assertNotIn('secret-test-value', (Path(d) / 'probe.json').read_text())

    def test_read_only_default_has_no_writes(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            self.assertEqual(self.execute(stand, d, write=False)['status'], 'READ_ONLY')
            self.assertTrue(all(r[0] == 'GET' for r in stand.requests))

    def test_scope_mismatch_and_wrong_author_do_not_update(self):
        for wrong in ('scope', 'author'):
            with self.subTest(wrong=wrong), tempfile.TemporaryDirectory() as d:
                stand = Stand('kaiten'); self.addCleanup(stand.close)
                if wrong == 'scope': stand.scope = '21'
                else: stand.wrong_author = True
                with self.assertRaises(ProbeError): self.execute(stand, d)
                self.assertFalse(any(r[0] == 'PATCH' for r in stand.requests))
                if wrong == 'scope': self.assertFalse(stand.comments)

    def test_applied_but_timed_out_create_is_reconciled_without_second_post(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            real = stand.client.request
            def timeout(method, *a, **kw):
                response = real(method, *a, **kw)
                if method == 'POST': raise TransportError('simulated_after_apply')
                return response
            stand.client.request = timeout
            with self.assertRaises(TransportError): self.execute(stand, d)
            self.assertEqual(json.loads((Path(d) / 'probe.json').read_text())['phase'], 'create_pending')
            stand.client.request = real
            self.assertEqual(self.execute(stand, d)['status'], 'PASS')
            self.assertEqual(sum(r[0] == 'POST' for r in stand.requests), 1)

    def test_unknown_absent_create_does_not_post_on_resume(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            real = stand.client.request
            def timeout(method, *a, **kw):
                if method == 'POST': raise TransportError('before_apply')
                return real(method, *a, **kw)
            stand.client.request = timeout
            with self.assertRaises(TransportError): self.execute(stand, d)
            stand.client.request = real
            with self.assertRaisesRegex(ProbeError, 'create_outcome_unresolved'): self.execute(stand, d)
            self.assertFalse(any(r[0] == 'POST' for r in stand.requests))

    def test_hostile_or_non_progressing_pagination_never_writes(self):
        for p, flag in (('yandex_tracker', 'foreign_link'), ('kaiten', 'loop_page')):
            with self.subTest(provider=p), tempfile.TemporaryDirectory() as d:
                stand = Stand(p); self.addCleanup(stand.close)
                setattr(stand, flag, True)
                for i in range(1, 5): stand.comments.append(stand.comment(str(i), 'unrelated'))
                with self.assertRaises(ProbeError): self.execute(stand, d)
                self.assertFalse(any(r[0] != 'GET' for r in stand.requests))

    def test_config_refuses_credentialed_hosts_and_ambiguous_org(self):
        for bad in ('http://demo.kaiten.ru', 'https://demo.kaiten.ru/else', 'https://evil.invalid', 'https://u:p@demo.kaiten.ru'):
            cfg = self.config('kaiten'); cfg['base_url'] = bad
            with self.assertRaises(ValueError): validate_config(cfg)
        cfg = self.config('yandex_tracker'); cfg['org_header'] = 'Authorization'
        with self.assertRaises(ValueError): validate_config(cfg)

    def test_resume_clears_old_error_after_success(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            real = stand.client.request
            def timeout(method, *a, **kw):
                response = real(method, *a, **kw)
                if method == 'PATCH': raise TransportError('after_update')
                return response
            stand.client.request = timeout
            with self.assertRaises(TransportError): self.execute(stand, d)
            stand.client.request = real
            result = self.execute(stand, d)
            self.assertEqual(result['status'], 'PASS')
            self.assertNotIn('error', result)
            self.assertEqual([r[0] for r in stand.requests if r[0] != 'GET'], ['POST', 'PATCH'])

    def test_duplicate_own_marker_or_manual_edit_stops_future_writes(self):
        for wrong in ('duplicate', 'manual_edit'):
            with self.subTest(wrong=wrong), tempfile.TemporaryDirectory() as d:
                stand = Stand('yandex_tracker'); self.addCleanup(stand.close)
                self.execute(stand, d)
                if wrong == 'duplicate': stand.comments.append(stand.comment('2', stand.comments[0]['text']))
                else: stand.comments[0]['text'] += ' human edit'
                count = sum(r[0] != 'GET' for r in stand.requests)
                with self.assertRaises(ProbeError): self.execute(stand, d)
                self.assertEqual(sum(r[0] != 'GET' for r in stand.requests), count)

    def test_journal_rejects_new_configuration_and_is_exclusively_locked(self):
        import fcntl
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            self.execute(stand, d, write=False)
            cfg = self.config('kaiten'); cfg['scope_id'] = '99'
            with self.assertRaisesRegex(ProbeError, 'probe_config_changed'):
                run_probe(cfg, Path(d), token='secret', write=True, client=stand.client)
            with (Path(d) / 'probe.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.assertRaisesRegex(ProbeError, 'probe_already_running'): self.execute(stand, d)
            self.assertFalse(any(r[0] != 'GET' for r in stand.requests))

    def test_errors_and_malformed_pages_never_become_empty_success(self):
        from agent_service.http import AuthError, RateLimited, ServerError, Response
        for error in (AuthError(status=401), AuthError(status=403), RateLimited(status=429, retry_after=2), ServerError(status=503), None):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as d:
                stand = Stand('kaiten'); self.addCleanup(stand.close)
                real = stand.client.request
                def broken(method, path, **kw):
                    if '/comments' in path:
                        if error: raise error
                        return Response(200, {}, b'{"not":"an array"}')
                    return real(method, path, **kw)
                stand.client.request = broken
                with self.assertRaises((ProbeError, AuthError, RateLimited, ServerError)):
                    self.execute(stand, d)
                state = json.loads((Path(d) / 'probe.json').read_text())
                self.assertEqual(state['status'], 'FAILED')
                self.assertFalse(stand.comments)

    def test_page_budget_exhaustion_and_long_marker_body_fail_before_write(self):
        from unittest.mock import patch
        from tools.agent_service.tracker_api_probe import ProbeAPI
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            for i in range(1, 5): stand.comments.append(stand.comment(str(i), 'unrelated'))
            with patch('tools.agent_service.tracker_api_probe.MAX_PAGES', 1):
                with self.assertRaisesRegex(ProbeError, 'comment_listing_incomplete'): self.execute(stand, d)
            api = ProbeAPI(self.config('kaiten'), 'secret', stand.client)
            with self.assertRaisesRegex(ProbeError, 'comment_too_large'): api.write('x' * 4097)
            self.assertFalse(any(r[0] != 'GET' for r in stand.requests))

    def mutate_responses(self, stand, transform):
        from agent_service.http import Response
        real = stand.client.request
        def changed(method, path, **kwargs):
            response = real(method, path, **kwargs)
            data = response.json()
            headers = dict(response.headers)
            status, data, headers = transform(method, path, response.status, data, headers)
            return Response(status, headers, json.dumps(data).encode())
        stand.client.request = changed

    def test_bad_cursor_and_missing_applied_limit_prevent_any_write(self):
        for provider in ('kaiten', 'yandex_tracker'):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as d:
                stand = Stand(provider); self.addCleanup(stand.close)
                for i in range(1, 5): stand.comments.append(stand.comment(str(i), 'unrelated'))
                def change(method, path, status, data, headers):
                    if provider == 'kaiten': headers.pop('x-pagination-limit', None)
                    elif 'link' in headers: headers['link'] = headers['link'].replace('id=2', 'id=999')
                    return status, data, headers
                self.mutate_responses(stand, change)
                with self.assertRaises(ProbeError): self.execute(stand, d)
                self.assertFalse(any(r[0] != 'GET' for r in stand.requests))

    def test_yandex_missing_link_is_explicitly_exhausted_and_overfull_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('yandex_tracker'); self.addCleanup(stand.close)
            for i in range(1, 5): stand.comments.append(stand.comment(str(i), 'unrelated'))
            def no_link(method, path, status, data, headers):
                headers.pop('link', None)
                return status, data, headers
            self.mutate_responses(stand, no_link)
            self.assertEqual(self.execute(stand, d)['status'], 'PASS')
            before_post = stand.requests[:next(i for i, r in enumerate(stand.requests) if r[0] == 'POST')]
            self.assertTrue(any(r[2].get('id') == ['4'] for r in before_post))

    def test_yandex_overfull_unique_page_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('yandex_tracker'); self.addCleanup(stand.close)
            stand.page_size = 51
            for i in range(1, 52): stand.comments.append(stand.comment(str(i), 'unrelated'))
            with self.assertRaises(ProbeError): self.execute(stand, d)
            self.assertFalse(any(r[0] != 'GET' for r in stand.requests))

    def test_malformed_nested_response_invalidates_previous_pass(self):
        for target in ('queue', 'createdBy'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as d:
                stand = Stand('yandex_tracker'); self.addCleanup(stand.close)
                self.execute(stand, d)
                def change(method, path, status, data, headers):
                    if isinstance(data, dict) and '/comments' not in path and target == 'queue': data['queue'] = 'bad'
                    if isinstance(data, list) and data and target == 'createdBy': data[0]['createdBy'] = 'bad'
                    return status, data, headers
                self.mutate_responses(stand, change)
                with self.assertRaises(ProbeError): self.execute(stand, d)
                state = json.loads((Path(d) / 'probe.json').read_text())
                self.assertEqual(state['status'], 'FAILED')

    def test_foreign_comment_self_and_deleted_write_reply_are_rejected(self):
        for condition in ('foreign_self', 'deleted', 'deleted_wrong_type'):
            with self.subTest(condition=condition), tempfile.TemporaryDirectory() as d:
                stand = Stand('yandex_tracker'); self.addCleanup(stand.close)
                def change(method, path, status, data, headers):
                    if method in {'POST', 'PATCH'}:
                        if condition == 'foreign_self': data['self'] = 'https://api.tracker.yandex.net/v3/issues/OTHER-2/comments/1'
                        elif condition == 'deleted': data['deleted'] = True
                        else: data['deleted'] = 'false'
                    return status, data, headers
                self.mutate_responses(stand, change)
                with self.assertRaises(ProbeError): self.execute(stand, d)
                self.assertFalse(any(r[0] == 'PATCH' for r in stand.requests))

    def test_partial_page_status_is_not_complete(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            self.mutate_responses(stand, lambda method, path, status, data, headers: (206 if '/comments' in path else status, data, headers))
            with self.assertRaises(ProbeError): self.execute(stand, d)
            self.assertFalse(any(r[0] != 'GET' for r in stand.requests))

    def test_unearned_updated_readback_cannot_skip_patch(self):
        import hashlib
        from agent_service.connectors.base import marker_line, parse_marker
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            def change(method, path, status, data, headers):
                if method == 'POST':
                    marker = parse_marker(data['text'])[0]
                    body = 'ImpactMap API probe: updated. Dedicated test target.'
                    stand.comments[0]['text'] = body + '\n\n' + marker_line(marker, hashlib.sha256(body.encode()).hexdigest(), 2)
                return status, data, headers
            self.mutate_responses(stand, change)
            with self.assertRaisesRegex(ProbeError, 'unexpected_probe_generation'): self.execute(stand, d)
            self.assertNotEqual(json.loads((Path(d) / 'probe.json').read_text())['status'], 'PASS')

    def test_post_write_scope_drift_is_not_pass(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            def change(method, path, status, data, headers):
                if method == 'PATCH': stand.scope = '21'
                return status, data, headers
            self.mutate_responses(stand, change)
            with self.assertRaisesRegex(ProbeError, 'task_scope_mismatch'): self.execute(stand, d)
            self.assertNotEqual(json.loads((Path(d) / 'probe.json').read_text())['status'], 'PASS')

    def test_directory_entry_is_durable_before_post(self):
        import os
        import stat
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            sync, replace, request = os.fsync, os.replace, stand.client.request
            events = []
            def synced(fd):
                result = sync(fd)
                if stat.S_ISDIR(os.fstat(fd).st_mode): events.append('directory_sync')
                return result
            def replaced(*a, **kw):
                result = replace(*a, **kw); events.append('replace'); return result
            def checked(method, *a, **kw):
                if method == 'POST':
                    self.assertIn('directory_sync', events)
                    self.assertGreater(len(events) - 1 - events[::-1].index('directory_sync'), len(events) - 1 - events[::-1].index('replace'))
                return request(method, *a, **kw)
            stand.client.request = checked
            with patch('os.fsync', synced), patch('os.replace', replaced): self.execute(stand, Path(d) / 'new' / 'nested')
            self.assertIn('directory_sync', events)

    def test_read_only_resume_preserves_unresolved_write_outcome(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            real = stand.client.request
            def timeout(method, *a, **kw):
                if method == 'POST': raise TransportError('before_apply')
                return real(method, *a, **kw)
            stand.client.request = timeout
            with self.assertRaises(TransportError): self.execute(stand, d)
            stand.client.request = real
            result = self.execute(stand, d, write=False)
            self.assertEqual(result['status'], 'UNKNOWN')
            self.assertEqual(result['observation'], 'READ_ONLY')
            self.assertEqual(result['phase'], 'create_pending')

    def test_valid_yandex_current_key_links_are_scoped_and_dispatched_by_id(self):
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('yandex_tracker'); self.addCleanup(stand.close)
            for i in range(1, 5): stand.comments.append(stand.comment(str(i), 'unrelated'))
            def change(method, path, status, data, headers):
                if isinstance(data, dict) and '/comments' not in path: data['key'] = 'Q-12'
                values = data if isinstance(data, list) else [data] if '/comments' in path else []
                for value in values: value['self'] = f'https://api.tracker.yandex.net/v3/issues/Q-12/comments/{value["id"]}'
                if 'link' in headers: headers['link'] = headers['link'].replace('/issues/12/', '/issues/Q-12/')
                return status, data, headers
            self.mutate_responses(stand, change)
            self.assertEqual(self.execute(stand, d)['status'], 'PASS')
            self.assertTrue(all('/issues/12' in r[1] for r in stand.requests))

    def test_deep_invalid_json_is_stable_failure(self):
        from agent_service.http import Response
        with tempfile.TemporaryDirectory() as d:
            stand = Stand('kaiten'); self.addCleanup(stand.close)
            real = stand.client.request
            def deep(method, path, **kw):
                if '/comments' in path: return Response(200, {}, b'[' * 2000 + b'0')
                return real(method, path, **kw)
            stand.client.request = deep
            with self.assertRaisesRegex(ProbeError, 'invalid_provider_json'): self.execute(stand, d)
            state = json.loads((Path(d) / 'probe.json').read_text())
            self.assertEqual(state['status'], 'FAILED')
