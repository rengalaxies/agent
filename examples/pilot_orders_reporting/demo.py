"""Local show of the autonomous service on the M2-A pilot sources.

LOCAL, not LIVE. Real pieces: the Git repositories from prepare.py, the core
analyzer, the service queue and worker, the FastAPI webhook receiver with
signature checks and the SQLite state. GitHub and Jira are the loopback stands
from agent_service.stands, so no comment leaves 127.0.0.1. MODEL OFF.

Scenario (each step is a signed webhook, then the worker drains the queue):
1. Jira APILOT-1 asks to reduce the Orders page size: preliminary comment.
2. PR #1 opens at pilot-page-limit (100 -> 20): impact on Reporting.
3. The same PR is pushed to pilot-restored (back to 100): the same comment is updated.
4. PR #2 opens at pilot-docs-only: neutral control, no impact claimed.
5. The service restarts on the same state and reconciles: nothing is duplicated.

Writes <out>/demo.json (bodies, versions, checks) and <out>/site/ (static viewer).
Usage: python examples/pilot_orders_reporting/demo.py <new-output-directory>
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import secrets
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from agent_graph import PROFILE  # noqa: E402
from agent_service.connectors.github import GitHubConnector, StaticToken  # noqa: E402
from agent_service.connectors.jira import BasicAuth, JiraConnector, adf_text  # noqa: E402
from agent_service.core_analyzer import CoreAnalyzer  # noqa: E402
from agent_service.http import HttpClient  # noqa: E402
from agent_service.queue import Limits, ServiceStore  # noqa: E402
from agent_service.service import Service  # noqa: E402
from agent_service.smoke import Receiver, post  # noqa: E402
from agent_service.stands import GitHubStand, JiraStand, sign  # noqa: E402
from examples.pilot_orders_reporting.prepare import prepare  # noqa: E402
from examples.pilot_orders_reporting.site import write_site  # noqa: E402

INSTALLATION = "agent-pilot"
ORDERS, REPORTING = "rengalaxies/agent-pilot-orders", "rengalaxies/agent-pilot-reporting"
ISSUE = dict(id="10001", key="APILOT-1", project="APILOT",
             summary="Orders: уменьшить размер страницы GET /orders до 20",
             description="GET /orders: default page_size 100 -> 20.")
OWNERSHIP = dict(source="installation_mapping", version="pilot-ownership-1",
                 services=dict(orders="team-orders", reporting="team-reporting"))
REQUIREMENT = ROOT / "examples/pilot_orders_reporting/reporting/export-requirement.md"


def policy(repositories: Path, pins: dict) -> dict:
    return dict(
        installation_id=INSTALLATION, environment="test", subject="pilot-demo",
        capabilities=["read_context", "maintain", "propose", "report_check"],
        repositories=[dict(id=name, service=name, root=str(repositories / name), snapshot="git", revision=sha)
                      for name, sha in pins.items()],
        addresses=[dict(service="orders", base_url="https://orders.pilot.invalid")],
        requirements=[dict(id="R-pilot-export-all", repository="reporting", path="export-requirement.md",
                           sha256=hashlib.sha256(REQUIREMENT.read_bytes()).hexdigest(),
                           issuer="M2-A author test condition", consumer="reporting", service="orders",
                           path_template="/orders", predicate="complete_collection")])


class Bench:
    """Stands and one running service instance over a persistent state directory."""

    def __init__(self, out: Path, prepared: dict):
        self.out, self.prepared = out, prepared
        self.commits = {name: item["commits"] for name, item in prepared["repositories"].items()}
        self.gh_secret, self.jira_secret = secrets.token_bytes(16), secrets.token_bytes(16)
        self.github, self.jira = GitHubStand(), JiraStand()
        self.github.branches[(ORDERS, "main")] = self.commits["orders"]["main"]
        self.github.branches[(REPORTING, "main")] = self.commits["reporting"]["main"]
        self.jira.add_issue(int(ISSUE["id"]), ISSUE["key"], ISSUE["project"], ISSUE["summary"], ISSUE["description"])
        (out / "ownership.json").write_text(json.dumps(OWNERSHIP, indent=2, sort_keys=True) + "\n")
        pins = {name: commits["main"] for name, commits in self.commits.items()}
        self.policy = policy(out / "repositories", pins)
        self.service = self.receiver = self.analyzer = None

    def start(self):
        clock = time.time
        self.analyzer = CoreAnalyzer(self.policy, self.out / "state" / "core",
                                     ownership_path=str(self.out / "ownership.json"),
                                     code_version=code_version())
        store = ServiceStore(self.out / "state" / "service.sqlite", clock=clock,
                             limits=Limits(create_settle_seconds=0))
        connectors = {
            "github": GitHubConnector(
                HttpClient(self.github.url, allow_loopback_http=True), StaticToken(self.github.token),
                repositories=[ORDERS], read_repositories={ORDERS: "main", REPORTING: "main"},
                repository_ids={ORDERS: "orders", REPORTING: "reporting"}, jira_project_keys=["APILOT"],
                bot_login=self.github.bot_login, webhook_secret=self.gh_secret, clock=clock),
            "jira": JiraConnector(HttpClient(self.jira.url, allow_loopback_http=True),
                                  BasicAuth("bot@example.invalid", "jira-test-token"), project_keys=["APILOT"],
                                  bot_account_id=self.jira.bot_account_id, webhook_secret=self.jira_secret,
                                  clock=clock),
        }
        self.service = Service(store=store, connectors=connectors, analyzer=self.analyzer,
                               installation_id=INSTALLATION, environment="test", worker_id=uuid.uuid4().hex)
        self.receiver = Receiver(self.service, status_token=secrets.token_hex(16))
        # What the installer's "initial graph" step does: code at the default branches and owners.
        self.service.reconcile_graph()

    def stop(self):
        self.receiver.close()
        self.analyzer.close()

    def close(self):
        self.github.close()
        self.jira.close()

    def deliver_pr(self, number: int, action: str):
        pr = self.github.prs[(ORDERS, number)]
        body = json.dumps({"action": action, "number": number, "repository": {"full_name": ORDERS},
                           "pull_request": {"number": number, "title": pr["title"], "head": dict(pr["head"]),
                                            "base": dict(pr["base"])}}).encode()
        delivery = uuid.uuid4().hex
        status, _ = post(self.receiver.url + "/webhooks/github", body, {
            "X-GitHub-Event": "pull_request", "X-GitHub-Delivery": delivery,
            "X-Hub-Signature-256": sign(self.gh_secret, body)})
        return {"provider": "github", "event": f"pull_request.{action}", "delivery": delivery, "http_status": status}

    def deliver_jira(self):
        body = json.dumps({"webhookEvent": "jira:issue_created", "issue_event_type_name": "issue_created",
                           "timestamp": 1, "issue": {"id": ISSUE["id"], "key": ISSUE["key"],
                                                     "fields": {"project": {"key": ISSUE["project"]}}}}).encode()
        delivery = uuid.uuid4().hex
        status, _ = post(self.receiver.url + "/webhooks/jira", body, {
            "X-Atlassian-Webhook-Identifier": delivery, "X-Hub-Signature": sign(self.jira_secret, body)})
        return {"provider": "jira", "event": "jira:issue_created", "delivery": delivery, "http_status": status}

    def snapshot(self) -> dict:
        """Every comment the service has published, as a provider shows it now."""
        comments = {}
        for number in sorted(n for (repo, n) in self.github.prs if repo == ORDERS):
            comments[f"{ORDERS}#{number}"] = [{"id": str(c["id"]), "body": c["body"]}
                                               for c in self.github.service_comments(ORDERS, number)]
        comments[ISSUE["key"]] = [{"id": str(c["id"]), "body": adf_text(c["body"])}
                                  for c in self.jira.comments.get(ISSUE["id"], [])]
        return comments


def code_version() -> str:
    try:
        return subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def run(out: Path) -> dict:
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    prepared = prepare(out / "repositories")
    bench = Bench(out, prepared)
    steps, checks = [], []

    def step(key, title, action, event=None):
        drained = bench.service.run_until_idle(200)
        steps.append({"key": key, "title": title, "action": action, "event": event, "worker_steps": drained,
                      "at": datetime.now(timezone.utc).isoformat(), "comments": bench.snapshot(),
                      "graph_html": bench.analyzer.graph_html()})

    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})

    try:
        bench.start()
        orders = bench.commits["orders"]
        event = bench.deliver_jira()
        step("jira", "Задача в Jira", "Создана задача APILOT-1: уменьшить размер страницы GET /orders до 20.",
             event)
        bench.github.add_pr(ORDERS, 1, head=orders["pilot-page-limit"], base=orders["main"],
                            title="APILOT-1 Reduce the default page size", head_ref="pilot-page-limit")
        event = bench.deliver_pr(1, "opened")
        step("pr_opened", "PR с изменением", "Открыт PR #1: page_size по умолчанию 100 -> 20.", event)
        bench.github.set_head(ORDERS, 1, orders["pilot-restored"])
        event = bench.deliver_pr(1, "synchronize")
        step("pr_fixed", "Исправление в том же PR", "В PR #1 запушен pilot-restored: значение снова 100.", event)
        bench.github.add_pr(ORDERS, 2, head=orders["pilot-docs-only"], base=orders["main"],
                            title="Document GET /orders pagination", head_ref="pilot-docs-only")
        event = bench.deliver_pr(2, "opened")
        step("docs_only", "Нейтральный контроль", "Открыт PR #2: меняется только README, API прежний.", event)
        bench.stop()
        bench.start()  # the same SQLite and core state, as after a host restart
        reconciled = bench.service.reconcile()
        step("restart", "Перезапуск сервиса", "Сервис перезапущен на том же state и выполнил reconcile.",
             {"provider": "service", "event": "reconcile",
              "result": {k: reconciled[k] for k in ("recovered", "revived", "enqueued", "reanalysed")
                         if k in reconciled}})
        history = len(bench.service.store.history())
        bench.stop()
    finally:
        bench.close()

    by = {s["key"]: s["comments"] for s in steps}
    pr1, pr2, jira = f"{ORDERS}#1", f"{ORDERS}#2", ISSUE["key"]
    check("jira_preliminary_comment", len(by["jira"][jira]) == 1 and "предварительный" in by["jira"][jira][0]["body"])
    check("pr_change_names_reporting", len(by["pr_opened"][pr1]) == 1 and "reporting" in by["pr_opened"][pr1][0]["body"]
          and "100 -> 20" in by["pr_opened"][pr1][0]["body"])
    check("fix_updates_the_same_comment", len(by["pr_fixed"][pr1]) == 1
          and by["pr_fixed"][pr1][0]["id"] == by["pr_opened"][pr1][0]["id"]
          and "POSSIBLE_TRUNCATION у reporting. В текущей версии не обнаружено" in by["pr_fixed"][pr1][0]["body"]
          and "Потребители не названы" in by["pr_fixed"][pr1][0]["body"])
    check("docs_only_claims_no_change", len(by["docs_only"][pr2]) == 1 and "100 -> 20" not in by["docs_only"][pr2][0]["body"])
    check("restart_keeps_one_comment_per_resource",
          all(len(by["restart"][k]) == 1 for k in (pr1, pr2, jira))
          and [c["id"] for k in (pr1, pr2, jira) for c in by["restart"][k]]
          == [c["id"] for k in (pr1, pr2, jira) for c in by["docs_only"][k]])
    report = {
        "schema": "pilot-local-demo-1", "level": "LOCAL", "model": "OFF",
        "not": ["LIVE", "INSTALLED", "REAL_API", "independent project", "customer value"],
        "code_version": code_version(), "profile": PROFILE, "python": platform.python_version(),
        "sources": {"generator": "examples/pilot_orders_reporting/prepare.py", "commits": bench.commits,
                    "author": "M2-A author sources, not an independent project"},
        "stands": "agent_service.stands GitHubStand/JiraStand on 127.0.0.1",
        "history_entries": history, "steps": steps, "checks": checks,
        "status": "PASS" if all(c["ok"] for c in checks) else "FAIL",
    }
    (out / "demo.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_site(report, out / "site")
    return report


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    result = run(Path(sys.argv[1]))
    print(json.dumps({"status": result["status"], "checks": result["checks"]}, ensure_ascii=False, indent=2))
    sys.exit(0 if result["status"] == "PASS" else 1)
