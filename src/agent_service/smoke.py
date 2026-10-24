"""Offline end-to-end smoke: ``python -m agent_service smoke``.

Real pieces: the batch 2A core on the Orders/Reporting Git stand, the
service queue and worker, the FastAPI webhook receiver on a local port, and
the GitHub/Jira HTTP stands from ``agent_service.stands``. Nothing leaves
127.0.0.1; no model is called. Exit code 0 only when every check passes.

Scenario: Jira ORD-12 → preliminary comment; PR #7 opened at a README-only
head → comment; push of an unclassified change, and while it is analyzed a
push of the real change (pr-7) → the unclassified head is superseded and the
same PR comment is updated with the pr-7 result.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid

from .connectors.github import GitHubConnector, StaticToken
from .connectors.jira import BasicAuth, JiraConnector, adf_text
from .core_analyzer import CoreAnalyzer
from .http import HttpClient
from .queue import Limits, ServiceStore
from .service import Service
from .stands import GitHubStand, JiraStand, sign

ORG = "acme"
STAND_PATH = Path(__file__).resolve().parents[2] / "examples" / "orders_reporting" / "stand.py"


def load_stand_module(path: Path = STAND_PATH):
    if not path.is_file():
        raise FileNotFoundError(f"orders_reporting stand not found at {path}")
    name = "orders_reporting_stand"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve annotations through sys.modules
    spec.loader.exec_module(module)
    return module


class Receiver:
    """The service's FastAPI webhook receiver on a free local port (uvicorn)."""

    def __init__(self, service, status_token: str | None = None):
        import uvicorn

        from .api import create_app

        self.server = uvicorn.Server(uvicorn.Config(create_app(service, status_token=status_token),
                                                    host="127.0.0.1", port=0, log_level="error", lifespan="off"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()
        deadline = time.time() + 10
        while not self.server.started:
            if time.time() > deadline:
                raise RuntimeError("receiver did not start")
            time.sleep(0.01)
        self.url = f"http://127.0.0.1:{self.server.servers[0].sockets[0].getsockname()[1]}"

    def close(self):
        self.server.should_exit = True
        self.thread.join(timeout=10)


def post(url, body: bytes, headers: dict) -> tuple[int, dict]:
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read())
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, json.loads(exc.read() or b"{}")


def get(url, headers: dict) -> tuple[int, str]:
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, ""


class SmokeBench:
    """Stands, core and service wired together; also used by tests/service."""

    STATUS_TOKEN = "smoke-status-token"

    def __init__(self, root: Path, *, policy_overrides: dict | None = None, ownership=True, runtime_sources=()):
        self.root = Path(root)
        stand_module = load_stand_module()
        self.stand = stand_module.build_stand(self.root / "stand")
        self.jira_issue = stand_module.JIRA_ISSUE
        self.gh_secret, self.jira_secret = secrets.token_bytes(16), secrets.token_bytes(16)
        self.github, self.jira = GitHubStand(), JiraStand()
        self.repos = {name: f"{ORG}/{name}" for name in self.stand.commits}
        for name, full in self.repos.items():
            self.github.branches[(full, "main")] = self.stand.head(name)
        self.github.add_pr(self.repos["orders"], 7, head=self.stand.head("orders", "readme-only"),
                           base=self.stand.head(), title="ORD-12 Reduce the default page size", head_ref="pr-7")
        fields = self.jira_issue["text_fields"]
        self.jira.add_issue(10012, self.jira_issue["key"], self.jira_issue["project"], fields["summary"],
                            fields["description"])
        # build_stand writes the installation mapping; the graph reads it on every reconciliation.
        self.ownership_path = self.stand.root / "ownership.json"
        self.analyzer = CoreAnalyzer(self.stand.policy(**(policy_overrides or {})), self.root / "core-state",
                                     ownership_path=str(self.ownership_path) if ownership else None,
                                     runtime_sources=runtime_sources, code_version="agent-service-smoke")
        self.during = None  # callable(request) run before the core analysis
        self.service = self._service()
        self.receiver = Receiver(self.service, status_token=self.STATUS_TOKEN)
        # What the installer's "initial graph" step does: code at the default branches and owners.
        self.service.reconcile_graph()

    def _service(self) -> Service:
        clock = time.time
        store = ServiceStore(self.root / "service" / "service.sqlite", clock=clock,
                             limits=Limits(create_settle_seconds=0))
        connectors = {
            "github": GitHubConnector(
                HttpClient(self.github.url, allow_loopback_http=True), StaticToken(self.github.token),
                repositories=[self.repos["orders"]], read_repositories={f: "main" for f in self.repos.values()},
                repository_ids={f: n for n, f in self.repos.items()}, jira_project_keys=["ORD"],
                bot_login=self.github.bot_login, webhook_secret=self.gh_secret, clock=clock),
            "jira": JiraConnector(HttpClient(self.jira.url, allow_loopback_http=True),
                                  BasicAuth("bot@example.invalid", "jira-test-token"), project_keys=["ORD"],
                                  bot_account_id=self.jira.bot_account_id, webhook_secret=self.jira_secret,
                                  clock=clock),
        }
        bench = self

        class Hooked:
            """The core analyzer with a test hook in front of each analysis."""

            def __getattr__(self, name):
                return getattr(bench.analyzer, name)

            def analyze(self, request, *, attachments, cancelled):
                if bench.during:
                    bench.during(request)
                return bench.analyzer.analyze(request, attachments=attachments, cancelled=cancelled)

        return Service(store=store, connectors=connectors, analyzer=Hooked(), installation_id="acme",
                       environment="prod", worker_id=uuid.uuid4().hex)

    def close(self):
        self.receiver.close()
        self.github.close()
        self.jira.close()
        self.analyzer.close()

    # -- deliveries -------------------------------------------------------

    def push(self, branch: str, *, deliver=True):
        head = self.stand.head("orders", branch)
        self.github.set_head(self.repos["orders"], 7, head)
        if deliver:
            return self.deliver_pr("synchronize")
        return None

    def deliver_pr(self, action: str):
        pr = self.github.prs[(self.repos["orders"], 7)]
        body = json.dumps({"action": action, "number": 7, "repository": {"full_name": self.repos["orders"]},
                           "pull_request": {"number": 7, "title": pr["title"], "head": dict(pr["head"]),
                                            "base": dict(pr["base"])}}).encode()
        return post(self.receiver.url + "/webhooks/github", body, {
            "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": uuid.uuid4().hex,
            "X-Hub-Signature-256": sign(self.gh_secret, body)})

    def deliver_jira(self, event="jira:issue_created", type_name="issue_created"):
        body = json.dumps({"webhookEvent": event, "issue_event_type_name": type_name, "timestamp": 1,
                           "issue": {"id": "10012", "key": "ORD-12", "fields": {"project": {"key": "ORD"}}}}).encode()
        return post(self.receiver.url + "/webhooks/jira", body, {
            "X-Atlassian-Webhook-Identifier": uuid.uuid4().hex, "X-Hub-Signature": sign(self.jira_secret, body)})

    def drain(self):
        return self.service.run_until_idle(200)

    def pr_comments(self):
        return self.github.service_comments(self.repos["orders"], 7)

    def jira_texts(self):
        return [adf_text(c["body"]) for c in self.jira.comments["10012"]]


def _section(text: str, start: str, end: str) -> str:
    head, _, rest = text.partition(start)
    return rest.partition(end)[0] if rest else ""


def run_smoke(root: Path) -> dict:
    checks = []

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    started = time.monotonic()
    bench = SmokeBench(root)
    try:
        status, _ = bench.deliver_jira()
        check("jira_delivery_accepted", status == 202, f"status={status}")
        bench.drain()
        texts = bench.jira_texts()
        check("jira_one_comment", len(texts) == 1, f"comments={len(texts)}")
        jira = texts[0] if texts else ""
        affected = _section(jira, "Что может затронуть", "Почему и через какой путь")
        check("jira_names_reporting_and_archive", "reporting:" in affected and "archive:" in affected, affected)
        # billing declares its own GET /orders, audit calls billing: neither is an Orders consumer.
        check("jira_excludes_audit_and_billing", "audit" not in affected and "billing" not in affected, affected)
        check("jira_owner_from_graph",
              "reporting: команда team-reporting (источник: installation_mapping@ownership-1)" in affected, affected)
        check("jira_graph_version", "graph_version: graph-" in jira)
        check("jira_says_preliminary", "jira_without_diff" in jira and "предварительный" in jira)

        status, _ = bench.deliver_pr("opened")
        check("pr_delivery_accepted", status == 202, f"status={status}")
        bench.drain()
        first = bench.pr_comments()
        check("pr_one_comment_for_readme_head", len(first) == 1 and "no_supported_delta" in first[0]["body"],
              first[0]["body"].splitlines()[0] if first else "none")
        comment_id = first[0]["id"] if first else None

        unclassified = bench.stand.head("orders", "unclassified")

        def push_real_change(request):
            if request["pr"] and request["pr"]["head_sha"] == unclassified:
                bench.during = None
                bench.push("pr-7")  # a newer head arrives while the core analyzes the older one

        bench.during = push_real_change
        bench.push("unclassified")
        bench.drain()
        final = bench.pr_comments()
        body = final[0]["body"] if final else ""
        pr7 = bench.stand.head("orders", "pr-7")
        check("pr_same_comment_updated", len(final) == 1 and final[0]["id"] == comment_id,
              f"comments={len(final)}")
        check("pr_shows_new_head", f"head {pr7[:12]}" in body)
        check("pr_shows_delta", "PAGE_DEFAULT_CHANGED 100 -> 20" in body)
        check("pr_reporting_truncation_at_callsite", "POSSIBLE_TRUNCATION у reporting: вызов reporting:client.py:" in body)
        check("pr_archive_only_recheck", "RECHECK_REQUIRED у archive" in body and "POSSIBLE_TRUNCATION у archive" not in body)
        reasons = _section(body, "Что может затронуть", "Что проверить")
        check("pr_audit_not_a_consumer", "audit" not in reasons and "billing" not in reasons)
        # Only a "previous result is stale" notice may name the superseded head; never a result for it.
        results = [b for b in bench.github.written if not b.startswith("### Предыдущий вывод устарел")]
        check("superseded_head_never_published", all(unclassified[:12] not in b for b in results),
              f"writes={len(bench.github.written)}")
        check("pr_single_create", bench.github.count("POST", r"/repos/acme/orders/issues/7/comments") == 1)
        jobs = bench.service.store.jobs("github:acme/orders#7")
        check("generations_superseded_then_done", [j["state"] for j in jobs][-2:] == ["SUPERSEDED", "DONE"],
              ",".join(j["state"] for j in jobs))
        status, _ = get(bench.receiver.url + "/graph", {})
        check("graph_view_requires_token", status == 401, f"status={status}")
        status, page = get(bench.receiver.url + "/graph", {"Authorization": f"Bearer {bench.STATUS_TOKEN}"})
        check("graph_view_shows_paths", status == 200 and "reporting" in page and "Граф зависимостей" in page,
              f"status={status}")
    finally:
        bench.close()
    return {"ok": all(c["ok"] for c in checks), "seconds": round(time.monotonic() - started, 1), "checks": checks}


def main(keep: str | None = None) -> int:
    root = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="agent-service-smoke-"))
    try:
        report = run_smoke(root)
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    # ASCII JSON: the installer parses it whatever the console encoding is.
    sys.stdout.write(json.dumps(report, ensure_ascii=True, indent=2) + "\n")
    return 0 if report["ok"] else 1
