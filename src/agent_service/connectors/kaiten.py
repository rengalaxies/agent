"""Scoped Kaiten v1 context/publication adapter, polling through Bitbucket.

No standalone task trigger or webhook authentication is implied here.
"""
from __future__ import annotations

import re
import threading
import time
from urllib.parse import urlsplit

from ..envelope import digest
from ..http import AuthError, ClientError, ConnectorError, NotFound, TransportError, segment
from .base import Comment, MARKER_RE, ResourceNotAllowed, Snapshot, parse_marker
from .tracker_contract import TaskIdentity, semantic_version

SEMANTIC_FIELDS = ('title', 'description', 'board_id', 'column_id', 'state', 'condition', 'archived', 'deleted')


def numeric_id(value):
    if isinstance(value, bool) or not isinstance(value, (str, int)) or not re.fullmatch(r'[1-9][0-9]{0,18}', str(value)):
        raise ClientError('invalid_kaiten_id')
    return str(value)


def render_comment(doc, marker):
    """Bounded plain Markdown with a single trusted Publisher marker line."""
    if not isinstance(marker, str) or MARKER_RE.fullmatch(marker) is None:
        raise ClientError('invalid_publication_marker')
    def clean(value):
        return str(value).replace('agent-service marker=', 'agent‑service marker=')
    # Status and limitations precede lengthy evidence; retain every section
    # heading/count on reduction instead of letting one item consume the budget.
    blocks = [clean(doc.get('title', 'Результат ImpactMap')), clean(doc.get('status_line', ''))]
    sections = [s for s in doc.get('sections', []) if isinstance(s, dict)]
    full = blocks + [clean(s.get('title', '')) + '\n' + '\n'.join('• ' + clean(i) for i in s.get('items', [])) for s in sections]
    text = '\n\n'.join(full)
    from ..ui_links import LABEL, validated_url
    url = validated_url(doc.get("ui_result_url"))
    link = "\n\n" + LABEL + ": " + url if url else ""
    budget = 4096 - len(marker) - 2 - len(link)
    if len(text) > budget:
        note = 'Текст сокращён. Полный результат сохранён в сервисе.'
        reduced = [blocks[0][:150], blocks[1][:700]]
        per_section = max(80, (budget - 1000) // max(len(sections), 1))
        for s in sections:
            items = s.get('items', [])
            block = clean(s.get('title', ''))[:80] + f' ({len(items)})\n' + '\n'.join('• ' + clean(i) for i in items)
            reduced.append(block[:per_section] + ('…' if len(block) > per_section else ''))
        text = '\n\n'.join(reduced)
        text = text[:budget - len(note) - 2] + '\n\n' + note
    return text + link + '\n\n' + marker


class KaitenConnector:
    def __init__(self, client, auth, *, board_ids, bot_id, request_interval=0.1):
        parts = urlsplit(client.base_url)
        local = parts.scheme == 'http' and parts.hostname in {'127.0.0.1', 'localhost', '::1'}
        cloud = parts.scheme == 'https' and re.fullmatch(r'[a-z0-9][a-z0-9-]*\.kaiten\.ru', parts.netloc or '')
        if parts.path or parts.query or parts.fragment or not (local or cloud):
            raise ValueError('invalid_kaiten_origin')
        if not board_ids: raise ValueError('kaiten_boards_required')
        self.client, self.auth = client, auth
        self.board_ids = {numeric_id(x) for x in board_ids}
        self.bot_id = numeric_id(bot_id)
        self.interval = request_interval
        self._lock, self._last = threading.Lock(), 0.0

    @property
    def bot_identity(self): return self.bot_id

    def identity(self, card_id):
        return TaskIdentity('kaiten', self.client.base_url, numeric_id(card_id))

    def _call(self, method, path, **kwargs):
        with self._lock:
            delay = self.interval - (time.monotonic() - self._last)
            if delay > 0: time.sleep(delay)
            self._last = time.monotonic()
            try:
                response = self.client.request(method, '/api/v1' + path, headers={'Authorization': self.auth()}, **kwargs)
            except ClientError as exc:
                if method != 'GET' and exc.status is not None and 200 <= exc.status < 300:
                    raise TransportError('invalid_kaiten_write_response') from None
                raise
        try:
            if response.status not in ({200, 201} if method == 'POST' else {200}): raise ValueError
            return response, response.json()
        except (ValueError, UnicodeError, RecursionError):
            if method != 'GET': raise TransportError('invalid_kaiten_write_response') from None
            raise ClientError('invalid_kaiten_response') from None

    def verify_bot(self):
        _, data = self._call('GET', '/users/current')
        if not isinstance(data, dict) or numeric_id(data.get('id')) != self.bot_id:
            raise AuthError('kaiten_bot_identity_mismatch', status=403)

    def read_card(self, card_id):
        card_id = numeric_id(card_id)
        identity = self.identity(card_id)
        rid = 'kaiten:' + digest(identity.as_list())[:16] + ':' + card_id
        try: _, data = self._call('GET', '/cards/' + segment(card_id))
        except NotFound: return Snapshot(rid, 'task', 'missing', {'card_id': card_id}, closed=True)
        if not isinstance(data, dict) or numeric_id(data.get('id')) != card_id:
            raise ClientError('kaiten_card_identity_mismatch')
        if numeric_id(data.get('board_id')) not in self.board_ids:
            return Snapshot(rid, 'task', 'out_of_scope:' + numeric_id(data['board_id']),
                            {'card_id':card_id,'unavailable_reason':'kaiten_board_not_configured'}, closed=True)
        if not isinstance(data.get('archived'), bool): raise ClientError('invalid_kaiten_card')
        for field in ('title', 'description'):
            if data.get(field) is not None and not isinstance(data[field], str): raise ClientError('invalid_kaiten_card')
        if 'deleted' in data and not isinstance(data['deleted'], bool): raise ClientError('invalid_kaiten_card')
        condition = data.get('condition', 1)
        if type(condition) is not int or condition not in {1,2,3}: raise ClientError('invalid_kaiten_card')
        closed = data['archived'] or data.get('deleted', False) or condition in {2,3}
        version = semantic_version(identity, data, SEMANTIC_FIELDS, closed=closed)
        context = {'card_id': card_id, 'board_id': str(data['board_id']), 'title': (data.get('title') or '')[:20000],
                   'description': (data.get('description') or '')[:20000], 'revision': version,
                   'context_truncated': any(len(data.get(k) or '') > 20000 for k in ('title', 'description'))}
        return Snapshot(rid, 'task', version, context, closed)

    def _available(self, card_id):
        task = self.read_card(card_id)
        if task.closed: raise ResourceNotAllowed('kaiten_card_unavailable')
        return task

    def _comment(self, card_id, item):
        if not isinstance(item, dict) or not isinstance(item.get('text'), str) or ('deleted' in item and not isinstance(item['deleted'], bool)):
            raise ClientError('invalid_kaiten_comment')
        if numeric_id(item.get('card_id')) != numeric_id(card_id): raise ClientError('kaiten_comment_target_mismatch')
        native, author = numeric_id(item.get('id')), numeric_id(item.get('author_id'))
        marker, body_digest, generation = parse_marker(item['text'])
        return Comment(native, author, marker, body_digest, generation)

    def _list(self, card_id):
        self._available(card_id)
        self.verify_bot()
        result, seen, offset = [], set(), 0
        for _ in range(100):
            response, data = self._call('GET', '/cards/' + segment(card_id) + '/comments', query={'limit':100,'offset':offset})
            applied = response.headers.get('x-pagination-limit', '')
            if not applied.isdigit() or not 1 <= int(applied) <= 100 or not isinstance(data, list) or len(data) > int(applied):
                raise ClientError('kaiten_listing_incomplete')
            for item in data:
                comment = self._comment(card_id, item)
                if comment.comment_id in seen: raise ClientError('kaiten_listing_incomplete')
                seen.add(comment.comment_id)
                if not item.get('deleted',False): result.append((comment,item['text']))
            if len(data) < int(applied): return result
            offset += int(applied)
        raise ClientError('kaiten_listing_incomplete')

    def list_comments(self, card_id):
        return [comment for comment,_ in self._list(card_id)]

    def get_comment(self, card_id, comment_id):
        native = numeric_id(comment_id)
        return next((c for c in self.list_comments(card_id) if c.comment_id == native), None)

    def _write(self, card_id, doc, marker, comment_id=None, before_write=None):
        self._available(card_id)
        self.verify_bot()
        text = render_comment(doc, marker)
        suffix = '/comments' + ('/' + segment(numeric_id(comment_id)) if comment_id else '')
        if before_write is not None: before_write()
        _, data = self._call('PATCH' if comment_id else 'POST', '/cards/' + segment(numeric_id(card_id)) + suffix, json_body={'text':text})
        try:
            comment = self._comment(card_id, data)
            if not isinstance(data.get('deleted'),bool) or data['deleted'] or data['text'] != text or comment.author != self.bot_id or (comment_id and comment.comment_id != comment_id): raise ValueError
        except (ClientError, ValueError, TypeError):
            raise TransportError('invalid_kaiten_write_response') from None
        try:
            found = [(c,t) for c,t in self._list(card_id) if c.comment_id==comment.comment_id]
            if len(found)!=1 or found[0][0].author!=self.bot_id or found[0][1]!=text:
                raise TransportError('kaiten_write_not_confirmed')
        except (ConnectorError,ResourceNotAllowed):
            raise TransportError('kaiten_write_not_confirmed') from None
        return comment.comment_id

    def create_comment(self, card_id, doc, marker, *, before_write=None):
        return self._write(card_id, doc, marker, before_write=before_write)

    def update_comment(self, card_id, comment_id, doc, marker, *, before_write=None):
        current = self.get_comment(card_id, comment_id)
        if current is None: raise NotFound(status=404)
        if current.author != self.bot_id or current.marker != parse_marker(marker)[0]:
            raise ResourceNotAllowed('kaiten_comment_not_owned')
        self._write(card_id, doc, marker, comment_id, before_write)
