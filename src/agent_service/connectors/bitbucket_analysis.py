"""Bitbucket analysis over scoped local Git mirrors, with publication held."""

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

    def __init__(self, reader, repositories, *, mirrors, refresh_mirrors=False, jira_project_keys=()):
        super().__init__(reader, repositories, jira_project_keys=jira_project_keys)
        self.refresh_mirrors = refresh_mirrors
        self.mirrors = {k: Path(v) for k, v in mirrors.items()}
        if set(self.mirrors) != {r.repository_id for r in repositories.values()} or any(
            not p.is_absolute() for p in self.mirrors.values()
        ):
            raise ValueError("bitbucket_mirror_scope_mismatch")

    def _refresh_mirror(self, git, repo):
        if git.dir != self.mirrors[self.repositories[repo.slug].repository_id]:
            raise GraphError("bitbucket_bare_mirror_required")
        settings = {
            "protocol.allow": "never",
            "protocol.https.allow": "always",
            "http.followRedirects": "false",
            "http.sslVerify": "true",
            "credential.helper": "",
            "http.https://bitbucket.org/.extraHeader":
                "Authorization: " + self.reader.auth.git_header(),
        }
        env = dict(git.env, GIT_CONFIG_COUNT=str(len(settings)))
        for index, (key, value) in enumerate(settings.items()):
            env[f"GIT_CONFIG_KEY_{index}"] = key
            env[f"GIT_CONFIG_VALUE_{index}"] = value
        url = f"https://bitbucket.org/{repo.workspace}/{repo.slug}.git"
        result = subprocess.run(
            git.argv("fetch", "--atomic", "--prune", "--no-tags", "--", url,
                     "+refs/heads/*:refs/heads/*"),
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30,
        )
        if result.returncode:
            raise GraphError("bitbucket_git_fetch_failed")

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
                if self.refresh_mirrors:
                    self._refresh_mirror(git, repo)
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
