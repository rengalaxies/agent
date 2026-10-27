"""One change on its own stand: Git repositories, local GitHub/Jira HTTP stands and the real service.

The wiring is ``agent_service.smoke.SmokeBench`` generalised to any readiness
change: the batch 2A core and batch 3 graph behind ``CoreAnalyzer``, the
SQLite queue and worker, the FastAPI webhook receiver on 127.0.0.1, and the
``agent_service.stands`` HTTP stands. Git commits are written with the
Orders/Reporting stand's plumbing (fixed author, committer and dates), so the
same change file always gives the same commit SHAs. Nothing leaves 127.0.0.1.

The stands also record when each comment write was accepted, which the runner
uses for latency, and the GitHub stand answers ``compare`` from the real
repositories instead of the smoke's fixed Orders diff.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import secrets
import subprocess
import time
import uuid

from agent_service.connectors.github import GitHubConnector, StaticToken
from agent_service.connectors.jira import BasicAuth, JiraConnector, adf_text
from agent_service.core_analyzer import CoreAnalyzer
from agent_service.http import HttpClient
from agent_service.queue import Limits, ServiceStore
from agent_service.service import Service
from agent_service.smoke import Receiver, load_stand_module, post
from agent_service.stands import GitHubStand, JiraStand, sign
from tools.autonomous_mvp.readiness import world

RUNTIME_WINDOW_SECONDS = 3 * 86400  # long enough to read a two-day-old window, so staleness is visible
CODE_VERSION = f"readiness-{world.CURRENT}"


# ---------------------------------------------------------------------------- Git


def materialize(change: dict, root: Path) -> dict[str, dict[str, str]]:
    """Write every repository and branch as real commits; return {repo: {branch: sha}}."""
    plumbing = load_stand_module()
    root = Path(root)
    home = root / "git-home"
    home.mkdir(parents=True)
    (home / "gitconfig").write_text("")
    env = plumbing.git_env(home)
    commits = {}
    for name, spec in change["repositories"].items():
        repo = root / "repos" / name
        repo.mkdir(parents=True)
        subprocess.run(["git", "init", "-q", "--initial-branch=main", str(repo)], env=env, check=True,
                       stdout=subprocess.DEVNULL)
        plumbing._git(repo, env, "config", "core.autocrlf", "false")
        branches = {}
        # Parents first: change files store branches with sorted keys ("change" before "main").
        for branch, data in sorted(spec["branches"].items(), key=lambda kv: (kv[1]["parent"] is not None, kv[0])):
            tree = plumbing._tree(repo, env, data["files"])
            args = ["commit-tree", tree, "-m", f"{name}: {branch}"]
            if data["parent"]:
                args += ["-p", branches[data["parent"]]]
            branches[branch] = plumbing._git(repo, env, *args)
            plumbing._git(repo, env, "update-ref", f"refs/heads/{branch}", branches[branch])
        commits[name] = branches
    return commits


def git_out(repo: Path, *args) -> str:
    out = subprocess.run(["git", "--git-dir", str(Path(repo) / ".git"), *args], stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, check=True)
    return out.stdout.decode("utf-8")


# ---------------------------------------------------------------------------- stands


class RecordingGitHub(GitHubStand):
    """GitHub stand with timestamps of accepted comment writes and real compare output."""

    def __init__(self, repo_roots: dict[str, Path]):
        super().__init__()
        self.repo_roots = repo_roots  # "acme/orders" -> local repository
        self.writes: list[tuple[float, str, str]] = []  # (time, method, path)

    def route(self, method, path, query, headers, body):
        m = re.fullmatch(r"/repos/([^/]+)/([^/]+)/compare/([0-9a-f]+)(?:\.\.\.|%2E%2E%2E)([0-9a-f]+)", path)
        if method == "GET" and m and headers.get("authorization") == f"Bearer {self.token}":
            root = self.repo_roots.get(f"{m.group(1)}/{m.group(2)}")
            if root is not None:
                base, head = m.group(3), m.group(4)
                if headers.get("accept") == "application/vnd.github.diff":
                    return 200, git_out(root, "diff", base, head), {"content-type": "text/x-diff"}
                names = [n for n in git_out(root, "diff", "--name-only", base, head).splitlines() if n]
                return 200, {"files": [{"filename": n} for n in names], "merge_base_commit": {"sha": base}}, {}
        status, payload, headers_out = super().route(method, path, query, headers, body)
        if method in ("POST", "PATCH") and "/comments" in path and status in (200, 201):
            self.writes.append((time.time(), method, path))
        return status, payload, headers_out


class RecordingJira(JiraStand):
    def __init__(self):
        super().__init__()
        self.writes: list[tuple[float, str, str]] = []

    def route(self, method, path, query, headers, body):
        status, payload, headers_out = super().route(method, path, query, headers, body)
        if method in ("POST", "PUT") and "/comment" in path and status in (200, 201):
            self.writes.append((time.time(), method, path))
        return status, payload, headers_out


# ---------------------------------------------------------------------------- policy and sources


def policy(change: dict, root: Path, commits: dict, *, include_revoked: bool, model: dict | None = None) -> dict:
    """``model``: the ModelConfig of a model configuration, with the 2B read window; None runs without one."""
    revoked = set(change["grants"]["revoked"])
    names = [n for n in change["repositories"] if include_revoked or n not in revoked]
    out = dict(
        installation_id=change["installation_id"], environment=change["environment"], subject="readiness-6",
        capabilities=["read_context", "maintain", "propose", "report_check"],
        repositories=[dict(id=n, service=change["repositories"][n]["service"], root=str(root / "repos" / n),
                           snapshot="git", revision=commits[n]["main"]) for n in names],
        addresses=change["addresses"], requirements=[])
    if model is not None:
        from tools.autonomous_mvp.readiness.live import READ_WINDOW

        out.update(model=model, limits=dict(max_tool_lines=READ_WINDOW))
    return out


def write_runtime_logs(change: dict, directory: Path, now: datetime) -> list[dict]:
    """access-log-segment-1 windows relative to ``now``; returns the AccessLogSource configuration."""
    runtime = change.get("runtime")
    if not runtime:
        return []
    directory.mkdir(parents=True, exist_ok=True)
    now = now.replace(microsecond=0)
    for segment in runtime["segments"]:
        end = now - timedelta(minutes=segment["end_minutes_ago"])
        start = end - timedelta(minutes=segment["minutes"])
        lines = [json.dumps(dict(ts=(start + timedelta(seconds=i + 1)).isoformat(), service=runtime["instrumented"][0],
                                 env=change["environment"], **r))
                 for i, r in enumerate(segment["records"])]
        data = (("\n".join(lines) + "\n") if lines else "").encode()
        (directory / f"{segment['name']}.jsonl").write_bytes(data)
        (directory / f"{segment['name']}.coverage.json").write_text(json.dumps(dict(
            schema="access-log-segment-1", file=f"{segment['name']}.jsonl", emitter=runtime["instrumented"][0],
            environment=change["environment"], start=start.isoformat(), end=end.isoformat(), sample_rate=1.0,
            sha256=hashlib.sha256(data).hexdigest())))
    return [dict(id=runtime["source_id"], installation_id=change["installation_id"],
                 environment=change["environment"], root=str(directory),
                 identities=[dict(alias=s, service=s) for s in change["repositories"]],
                 instrumented_services=list(runtime["instrumented"]))]


# ---------------------------------------------------------------------------- bench


class ChangeBench:
    """Stands, core and service for one change.

    Without ``model_section`` the model is off. With it the service gets that ModelConfig, the
    qualification reference and ``model`` (the object that answers; None builds the policy's ChatModel),
    and the analyzer's own qualification check decides whether the model is ever called.
    """

    def __init__(self, change: dict, root: Path, *, model_section: dict | None = None,
                 qualification: dict | None = None, model=None):
        self.change, self.root = change, Path(root)
        self.started = time.monotonic()
        self.commits = materialize(change, self.root / "stand")
        org = change["org"]
        self.full = {name: f"{org}/{name}" for name in change["repositories"]}
        revoked = set(change["grants"]["revoked"])
        self.readable = {n: f for n, f in self.full.items() if n not in revoked}
        self.provider = change["pr"]["repository"]
        self.gh_secret, self.jira_secret = secrets.token_bytes(16), secrets.token_bytes(16)
        self.github = RecordingGitHub({f: self.root / "stand" / "repos" / n for n, f in self.full.items()})
        self.jira = RecordingJira()
        for name, full in self.full.items():
            self.github.branches[(full, "main")] = self.commits[name]["main"]
        jira = change["jira"]
        self.issue_id = str(jira["issue_id"])
        self.jira.add_issue(jira["issue_id"], jira["key"], jira["project"], jira["summary"], jira["description"])
        (self.root / "stand" / "ownership.json").write_text(json.dumps(change["ownership"], indent=2, sort_keys=True))
        self.ownership_path = self.root / "stand" / "ownership.json"
        self.runtime_sources = write_runtime_logs(change, self.root / "stand" / "logs", datetime.now(timezone.utc))
        state = self.root / "core-state"
        if revoked:
            # The revoked repositories were readable earlier: a wider policy synced them into the graph.
            earlier = CoreAnalyzer(policy(change, self.root / "stand", self.commits, include_revoked=True), state,
                                   ownership_path=str(self.ownership_path), runtime_sources=self.runtime_sources,
                                   code_version=CODE_VERSION, runtime_window_seconds=RUNTIME_WINDOW_SECONDS)
            try:
                earlier.reconcile_graph({n: c["main"] for n, c in self.commits.items()})
            finally:
                earlier.close()
        self.analyzer = CoreAnalyzer(policy(change, self.root / "stand", self.commits, include_revoked=False,
                                            model=model_section), state,
                                     ownership_path=str(self.ownership_path), runtime_sources=self.runtime_sources,
                                     code_version=CODE_VERSION, model=model, model_qualification=qualification,
                                     runtime_window_seconds=RUNTIME_WINDOW_SECONDS)
        self.service = self._service()
        self.receiver = Receiver(self.service)
        self.initial_graph = self.service.reconcile_graph()
        self.setup_seconds = time.monotonic() - self.started

    def _service(self) -> Service:
        clock = time.time
        store = ServiceStore(self.root / "service" / "service.sqlite", clock=clock,
                             limits=Limits(create_settle_seconds=0))
        project = self.change["jira"]["project"]
        connectors = {
            "github": GitHubConnector(
                HttpClient(self.github.url, allow_loopback_http=True), StaticToken(self.github.token),
                repositories=[self.full[self.provider]], read_repositories={f: "main" for f in self.readable.values()},
                repository_ids={f: n for n, f in self.readable.items()}, jira_project_keys=[project],
                bot_login=self.github.bot_login, webhook_secret=self.gh_secret, clock=clock),
            "jira": JiraConnector(HttpClient(self.jira.url, allow_loopback_http=True),
                                  BasicAuth("bot@example.invalid", "jira-test-token"), project_keys=[project],
                                  bot_account_id=self.jira.bot_account_id, webhook_secret=self.jira_secret,
                                  clock=clock),
        }
        return Service(store=store, connectors=connectors, analyzer=self.analyzer,
                       installation_id=self.change["installation_id"], environment=self.change["environment"],
                       worker_id=uuid.uuid4().hex)

    def close(self):
        self.receiver.close()
        self.github.close()
        self.jira.close()
        self.analyzer.close()

    # -- deliveries -------------------------------------------------------

    @property
    def pr_key(self):
        return (self.full[self.provider], self.change["pr"]["number"])

    def open_pr(self):
        pr = self.change["pr"]
        self.github.add_pr(self.full[self.provider], pr["number"], head=self.commits[self.provider][pr["head_branch"]],
                           base=self.commits[self.provider][pr["base_branch"]], title=pr["title"],
                           head_ref=f"{self.change['jira']['key'].lower()}-{pr['head_branch']}")

    def deliver_pr(self, action: str, delivery: str | None = None):
        pr = self.github.prs[self.pr_key]
        number = self.change["pr"]["number"]
        body = json.dumps({"action": action, "number": number, "repository": {"full_name": self.full[self.provider]},
                           "pull_request": {"number": number, "title": pr["title"], "head": dict(pr["head"]),
                                            "base": dict(pr["base"])}}).encode()
        return post(self.receiver.url + "/webhooks/github", body, {
            "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": delivery or uuid.uuid4().hex,
            "X-Hub-Signature-256": sign(self.gh_secret, body)})

    def deliver_jira(self, delivery: str | None = None):
        jira = self.change["jira"]
        body = json.dumps({"webhookEvent": "jira:issue_created", "issue_event_type_name": "issue_created",
                           "timestamp": 1, "issue": {"id": self.issue_id, "key": jira["key"],
                                                     "fields": {"project": {"key": jira["project"]}}}}).encode()
        return post(self.receiver.url + "/webhooks/jira", body, {
            "X-Atlassian-Webhook-Identifier": delivery or uuid.uuid4().hex,
            "X-Hub-Signature": sign(self.jira_secret, body)})

    def drain(self):
        return self.service.run_until_idle(200)

    # -- observations ------------------------------------------------------

    def pr_comments(self):
        return self.github.service_comments(*self.pr_key)

    def jira_comments(self):
        return [dict(id=c["id"], body=adf_text(c["body"])) for c in self.jira.comments[self.issue_id]
                if c["author"]["accountId"] == self.jira.bot_account_id]

    def pr_resource(self):
        return f"github:{self.full[self.provider]}#{self.change['pr']['number']}"

    def jira_resource(self):
        return f"jira:{self.issue_id}"
