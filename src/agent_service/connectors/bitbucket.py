"""GET-only Bitbucket polling intake. Git/core analysis and publication remain disconnected."""
from __future__ import annotations

import re

from .base import ResourceNotAllowed, Snapshot, WebhookRejected
from .github import jira_keys
from ..http import ClientError, NotFound


class BitbucketQueueConnector:
    provider = 'bitbucket'
    analysis_ready = False

    def __init__(self, reader, repositories, *, jira_project_keys=()):
        self.reader, self.repositories = reader, repositories
        self.jira_project_keys = list(jira_project_keys)
        self._by_uuid = {str(cfg.uuid): slug for slug, cfg in repositories.items()}

    def _repository(self, slug):
        repo = self.reader.repository(slug)
        if repo.uuid != str(self.repositories[slug].uuid):
            raise ClientError('bitbucket_repository_identity_mismatch')
        if not repo.is_private:
            raise ClientError('bitbucket_private_repository_required')
        return repo

    def _snapshot(self, pr):
        repo = pr.repository
        data = dict(provider=self.provider, repository=f'{repo.workspace}/{repo.slug}',
            workspace_uuid=repo.workspace_uuid, repository_uuid=repo.uuid,
            repository_id=self.repositories[repo.slug].repository_id, pr_id=pr.number,
            title=pr.title, description=pr.description, draft=pr.draft, state=pr.state,
            head_sha=pr.head_sha, destination_tip_sha=pr.base_sha,
            source_repository_uuid=pr.source_repository_uuid,
            head_ref=pr.source_branch, base_ref=pr.destination_branch,
            linked_jira_keys=jira_keys([pr.title, pr.description, pr.source_branch], self.jira_project_keys))
        return Snapshot(pr.resource_id, 'pr', pr.version, data, closed=pr.state != 'OPEN')

    def fetch(self, rid):
        match = re.fullmatch(r'bitbucket:([0-9a-f-]{36})/([0-9a-f-]{36})#([1-9][0-9]{0,18})', rid)
        if not match or match[1] != self.reader.workspace_uuid or match[2] not in self._by_uuid:
            raise ResourceNotAllowed('bitbucket_resource_not_configured')
        number = int(match[3])
        if number >= 2**63:
            raise ResourceNotAllowed('invalid_resource_id')
        repo = self._repository(self._by_uuid[match[2]])
        try:
            return self._snapshot(self.reader.pull_request(repo, number))
        except NotFound:
            return Snapshot(rid, 'pr', 'missing', {}, closed=True)

    def reconcile_candidates(self, since):
        candidates = []  # commit no partial listing/checkpoint if any repository fails
        for slug in sorted(self.repositories):
            repo = self._repository(slug)
            if repo.default_branch is None:
                continue
            for pr in self.reader.open_pull_requests(repo):
                snapshot = self._snapshot(pr)
                candidates.append((snapshot.resource_id, snapshot.version))
        return candidates

    def parse_webhook(self, headers, body):
        raise WebhookRejected(404, 'bitbucket_polling_only')

    def prepare(self, snapshot):
        raise ClientError('bitbucket_analysis_not_connected')
