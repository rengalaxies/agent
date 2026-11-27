"""Explicit Bitbucket→Kaiten binding with fresh source/target fences."""
from dataclasses import replace

from ..envelope import digest
from ..http import ClientError
from .base import ResourceNotAllowed, Snapshot
from .tracker_contract import CommentIdentity


class BitbucketKaitenConnector:
    provider = 'bitbucket'
    analysis_ready = True
    publication_ready = True

    def __init__(self, source, kaiten, *, bindings):
        self.source, self.kaiten, self.bindings = source, kaiten, dict(bindings)

    def parse_webhook(self, headers, body): return self.source.parse_webhook(headers, body)

    def fetch(self, rid):
        if rid not in self.bindings: raise ResourceNotAllowed('kaiten_binding_required')
        source = self.source.fetch(rid)
        card_id = self.bindings[rid]
        task = self.kaiten.read_card(card_id) if not source.closed else None
        version = 'bitbucket-kaiten:' + digest({'source':source.version,'target':self.kaiten.identity(card_id).as_list(), 'task':task.version if task else None})
        return Snapshot(rid, 'pr', version, {**source.data, '_tracker_target':card_id, '_tracker_context':task.data if task else {}, '_source_version':source.version}, source.closed or bool(task and task.closed))

    def prepare(self, snapshot):
        current = self.fetch(snapshot.resource_id)
        if current.closed or current.version != snapshot.version: raise ClientError('bitbucket_kaiten_snapshot_changed')
        source = self.source.fetch(snapshot.resource_id)
        if source.version != current.data['_source_version']: raise ClientError('bitbucket_kaiten_snapshot_changed')
        prepared = self.source.prepare(source)
        if self.fetch(snapshot.resource_id).version != snapshot.version: raise ClientError('bitbucket_kaiten_snapshot_changed')
        prepared.attachments['tracker_context'] = current.data['_tracker_context']
        if current.data['_tracker_context'].get('context_truncated'): prepared.gaps.append('kaiten_context_truncated')
        return prepared

    def reconcile_candidates(self, since):
        return [(rid,self.fetch(rid).version) for rid,_ in self.source.reconcile_candidates(since) if rid in self.bindings]


class BitbucketKaitenBackend:
    requires_publication_intent = True
    def __init__(self, bitbucket, kaiten):
        self.bitbucket, self.kaiten, self.store = bitbucket, kaiten, None

    @property
    def bot_identity(self): return self.kaiten.bot_identity
    def bind_store(self, store): self.store = store

    def _target(self, rid):
        source = self.bitbucket.fetch(rid)
        resource = self.store.resource(rid) if self.store else None
        if resource is None or source.version != resource['version']: raise ResourceNotAllowed('publication_source_changed')
        if source.closed: raise ResourceNotAllowed('linked_kaiten_unavailable')
        return source.data['_tracker_target']

    def _encode(self, target, comment):
        return replace(comment, comment_id=CommentIdentity(self.kaiten.identity(target), comment.comment_id).encode())

    def list_comments(self, rid):
        target = self._target(rid)
        comments = self.kaiten.list_comments(target)
        markers = [c.marker for c in comments if c.author == self.bot_identity and c.marker]
        if len(markers) != len(set(markers)): raise ResourceNotAllowed('duplicate_kaiten_result')
        return [self._encode(target,c) for c in comments]

    def _decode(self, rid, cid):
        target = self._target(rid)
        decoded = CommentIdentity.decode(cid,expected=self.kaiten.identity(target))
        return target,decoded.native_id

    def get_comment(self, rid, comment_id):
        target = self._target(rid)
        try: CommentIdentity.decode(comment_id,expected=self.kaiten.identity(target))
        except (ValueError,ResourceNotAllowed): return None
        # List also detects duplicate owned markers even on persisted-ID fast path.
        return next((c for c in self.list_comments(rid) if c.comment_id==comment_id),None)

    def _guard(self, rid, expected_intent):
        if not expected_intent or expected_intent.get('resource_id')!=rid or not self.store.intent_is_current(expected_intent):
            raise ResourceNotAllowed('publication_intent_changed')
        source=self.bitbucket.fetch(rid)
        if source.closed or source.version!=expected_intent['resource_version']:
            raise ResourceNotAllowed('publication_source_changed')
        return source.data['_tracker_target']

    def create_comment(self, rid, doc, marker, *, expected_intent=None):
        self._guard(rid,expected_intent)
        target=self._target(rid)
        native=self.kaiten.create_comment(target,doc,marker,before_write=lambda:self._guard(rid,expected_intent))
        return CommentIdentity(self.kaiten.identity(target),native).encode()

    def update_comment(self, rid, comment_id, doc, marker, *, expected_intent=None):
        self._guard(rid,expected_intent)
        target,native=self._decode(rid,comment_id)
        self.kaiten.update_comment(target,native,doc,marker,before_write=lambda:self._guard(rid,expected_intent))
