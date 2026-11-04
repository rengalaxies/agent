"""Real local HTTP boundaries for the additive, not-yet-wired Bitbucket reader."""
import base64
from copy import deepcopy
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from threading import Thread
import unittest
from urllib.parse import parse_qs, urlsplit

from agent_service.http import AuthError, ClientError, HttpClient, ServerError
try:
    from agent_service.connectors.bitbucket_read import ApiTokenAuth, BitbucketReadClient
except ModuleNotFoundError as exc:
    if exc.name != 'agent_service.connectors.bitbucket_read':
        raise
    ApiTokenAuth = BitbucketReadClient = None

WS = '{11111111-1111-1111-1111-111111111111}'
REPO = '{22222222-2222-2222-2222-222222222222}'
OTHER = '{33333333-3333-3333-3333-333333333333}'
ROOT = '/2.0/repositories/pilot/orders'
PINNED = '/2.0/repositories/pilot/%7B22222222-2222-2222-2222-222222222222%7D'


def repository():
    return dict(type='repository', uuid=REPO, slug='orders', full_name='pilot/orders',
                workspace=dict(type='workspace', uuid=WS, slug='pilot'), is_private=True,
                mainbranch=dict(type='branch', name='main'))


def pull_request(number=7):
    repo = dict(type='repository', uuid=REPO, full_name='pilot/orders')
    return dict(type='pullrequest', id=number, title='ORD-12 orders GET /orders page size',
                description='Change default page_size from 100 to 20.', state='OPEN', draft=False,
                source=dict(repository=deepcopy(repo), branch={'name': 'ORD-12/page-size'}, commit={'hash': 'a'*40}),
                destination=dict(repository=deepcopy(repo), branch={'name': 'main'}, commit={'hash': 'b'*40}),
                updated_on='2026-11-02T10:00:00+00:00', comment_count=0)


