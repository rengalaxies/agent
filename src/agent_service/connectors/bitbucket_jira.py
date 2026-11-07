"""Jira publication backend for explicitly linked Bitbucket PRs."""
from dataclasses import replace

from .base import ResourceNotAllowed


class BitbucketJiraBackend:
    def __init__(self, bitbucket, jira):
        self.bitbucket = bitbucket
        self.jira = jira
        self.store = None

    def bind_store(self, store):
        self.store = store

    @property
    def bot_identity(self):
        return self.jira.bot_identity

    def _target(self, rid):
        source = self.bitbucket.fetch(rid)
        if self.store is None:
            raise ResourceNotAllowed("publication_store_required")
        resource = self.store.resource(rid)
        if resource is None or source.version != resource["version"]:
            raise ResourceNotAllowed("publication_source_changed")
        keys = source.data.get("linked_jira_keys", [])
        if source.closed or len(keys) != 1:
            raise ResourceNotAllowed("exactly_one_linked_jira_required")
        target = self.jira.resolve_key(keys[0])
        if target.closed:
            raise ResourceNotAllowed("linked_jira_unavailable")
        return target.resource_id

    @staticmethod
    def _encode(target, comment):
        return replace(comment, comment_id=target + "|" + comment.comment_id)

    def list_comments(self, rid):
        target = self._target(rid)
        return [self._encode(target, c) for c in self.jira.list_comments(target)]

    def _decode(self, rid, comment_id):
        target, separator, native_id = comment_id.partition("|")
        if not separator or target != self._target(rid):
            raise ResourceNotAllowed("linked_jira_changed")
        return target, native_id

    def get_comment(self, rid, comment_id):
        target, native_id = self._decode(rid, comment_id)
        comment = self.jira.get_comment(target, native_id)
        return self._encode(target, comment) if comment else None

    def create_comment(self, rid, doc, marker):
        target = self._target(rid)
        native_id = self.jira.create_comment(target, doc, marker)
        return target + "|" + native_id

    def update_comment(self, rid, comment_id, doc, marker):
        target, native_id = self._decode(rid, comment_id)
        self.jira.update_comment(target, native_id, doc, marker)
