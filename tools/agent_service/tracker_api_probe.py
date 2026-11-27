"""Dedicated-target API diagnostic, not a production connector.

Read-only by default. --write leaves ONE owned diagnostic comment updated in
place. A durable journal survives unknown writes; never auto-retry a create.
No credentials, task bodies or provider exception details enter receipts.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import parse_qs, urljoin, urlsplit

from agent_service.connectors.base import marker_line, parse_marker
from agent_service.connectors.tracker_contract import TaskIdentity, CommentIdentity
from agent_service.http import ConnectorError, HttpClient, segment

MAX_PAGES = 100


class ProbeError(Exception):
    """Stable diagnostic reason, without provider payloads."""


def validate_config(cfg):
    if not isinstance(cfg, dict):
        raise ValueError('invalid_probe_config')
    provider = cfg.get('provider')
    if provider not in {'kaiten', 'yandex_tracker'}:
        raise ValueError('invalid_probe_provider')
    base = cfg.get('base_url', '')
    if not isinstance(base, str):
        raise ValueError('invalid_probe_host')
    parts = urlsplit(base)
    valid_host = bool(re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.kaiten\.ru', parts.hostname or '')) if provider == 'kaiten' else parts.hostname == 'api.tracker.yandex.net'
    if not valid_host or parts.scheme != 'https' or parts.netloc != parts.hostname or parts.path or parts.query or parts.fragment:
        raise ValueError('invalid_probe_host')
    for key in ('task_id', 'scope_id', 'bot_id'):
        TaskIdentity(provider, base, cfg.get(key))
    if provider == 'kaiten' and not all(re.fullmatch(r'[1-9][0-9]*', cfg[k]) for k in ('task_id', 'scope_id', 'bot_id')):
        raise ValueError('invalid_kaiten_numeric_id')
    if not isinstance(cfg.get('token_env'), str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', cfg['token_env']):
        raise ValueError('invalid_token_env')
    if provider == 'yandex_tracker':
        TaskIdentity(provider, base, cfg.get('org_id'))
        if cfg.get('org_header') not in {'X-Org-ID', 'X-Cloud-Org-ID'} or cfg.get('auth_scheme') not in {'OAuth', 'Bearer'}:
            raise ValueError('invalid_yandex_auth')
    allowed = {'provider', 'base_url', 'task_id', 'scope_id', 'bot_id', 'token_env'}
    if provider == 'yandex_tracker': allowed |= {'org_id', 'org_header', 'auth_scheme'}
    if set(cfg) != allowed:
        raise ValueError('unexpected_probe_config_keys')
    return cfg


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def _native_id(value):
    if isinstance(value, bool) or not isinstance(value, (int, str)) or not str(value):
        raise ProbeError('invalid_provider_identity')
    return str(value)


class ProbeAPI:
    def __init__(self, cfg, token, client=None):
        self.cfg = validate_config(cfg)
        self.provider = cfg['provider']
        self.client = client or HttpClient(cfg['base_url'])
        self.local = urlsplit(self.client.base_url).scheme == 'http' and urlsplit(self.client.base_url).hostname in {'127.0.0.1', 'localhost', '::1'}
        if not self.local and self.client.base_url != cfg['base_url']:
            raise ValueError('probe_client_host_mismatch')
        self.headers = {'Authorization': ('Bearer' if self.provider == 'kaiten' else cfg['auth_scheme']) + ' ' + token}
        if self.provider == 'yandex_tracker': self.headers[cfg['org_header']] = cfg['org_id']
        self.task_path = ('/api/v1/cards/' if self.provider == 'kaiten' else '/v3/issues/') + segment(cfg['task_id'])
        self.comments_path = self.task_path + '/comments'
        self.task_aliases = {cfg['task_id']}
        tenant = cfg['base_url'] if self.provider == 'kaiten' else cfg['org_header'] + ':' + cfg['org_id']
        self.task = TaskIdentity(self.provider, tenant, cfg['task_id'])
        self.events = []

    def request(self, method, path, **kwargs):
        try:
            response = self.client.request(method, path, headers=self.headers, **kwargs)
        except ConnectorError as exc:
            self.events.append({'operation': method, 'status': exc.status, 'error': exc.code})
            raise
        self.events.append({'operation': method, 'status': response.status})
        expected = {200, 201} if method == 'POST' else {200}
        if response.status not in expected:
            raise ProbeError('unexpected_response_status')
        try:
            return response, response.json()
        except (ValueError, UnicodeError, RecursionError):
            raise ProbeError('invalid_provider_json') from None

    def read_task(self):
        _, data = self.request('GET', self.task_path)
        if not isinstance(data, dict) or _native_id(data.get('id')) != self.cfg['task_id']:
            raise ProbeError('task_identity_mismatch')
        if self.provider == 'yandex_tracker' and not isinstance(data.get('queue'), dict):
            raise ProbeError('invalid_task_shape')
        scope = data.get('board_id') if self.provider == 'kaiten' else data['queue'].get('id')
        if _native_id(scope) != self.cfg['scope_id']:
            raise ProbeError('task_scope_mismatch')
        if data.get('archived') or data.get('deleted'):
            raise ProbeError('task_unavailable')
        self.task_aliases = {self.cfg['task_id']}
        if self.provider == 'yandex_tracker' and data.get('key') is not None:
            key = _native_id(data['key'])
            segment(key)
            self.task_aliases.add(key)

    def comment(self, raw):
        if not isinstance(raw, dict) or not isinstance(raw.get('text'), str):
            raise ProbeError('invalid_comment_shape')
        if self.provider == 'kaiten':
            if _native_id(raw.get('card_id')) != self.cfg['task_id']:
                raise ProbeError('comment_target_mismatch')
            native = _native_id(raw.get('id'))
            author = _native_id(raw.get('author_id'))
        else:
            native = _native_id(raw.get('longId') or raw.get('id'))
            if not isinstance(raw.get('createdBy'), dict):
                raise ProbeError('invalid_comment_shape')
            author = _native_id(raw['createdBy'].get('id'))
            if 'self' in raw:
                if not isinstance(raw['self'], str): raise ProbeError('invalid_comment_self')
                parts = urlsplit(urljoin(self.cfg['base_url'], raw['self']))
                origin = urlsplit(self.cfg['base_url'])
                ids = {native, _native_id(raw.get('id'))}
                allowed = {'/v3/issues/' + segment(task) + '/comments/' + segment(cid) for task in self.task_aliases for cid in ids}
                if parts.scheme != origin.scheme or parts.netloc != origin.netloc or parts.path not in allowed or parts.query or parts.fragment:
                    raise ProbeError('comment_target_mismatch')
        if 'deleted' in raw and not isinstance(raw['deleted'], bool):
            raise ProbeError('invalid_comment_shape')
        return {'id': native, 'author': author, 'text': raw['text'], 'deleted': raw.get('deleted', False), 'marker': parse_marker(raw['text'])[0]}

    def _next_query(self, link):
        matches = re.findall(r'<([^<>]+)>\s*;\s*rel="?next"?(?=\s*(?:,|$))', link)
        if len(matches) != 1:
            if 'next' in link: raise ProbeError('invalid_pagination_link')
            return None
        parts = urlsplit(urljoin(self.cfg['base_url'] + self.comments_path, matches[0]))
        expected = urlsplit(self.cfg['base_url'])
        allowed = {'/v3/issues/' + segment(task) + '/comments' for task in self.task_aliases}
        if parts.scheme != expected.scheme or parts.netloc != expected.netloc or parts.path not in allowed or parts.fragment:
            raise ProbeError('foreign_pagination_link')
        query = parse_qs(parts.query, keep_blank_values=True)
        if set(query) != {'perPage', 'id'} or any(len(v) != 1 or not v[0] for v in query.values()):
            raise ProbeError('invalid_pagination_query')
        if not query['perPage'][0].isdigit() or not 1 <= int(query['perPage'][0]) <= 100:
            raise ProbeError('invalid_pagination_limit')
        segment(query['id'][0])
        return {k: v[0] for k, v in query.items()}

    def list_comments(self):
        kaiten = self.provider == 'kaiten'
        query = {'limit': 100, 'offset': 0} if kaiten else {'perPage': 50}
        all_comments, seen, queries, cursor_ids = [], set(), set(), set()
        for _ in range(MAX_PAGES):
            fingerprint = _hash(query)
            if fingerprint in queries: raise ProbeError('pagination_not_progressing')
            queries.add(fingerprint)
            response, data = self.request('GET', self.comments_path, query=query)
            if not isinstance(data, list): raise ProbeError('invalid_comments_page')
            if not kaiten and len(data) > int(query['perPage']):
                raise ProbeError('overfull_comments_page')
            for raw in data:
                comment = self.comment(raw)
                if comment['id'] in seen: raise ProbeError('pagination_not_progressing')
                seen.add(comment['id'])
                if not kaiten:
                    cursor = _native_id(raw.get('id'))
                    if not cursor.isascii() or not cursor.isdigit() or cursor in cursor_ids:
                        raise ProbeError('invalid_comment_cursor')
                    cursor_ids.add(cursor)
                if not comment['deleted']: all_comments.append(comment)
            if kaiten:
                value = response.headers.get('x-pagination-limit', '')
                if not value.isdigit() or not 1 <= int(value) <= 100 or len(data) > int(value):
                    raise ProbeError('invalid_pagination_limit')
                if len(data) < int(value): return all_comments
                query['offset'] += int(value)
            else:
                next_query = self._next_query(response.headers.get('link', ''))
                if not data:
                    if next_query is not None: raise ProbeError('pagination_not_progressing')
                    return all_comments
                last_id = _native_id(data[-1]['id'])
                if next_query is not None and next_query['id'] != last_id:
                    raise ProbeError('pagination_cursor_mismatch')
                # Explicitly exhaust the numeric cursor even without Link. A
                # missing header/short clamped page must not conceal comments.
                query = next_query or {'perPage': query['perPage'], 'id': last_id}
        raise ProbeError('comment_listing_incomplete')

    def write(self, text, comment_id=None):
        # Kaiten limit includes the entire marker. Fail rather than chop it.
        if self.provider == 'kaiten' and len(text) > 4096:
            raise ProbeError('comment_too_large')
        path = self.comments_path + ('/' + segment(comment_id) if comment_id else '')
        _, data = self.request('PATCH' if comment_id else 'POST', path, json_body={'text': text})
        comment = self.comment(data)
        if comment['deleted']: raise ProbeError('deleted_write_response')
        return comment


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)


def _durable_directory(path):
    """Persist every new directory entry before a remote write can occur."""
    missing = []
    cursor = path.absolute()
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _sync_directory(directory.parent)


@contextmanager
def _locked(output):
    _durable_directory(output)
    with (output / 'probe.lock').open('a') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: raise ProbeError('probe_already_running') from None
        try: yield
        finally: fcntl.flock(lock, fcntl.LOCK_UN)


def run_probe(cfg, output: Path, *, token: str, write=False, client=None):
    api = ProbeAPI(cfg, token, client)
    output = Path(output)
    with _locked(output):
        journal = output / 'probe.json'
        if journal.exists():
            state = json.loads(journal.read_text())
            if state.get('config_sha256') != _hash(cfg) or state.get('environment') != ('LOCAL_HTTP' if api.local else 'REAL_API'):
                raise ProbeError('probe_config_changed')
        else:
            state = {'schema': 1, 'config_sha256': _hash(cfg), 'environment': 'LOCAL_HTTP' if api.local else 'REAL_API', 'task': api.task.as_list(), 'marker': secrets.token_hex(8), 'phase': 'new', 'comment_id': None, 'status': 'NOT_RUN', 'events': []}
        def save():
            tmp = output / 'probe.json.tmp'
            with tmp.open('w') as stream:
                json.dump(state, stream, ensure_ascii=False, indent=2)
                stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
            os.replace(tmp, journal)
            _sync_directory(output)
        def text(generation):
            body = f'ImpactMap API probe: {"created" if generation == 1 else "updated"}. Dedicated test target.'
            return body + '\n\n' + marker_line(state['marker'], hashlib.sha256(body.encode()).hexdigest(), generation)
        def owned(comments):
            matches = [c for c in comments if c['marker'] == state['marker']]
            if len(matches) > 1: raise ProbeError('duplicate_probe_marker')
            if matches and matches[0]['author'] != cfg['bot_id']: raise ProbeError('comment_author_mismatch')
            if matches and matches[0]['text'] not in {text(1), text(2)}: raise ProbeError('probe_comment_modified')
            if matches and state['comment_id'] and matches[0]['id'] != state['comment_id']: raise ProbeError('comment_identity_changed')
            return matches[0] if matches else None
        save()
        try:
            previous_status = state['status']
            state['status'] = 'RUNNING'
            api.read_task()
            existing = owned(api.list_comments())
            if not write:
                state['observation'] = 'READ_ONLY'
                # Observation must not erase the durable outcome of an earlier
                # write. Only a write-mode reconciliation can issue a new PASS.
                state['status'] = 'UNKNOWN' if state['phase'] in {'create_pending', 'update_pending'} else previous_status if state['phase'] != 'new' else 'READ_ONLY'
                return state
            state.pop('observation', None)
            if existing is not None and existing['text'] == text(2) and state['phase'] not in {'update_pending', 'verified'}:
                raise ProbeError('unexpected_probe_generation')
            if existing is None:
                if state['phase'] != 'new': raise ProbeError('create_outcome_unresolved')
                api.read_task()
                state.update(phase='create_pending', status='UNKNOWN'); save()
                created = api.write(text(1))
                if created['author'] != cfg['bot_id'] or created['text'] != text(1): raise ProbeError('create_verification_failed')
                state.update(comment_id=created['id'], phase='created'); save()
                existing = owned(api.list_comments())
                if not existing: raise ProbeError('created_comment_not_visible')
                if existing['text'] != text(1): raise ProbeError('unexpected_probe_generation')
            else:
                state['comment_id'] = existing['id']
            if existing['text'] != text(2):
                api.read_task()
                state.update(phase='update_pending', status='UNKNOWN'); save()
                updated = api.write(text(2), existing['id'])
                if updated['id'] != existing['id'] or updated['author'] != cfg['bot_id'] or updated['text'] != text(2):
                    raise ProbeError('update_verification_failed')
            for _ in range(2):
                verified = owned(api.list_comments())
                if not verified or verified['text'] != text(2): raise ProbeError('readback_verification_failed')
            api.read_task()
            state.update(phase='verified', status='PASS', comment_identity=CommentIdentity(api.task, state['comment_id']).encode())
            state.pop('error', None)
            return state
        except (ProbeError, ConnectorError, ValueError, TypeError, KeyError) as exc:
            state['status'] = 'UNKNOWN' if state['phase'] in {'create_pending', 'update_pending'} else 'FAILED'
            state['error'] = exc.code if isinstance(exc, ConnectorError) else str(exc) if isinstance(exc, ProbeError) else 'invalid_provider_or_journal_shape'
            raise
        finally:
            state['events'].extend(api.events)
            save()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Keep this journal for every resume; never reset after an unknown create.')
    parser.add_argument('--write', action='store_true', help='Create/update one probe comment in the configured dedicated test target.')
    args = parser.parse_args(argv)
    try:
        cfg = validate_config(json.loads(args.config.read_text()))
        token = os.environ.get(cfg['token_env'])
        if not token: raise ProbeError('token_env_missing')
        result = run_probe(cfg, args.output, token=token, write=args.write)
    except (ProbeError, ConnectorError, ValueError, TypeError, KeyError, OSError):
        print(json.dumps({'status': 'FAILED_OR_UNKNOWN', 'details': 'See local probe.json; no automatic write retry.'}))
        return 1
    print(json.dumps({'status': result['status'], 'environment': result['environment'], 'journal': str(args.output / 'probe.json')}))
    return 0 if result['status'] in {'PASS', 'READ_ONLY'} else 1


if __name__ == '__main__':
    raise SystemExit(main())
