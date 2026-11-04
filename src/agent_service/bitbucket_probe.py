"""Read-only installation probe; does not register a runtime connector or open state."""
from __future__ import annotations

from .config import ServiceConfig, _secret, build_bitbucket_reader
from .http import ClientError


def probe(config: ServiceConfig, *, env_secret=_secret) -> dict:
    reader = build_bitbucket_reader(config, env_secret=env_secret)
    bb = config.bitbucket
    repositories = []
    for slug, expected in sorted(bb.repositories.items()):
        repo = reader.repository(slug)
        if repo.uuid != str(expected.uuid):
            raise ClientError('bitbucket_repository_identity_mismatch')
        if not repo.is_private:
            raise ClientError('bitbucket_private_repository_required')
        head = reader.branch(repo) if repo.default_branch is not None else None
        prs = reader.open_pull_requests(repo) if head is not None else ()
        repositories.append(dict(
            slug=repo.slug, uuid=repo.uuid, repository_id=expected.repository_id,
            empty=head is None, default_branch=repo.default_branch, default_head_sha=head,
            open_pull_requests=[dict(resource_id=pr.resource_id, number=pr.number, version=pr.version,
                state=pr.state, draft=pr.draft, source_repository_uuid=pr.source_repository_uuid,
                source_branch=pr.source_branch, destination_branch=pr.destination_branch,
                head_sha=pr.head_sha, destination_tip_sha=pr.base_sha) for pr in prs]))
    return dict(schema='agent-service-bitbucket-probe/1', status='READ_ONLY_VERIFIED', runtime_ready=False,
                workspace=bb.workspace, workspace_uuid=str(bb.workspace_uuid), repositories=repositories)
