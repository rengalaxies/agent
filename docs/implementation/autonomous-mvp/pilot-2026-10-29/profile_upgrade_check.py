"""Upgrade check: state written by one code version, reopened by another (profile 4 -> 5).

Phase ``before`` (code A): the start-up reconcile finds Jira APILOT-1, PR #1 (page
limit) and PR #2 (docs only); the worker publishes through the dry-run sink, one
comment file per resource. Phase ``after`` (code B): a new process opens the same
state, graph store and comment files, runs the start-up reconcile and drains.

Records profile per published comment, comment ids, generations and history size.
LOCAL: loopback GitHub/Jira stands, dry_run publication, MODEL OFF. Only modules that
exist on both code versions are imported.

Usage: python profile_upgrade_check.py --code <repo root> --dir <work dir> --phase before|after
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import uuid

ORDERS, REPORTING = "rengalaxies/agent-pilot-orders", "rengalaxies/agent-pilot-reporting"


def run(code: Path, work: Path, phase: str) -> dict:
    sys.path[:0] = [str(code), str(code / "src")]
    from agent_graph import PROFILE
    from agent_service.connectors.github import GitHubConnector, StaticToken
    from agent_service.connectors.jira import BasicAuth, JiraConnector
    from agent_service.core_analyzer import CoreAnalyzer
    from agent_service.http import HttpClient
    from agent_service.publisher import DirectorySink
    from agent_service.queue import Limits, ServiceStore
    from agent_service.service import Service
    from agent_service.stands import GitHubStand, JiraStand
    from examples.pilot_orders_reporting.prepare import prepare

    if phase == "before":
        prepared = prepare(work / "repositories")
        (work / "ownership.json").write_text(json.dumps({"source": "installation_mapping", "version": "pilot-1",
            "services": {"orders": "team-orders", "reporting": "team-reporting"}}))
    else:
        prepared = json.loads((work / "repositories" / "prepared.json").read_text())
    commits = {name: item["commits"] for name, item in prepared["repositories"].items()}
    requirement = code / "examples/pilot_orders_reporting/reporting/export-requirement.md"
    policy = dict(installation_id="agent-pilot", environment="test", subject="upgrade-check",
                  capabilities=["read_context", "maintain", "propose", "report_check"],
                  repositories=[dict(id=n, service=n, root=str(work / "repositories" / n), snapshot="git",
                                     revision=c["main"]) for n, c in commits.items()],
                  addresses=[dict(service="orders", base_url="https://orders.pilot.invalid")],
                  requirements=[dict(id="R-pilot-export-all", repository="reporting", path="export-requirement.md",
                                     sha256=hashlib.sha256(requirement.read_bytes()).hexdigest(),
                                     issuer="M2-A author test condition", consumer="reporting", service="orders",
                                     path_template="/orders", predicate="complete_collection")])
    github, jira = GitHubStand(), JiraStand()
    try:
        github.branches[(ORDERS, "main")] = commits["orders"]["main"]
        github.branches[(REPORTING, "main")] = commits["reporting"]["main"]
        github.add_pr(ORDERS, 1, head=commits["orders"]["pilot-page-limit"], base=commits["orders"]["main"],
                      title="APILOT-1 Reduce the default page size", head_ref="pilot-page-limit")
        github.add_pr(ORDERS, 2, head=commits["orders"]["pilot-docs-only"], base=commits["orders"]["main"],
                      title="Document GET /orders pagination", head_ref="pilot-docs-only")
        jira.add_issue(10001, "APILOT-1", "APILOT", "Orders: уменьшить размер страницы GET /orders до 20",
                       "GET /orders: default page_size 100 -> 20.")
        commit = subprocess.run(["git", "-C", str(code), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        analyzer = CoreAnalyzer(policy, work / "state" / "core", ownership_path=str(work / "ownership.json"),
                                code_version=commit)
        store = ServiceStore(work / "state" / "service.sqlite", clock=time.time, limits=Limits(create_settle_seconds=0))
        connectors = {
            "github": GitHubConnector(HttpClient(github.url, allow_loopback_http=True), StaticToken(github.token),
                                      repositories=[ORDERS], read_repositories={ORDERS: "main", REPORTING: "main"},
                                      repository_ids={ORDERS: "orders", REPORTING: "reporting"},
                                      jira_project_keys=["APILOT"], bot_login=github.bot_login,
                                      webhook_secret=b"unused", clock=time.time),
            "jira": JiraConnector(HttpClient(jira.url, allow_loopback_http=True),
                                  BasicAuth("bot@example.invalid", "jira-test-token"), project_keys=["APILOT"],
                                  bot_account_id=jira.bot_account_id, webhook_secret=b"unused", clock=time.time),
        }
        backends = {name: DirectorySink(work / "comments" / name) for name in connectors}
        service = Service(store=store, connectors=connectors, analyzer=analyzer, installation_id="agent-pilot",
                          environment="test", backends=backends, worker_id=uuid.uuid4().hex)
        if phase == "before":
            service.reconcile_graph()  # what the installer's initial graph step does
        reconciled = service.reconcile()
        drained = service.run_until_idle(200)
        comments = {}
        for name in backends:
            for path in sorted((work / "comments" / name).glob("*.json")):
                item = json.loads(path.read_text(encoding="utf-8"))
                text = json.dumps(item["doc"], ensure_ascii=False)
                comments[item["resource_id"]] = {
                    "id": item["id"], "profile": (re.findall(r"profile: ([\w.-]+)", text) or [None])[0],
                    "generation": int(re.search(r"generation=(\d+)", item["marker"]).group(1)),
                    "title": item["doc"]["title"]}
        resources = {r["resource_id"]: r["generation"] for r in store.resources()}
        report = {"phase": phase, "level": "LOCAL", "model": "OFF", "code": commit, "profile": PROFILE,
                  "at": datetime.now(timezone.utc).isoformat(),
                  "reconcile": {k: reconciled.get(k) for k in ("enqueued", "reanalysed") if k in reconciled},
                  "worker_steps": drained, "generations": resources, "comments": comments,
                  "history_entries": len(store.history()),
                  "result_intents": sum(1 for rid in resources for _ in store.history(rid)
                                        if _["entry"] == "intent_delivered")}
        analyzer.close()
    finally:
        github.close()
        jira.close()
    (work / f"{phase}.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--code", required=True, type=Path)
    parser.add_argument("--dir", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=["before", "after"])
    args = parser.parse_args()
    print(json.dumps(run(args.code.resolve(), args.dir.resolve(), args.phase), ensure_ascii=False, indent=2))
