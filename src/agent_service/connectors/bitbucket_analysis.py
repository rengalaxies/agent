"""Explicit local-worker adapter over pre-fetched operator-owned mirrors.

Not enabled by the installation factory. Publication remains independently held.
"""

from pathlib import Path
import subprocess
import time

from agent_graph.contracts import GraphError
from agent_graph.git_sources import GitReader
from ..http import ClientError
from .base import Prepared
from .bitbucket import BitbucketQueueConnector


class BitbucketLocalAnalysisConnector(BitbucketQueueConnector):
    analysis_ready = True
    publication_ready = False

    def __init__(self, reader, repositories, *, mirrors, jira_project_keys=()):
        super().__init__(reader, repositories, jira_project_keys=jira_project_keys)
        self.mirrors = {k: Path(v) for k, v in mirrors.items()}
        if set(self.mirrors) != {r.repository_id for r in repositories.values()} or any(
            not p.is_absolute() for p in self.mirrors.values()
        ):
            raise ValueError("bitbucket_mirror_scope_mismatch")

    def prepare(self, snapshot):
        current = self.fetch(snapshot.resource_id)
        if current.closed or current.version != snapshot.version:
            raise ClientError("bitbucket_snapshot_changed")
        data = current.data
        if data["source_repository_uuid"] != data["repository_uuid"]:
            raise ClientError("bitbucket_fork_analysis_unsupported")
        mainline = {}
        try:
            for slug, cfg in self.repositories.items():
                repo = self._repository(slug)
                sha = self.reader.branch(repo)
                git = GitReader(
                    self.mirrors[cfg.repository_id], deadline=time.monotonic() + 30
                )
                if git.resolve(sha, ["refs/heads/*"]) is None:
                    raise GraphError("revision_unavailable")
                mainline[cfg.repository_id] = sha
            git = GitReader(
                self.mirrors[data["repository_id"]], deadline=time.monotonic() + 30
            )
            for sha in [data["head_sha"], data["destination_tip_sha"]]:
                if git.resolve(sha, ["refs/heads/*"]) is None:
                    raise GraphError("revision_unavailable")
            out = subprocess.run(
                git.argv("merge-base", data["destination_tip_sha"], data["head_sha"]),
                env=git.env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if out.returncode:
                raise GraphError("merge_base_unavailable")
            base = out.stdout.strip()
            if git.resolve(base, ["refs/heads/*"]) is None:
                raise GraphError("revision_unavailable")
        except (GraphError, OSError, subprocess.SubprocessError):
            raise ClientError("bitbucket_git_unavailable") from None
        subject = {**data, "base_sha": base}
        return Prepared(
            subject,
            {**mainline, data["repository_id"]: data["head_sha"]},
            attachments={
                "mainline_revisions": mainline,
                "linked_jira_keys": data["linked_jira_keys"],
            },
        )