class ReadTest(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(BitbucketReadClient, 'Bitbucket read foundation is not implemented')
        self.repo_data = repository()
        self.pr = pull_request()
        self.requests = []
        self.failure = None
        self.raw_body = None
        self.fail_page = None
        self.max_page_size = None
        self.commit_responses = {'a'*12: {'hash': 'a'*40}, 'b'*12: {'hash': 'b'*40}}
        self.slug_reused = False
        self.pages = {'first': {'pagelen': 100, 'values': [self.pr]}}
        case = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                parsed = urlsplit(self.path)
                query = parse_qs(parsed.query, keep_blank_values=True)
                credential = self.headers.get('Authorization', '')
                decoded = base64.b64decode(credential.removeprefix('Basic ')).decode() if credential.startswith('Basic ') else ''
                case.requests.append((self.command, parsed.path, query, decoded))
                status = 200
                if decoded != 'pilot@example.invalid:bb-test-token':
                    status, data = 401, {'error': {'message': 'unauthorized'}}
                elif case.failure:
                    status, data = case.failure, {'error': {'message': 'synthetic failure'}}
                elif (parsed.path == PINNED + '/pullrequests' and case.max_page_size is not None
                      and int(query.get('pagelen', ['10'])[0]) > case.max_page_size):
                    status, data = 400, {'error': {'message': 'Invalid pagelen'}}
                elif parsed.path == ROOT:
                    data = case.repo_data
                elif parsed.path == PINNED + '/refs/branches/feature%2Fwith-slash':
                    data = {'name': 'feature/with-slash', 'target': {'hash': 'c'*40}}
                elif parsed.path in {ROOT + '/refs/branches/main', PINNED + '/refs/branches/main'}:
                    sha = 'd' if case.slug_reused and parsed.path.startswith(ROOT + '/') else 'b'
                    data = {'name': 'main', 'target': {'hash': sha*40}}
                elif parsed.path.startswith(PINNED + '/commit/'):
                    key = parsed.path.rsplit('/', 1)[1]
                    status, data = (200, case.commit_responses[key]) if key in case.commit_responses else (404, {})
                elif parsed.path == PINNED + '/pullrequests/7':
                    data = case.pr
                elif parsed.path == PINNED + '/pullrequests':
                    cursor = query.get('after', query.get('page', ['first']))[0]
                    if cursor == case.fail_page:
                        status, data = 503, {"error": {"message": "page unavailable"}}
                    else:
                        data = case.pages[cursor]
                else:
                    status, data = 404, {'error': {'message': 'no fixture'}}
                body = case.raw_body if case.raw_body is not None else json.dumps(data).encode()
                self.send_response(status)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.url = f'http://127.0.0.1:{self.server.server_port}/2.0'
        self.client = self.reader()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def reader(self, *, token='bb-test-token'):
        return BitbucketReadClient(HttpClient(self.url, allow_loopback_http=True),
            ApiTokenAuth('pilot@example.invalid', token), workspace='pilot', workspace_uuid=WS,
            repositories=['orders', 'reporting'])

    def repo(self):
        return self.client.repository('orders')

    def next_url(self, query='after=opaque%2Bcursor%2F%3D'):
        return self.url + PINNED.removeprefix('/2.0') + '/pullrequests?' + query

    def test_basic_auth_and_read_operations_never_write(self):
        repo = self.repo()
        self.assertEqual(repo.uuid, '22222222-2222-2222-2222-222222222222')
        self.assertTrue(repo.is_private)
        self.assertEqual(self.client.branch(repo), 'b'*40)
        pr = self.client.pull_request(repo, 7)
        self.assertEqual((pr.head_sha, pr.base_sha), ('a'*40, 'b'*40))
        self.assertEqual(self.client.open_pull_requests(repo), (pr,))
        self.assertTrue(all(method == 'GET' and auth == 'pilot@example.invalid:bb-test-token'
                            for method, _, _, auth in self.requests))
        self.assertNotIn('bb-test-token', repr(self.client.auth))

    def test_empty_repository_is_metadata_not_an_auth_failure(self):
        self.repo_data['mainbranch'] = None
        repo = self.repo()
        self.assertIsNone(repo.default_branch)
        count = len(self.requests)
        with self.assertRaisesRegex(ClientError, 'bitbucket_empty_repository'):
            self.client.branch(repo)
        self.assertEqual(len(self.requests), count)

    def test_omitted_mainbranch_is_an_empty_repository(self):
        self.repo_data.pop('mainbranch')
        self.assertIsNone(self.repo().default_branch)

    def test_slug_reuse_cannot_switch_a_previously_resolved_repository(self):
        repo = self.repo()
        self.slug_reused = True
        self.assertEqual(self.client.branch(repo), 'b'*40)
        self.assertEqual(self.client.pull_request(repo, 7).repository.uuid, repo.uuid)
        self.assertEqual(len(self.client.open_pull_requests(repo)), 1)

    def test_caller_cannot_replace_resolved_uuid_or_read_an_unresolved_dto(self):
        repo = self.repo()
        before = len(self.requests)
        with self.assertRaises(ValueError):
            self.client.branch(replace(repo, uuid=OTHER.strip('{}')))
        with self.assertRaises(ValueError):
            self.reader().branch(repo)
        self.assertEqual(len(self.requests), before)
        self.repo_data['uuid'] = OTHER
        with self.assertRaisesRegex(ClientError, 'bitbucket_repository_identity_changed'):
            self.repo()

    def test_invalid_unicode_is_rejected_before_returning_a_dto(self):
        repo = self.repo()
        for change in [lambda x: x.update(description=chr(0xd800)),
                       lambda x: x.update(title=chr(0xd800)),
                       lambda x: x['source']['branch'].update(name=chr(0xd800))]:
            self.pr = pull_request()
            change(self.pr)
            with self.assertRaisesRegex(ClientError, 'bitbucket_response_invalid'):
                self.client.pull_request(repo, 7)

    def test_invalid_percent_escape_next_is_rejected_before_another_request(self):
        repo = self.repo()
        for query in ['after=%ZZ', 'after=%', 'after=%1']:
            self.pages = {'first': {'values': [], 'next': self.next_url(query)}}
            before = len(self.requests)
            with self.assertRaisesRegex(ClientError, 'bitbucket_pagination_invalid'):
                self.client.open_pull_requests(repo)
            self.assertEqual(len(self.requests), before + 1)

    def test_branch_slash_is_encoded_as_one_segment(self):
        self.assertEqual(self.client.branch(self.repo(), 'feature/with-slash'), 'c'*40)
        self.assertEqual(self.requests[-1][1], PINNED + '/refs/branches/feature%2Fwith-slash')

    def test_repository_allowlist_rejects_before_http(self):
        with self.assertRaises(ValueError):
            self.client.repository('production')
        self.assertEqual(self.requests, [])

    def test_repository_identity_mismatch_is_rejected(self):
        for mutate in [lambda x: x['workspace'].update(uuid=OTHER),
                       lambda x: x.update(full_name='other/orders'),
                       lambda x: x.update(slug='production')]:
            self.repo_data = repository()
            mutate(self.repo_data)
            with self.assertRaisesRegex(ClientError, 'bitbucket_response_invalid'):
                self.repo()

    def test_api_origin_cannot_be_replaced_by_config(self):
        with self.assertRaises(ValueError):
            BitbucketReadClient(HttpClient('https://other.invalid/2.0'),
                ApiTokenAuth('pilot@example.invalid', 'bb-test-token'), workspace='pilot',
                workspace_uuid=WS, repositories=['orders'])
        self.assertEqual(self.requests, [])

    def test_pr_resource_ids_are_uuid_scoped_and_not_github_ids(self):
        repo = self.repo()
        pr = self.client.pull_request(repo, 7)
        self.assertEqual(pr.resource_id, 'bitbucket:11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222#7')
        other = replace(pr, repository=replace(repo, uuid=OTHER.strip('{}')))
        self.assertNotEqual(pr.resource_id, other.resource_id)
        self.assertNotEqual(pr.resource_id, 'github:pilot/orders#7')

    def test_semantic_version_tracks_intent_refs_state_and_draft(self):
        repo = self.repo()
        old = self.client.pull_request(repo, 7)
        changes = [lambda x: x.update(title='ORD-99 Different issue'),
                   lambda x: x.update(description='Another requirement'),
                   lambda x: x['source']['commit'].update(hash='d'*40),
                   lambda x: x['destination']['commit'].update(hash='e'*40),
                   lambda x: x['source']['branch'].update(name='ORD-99/new-branch'),
                   lambda x: x['destination']['branch'].update(name='release'),
                   lambda x: x['source']['repository'].update(uuid=OTHER),
                   lambda x: x.update(state='MERGED'), lambda x: x.update(draft=True)]
        for change in changes:
            self.pr = pull_request()
            change(self.pr)
            with self.subTest(pr=self.pr):
                self.assertNotEqual(self.client.pull_request(repo, 7).version, old.version)
        self.pr = pull_request()
        self.pr.update(updated_on='2026-11-03T10:00:00+00:00', comment_count=20)
        self.assertEqual(self.client.pull_request(repo, 7).version, old.version)

    def test_pr_destination_uuid_and_number_are_checked(self):
        repo = self.repo()
        for change in [lambda x: x['destination']['repository'].update(uuid=OTHER),
                       lambda x: x['destination']['repository'].update(full_name='other/orders'),
                       lambda x: x.update(id=8), lambda x: x.update(id=True),
                       lambda x: x['source']['commit'].update(hash='short'),
                       lambda x: x.update(state='UNKNOWN'), lambda x: x.update(draft='false')]:
            self.pr = pull_request()
            change(self.pr)
            with self.assertRaisesRegex(ClientError, 'bitbucket_response_invalid'):
                self.client.pull_request(repo, 7)

    def test_compact_pr_hashes_resolve_to_full_commits_inside_the_pinned_repository(self):
        repo = self.repo()
        self.pr['source']['commit']['hash'] = 'a'*12
        self.pr['destination']['commit']['hash'] = 'b'*12
        pr = self.client.pull_request(repo, 7)
        self.assertEqual((pr.head_sha, pr.base_sha), ('a'*40, 'b'*40))
        self.assertEqual([p for _, p, _, _ in self.requests[-2:]],
                         [PINNED+'/commit/'+'a'*12, PINNED+'/commit/'+'b'*12])
        self.assertEqual(self.client.open_pull_requests(repo), (pr,))

    def test_mismatched_compact_commit_resolution_is_refused(self):
        self.pr['source']['commit']['hash'] = 'a'*12
        self.commit_responses['a'*12] = {'hash': 'd'*40}
        with self.assertRaisesRegex(ClientError, 'bitbucket_response_invalid'):
            self.client.pull_request(self.repo(), 7)

    def test_compact_fork_hash_does_not_expand_repository_read_scope(self):
        repo = self.repo()
        self.pr['source']['repository']['uuid'] = OTHER
        self.pr['source']['commit']['hash'] = 'a'*12
        before = len(self.requests)
        with self.assertRaisesRegex(ClientError, 'bitbucket_compact_fork_sha_unsupported'):
            self.client.pull_request(repo, 7)
        self.assertEqual(len(self.requests), before+1)

    def test_provider_rejecting_large_pr_pages_still_reads_complete_listing(self):
        # Observed against the real API: pagelen100 is HTTP400 Invalid pagelen;
        # pagelen50 is accepted. Keep actual HTTP behavior rather than a constant assertion.
        self.max_page_size = 50
        self.pages = {'first': {'values': [pull_request(7)], 'next': self.next_url('after=second&pagelen=50')},
                      'second': {'values': [pull_request(8)]}}
        self.assertEqual([pr.number for pr in self.client.open_pull_requests(self.repo())], [7, 8])

    def test_opaque_pagination_reads_all_pages(self):
        self.pages = {'first': {'values': [pull_request(7)], 'next': self.next_url()},
                      'opaque+cursor/=': {'values': [pull_request(8)]}}
        prs = self.client.open_pull_requests(self.repo())
        self.assertEqual([x.number for x in prs], [7, 8])
        self.assertEqual(self.requests[-1][2]['after'], ['opaque+cursor/='])

    def test_foreign_or_changed_next_target_never_receives_credentials(self):
        repo = self.repo()
        urls = ['https://other.invalid/2.0/repositories/pilot/orders/pullrequests?page=2',
                self.url + '/repositories/pilot/production/pullrequests?page=2',
                self.next_url() + '#fragment', self.next_url('state=MERGED&page=2'),
                self.next_url('page=2&page=3'),
                self.next_url().replace('://', '://name:secret@')]
        for url in urls:
            self.pages = {'first': {'values': [self.pr], 'next': url}}
            before = len(self.requests)
            with self.assertRaisesRegex(ClientError, 'bitbucket_pagination_invalid'):
                self.client.open_pull_requests(repo)
            self.assertEqual(len(self.requests), before + 1)

    def test_cycle_is_refused_without_returning_partial_results(self):
        self.pages = {'first': {'values': [self.pr], 'next': self.next_url('page=2')},
                      '2': {'values': [], 'next': self.next_url('page=2')}}
        repo = self.repo()
        before = len(self.requests)
        with self.assertRaisesRegex(ClientError, 'bitbucket_listing_incomplete'):
            self.client.open_pull_requests(repo)
        self.assertEqual(len(self.requests), before + 2)

    def test_page_limit_accepts_terminal_twentieth_but_refuses_twenty_first(self):
        self.pages = {'first': {'values': [], 'next': self.next_url('page=2')}}
        for i in range(2, 20):
            self.pages[str(i)] = {'values': [], 'next': self.next_url('page='+str(i+1))}
        self.pages['20'] = {'values': [self.pr]}
        repo = self.repo()
        self.assertEqual(len(self.client.open_pull_requests(repo)), 1)
        self.pages['20']['next'] = self.next_url('page=21')
        before = len(self.requests)
        with self.assertRaisesRegex(ClientError, 'bitbucket_listing_incomplete'):
            self.client.open_pull_requests(repo)
        self.assertEqual(len(self.requests), before+20)

    def test_invalid_pages_or_non_open_rows_do_not_pass_as_complete(self):
        repo = self.repo()
        for page in [{}, {'values': None}, {'values': [None]}, {'values': [], 'next': ''},
                     {'values': [dict(self.pr, state='DECLINED')]}, {'values': [], 'next': 3}]:
            self.pages = {'first': page}
            with self.assertRaises(ClientError):
                self.client.open_pull_requests(repo)

    def test_conflicting_duplicate_snapshot_is_refused(self):
        self.pages = {'first': {'values': [self.pr], 'next': self.next_url('page=2')},
                      '2': {'values': [dict(self.pr, title='ORD-99 changed mid-listing')]}}
        with self.assertRaisesRegex(ClientError, 'bitbucket_listing_changed'):
            self.client.open_pull_requests(self.repo())

    def test_identical_duplicate_is_coalesced(self):
        self.pages = {'first': {'values': [self.pr], 'next': self.next_url('page=2')},
                      '2': {'values': [self.pr]}}
        self.assertEqual(len(self.client.open_pull_requests(self.repo())), 1)

    def test_partial_next_page_failure_is_propagated(self):
        self.pages = {'first': {'values': [self.pr], 'next': self.next_url('page=2')}}
        self.fail_page = '2'
        repo = self.repo()
        before = len(self.requests)
        with self.assertRaises(ServerError):
            self.client.open_pull_requests(repo)
        self.assertEqual(len(self.requests), before+2)

    def test_http_auth_and_server_failures_keep_safe_classification(self):
        with self.assertRaises(AuthError):
            self.reader(token='wrong').repository('orders')
        self.failure = 503
        with self.assertRaises(ServerError):
            self.repo()
        self.failure = None
        self.raw_body = b'not json with fake token'
        with self.assertRaisesRegex(ClientError, 'bitbucket_response_invalid') as error:
            self.repo()
        self.assertNotIn('fake token', str(error.exception))


if __name__ == '__main__':
    unittest.main()
