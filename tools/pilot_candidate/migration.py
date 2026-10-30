"""Actual old/new code processes over the same state and loopback GitHub/Jira stands.

No patches to PROFILE: each child imports the checkout selected in PYTHONPATH.
Only synthetic credentials are generated; the private connection file is removed.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def phase(connection, action, output):
    import time
    import uuid
    import agent_graph
    from agent_service.connectors.github import GitHubConnector, StaticToken
    from agent_service.connectors.jira import BasicAuth, JiraConnector
    from agent_service.core_analyzer import CoreAnalyzer
    from agent_service.http import HttpClient
    from agent_service.queue import Limits, ServiceStore
    from agent_service.service import Service
    from agent_service.stands import sign

    config = json.loads(Path(connection).read_text())
    root = Path(config["state"])
    analyzer = CoreAnalyzer(config["policy"], root / "core", ownership_path=config["ownership"],
                            code_version=config["code_sha"])
    connectors = dict(github=GitHubConnector(HttpClient(config["github"], allow_loopback_http=True),
        StaticToken(config["token"]), repositories=["acme/orders"],
        read_repositories={"acme/" + n: "main" for n in config["repositories"]},
        repository_ids={"acme/" + n: n for n in config["repositories"]}, jira_project_keys=["ORD"],
        bot_login=config["bot_login"], webhook_secret=b"author-migration-webhook", clock=time.time),
        jira=JiraConnector(HttpClient(config["jira"], allow_loopback_http=True),
            BasicAuth("bot@example.invalid", "jira-test-token"), project_keys=["ORD"],
            bot_account_id=config["bot_account"], webhook_secret=b"author-migration-jira", clock=time.time))
    store = ServiceStore(root / "service.sqlite", limits=Limits(create_settle_seconds=0))
    service = Service(store=store, connectors=connectors, analyzer=analyzer,
                      installation_id="acme", environment="prod", worker_id=uuid.uuid4().hex)
    meta_path = root / "contexts.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    try:
        assessments = {name: analyzer.graph.freshness(analyzer.graph.context(cid))["status"]
                       for name, cid in meta.items()}
        query = analyzer.query()
        before_bases = [query.basis_freshness(b)["status"] for b in query._bases if b["origin"] == "code"]
        if action == "resume":
            pr = config["fresh_pr"]
            body = json.dumps(dict(action="synchronize", number=7,
                repository=dict(full_name="acme/orders"), pull_request=pr)).encode()
            status, _ = service.receive("github", {"X-GitHub-Event": "pull_request",
                "X-GitHub-Delivery": "author-fresh-during-upgrade",
                "X-Hub-Signature-256": sign(b"author-migration-webhook", body)}, body)
            assert status == 202
        recovered = service.recover()
        reconciliation = service.reconcile()
        if action == "unavailable":
            outcomes = []
        elif action == "partial":
            outcomes = []
            for _ in range(30):
                outcome = service.step()
                outcomes.append(outcome)
                if outcome == "analyze:done":
                    break  # durable ANALYZED + publication intent; next process resumes before send
            assert outcomes[-1] == "analyze:done"
        else:
            outcomes = service.run_until_idle(200)
        context = analyzer.graph.prepare_context()
        meta[agent_graph.PROFILE] = context["id"]
        meta_path.write_text(json.dumps(meta))
        if action == "initial":
            source = next(s for s in context["sources"].values() if s["repository"] == "reporting"
                          and s["path"].endswith(".py"))
            for key in ("modern", "legacy"):
                p = analyzer.graph.propose(context["id"], dict(key=key, kind="hypothesis", statement="Inspect caller " + key,
                    citations=[dict(source_id=source["id"], start_line=1, end_line=1,
                                    quote=source["text"].splitlines()[0])]))
                if key == "legacy":
                    # Explicit authored schema-1 fixture, not a production migration or repair.
                    analyzer.graph.store.db.execute("UPDATE proposal_bases SET config=NULL WHERE id=?", (p["id"],))
        proposals = [{"id": p["id"], "status": p["status"]} for p in analyzer.graph.proposals(context)]
        resources = ["jira:10012", "github:acme/orders#7", "github:acme/orders#8"]
        report = dict(profile=agent_graph.PROFILE, code_sha=config["code_sha"], action=action,
            coverage=context["coverage"], gaps=context["graph"]["gaps"],
            before_contexts=assessments, before_code_bases=before_bases, recovered=recovered,
            reconciliation=reconciliation, steps=outcomes, proposals=proposals,
            resources={rid: dict(generation=store.resource(rid)["generation"], jobs=[
                {k: j.get(k) for k in ("state", "resource_version", "reason")}
                for j in store.jobs(rid)], history_count=len(store.history(rid))) for rid in resources})
        Path(output).write_text(json.dumps(report, indent=2) + "\n")
    finally:
        analyzer.close()


def run(old_checkout, new_checkout, output):
    from agent_service.connectors.jira import adf_text
    from agent_service.smoke import load_stand_module
    from agent_service.stands import GitHubStand, JiraStand
    root = Path(output).resolve()
    root.mkdir(parents=True, exist_ok=True)
    module = load_stand_module()
    stand = module.build_stand(root / "stand")
    github, jira = GitHubStand(), JiraStand()
    try:
        repos = sorted(stand.commits)
        for name in repos:
            github.branches[("acme/" + name, "main")] = stand.head(name)
        for number, branch in ((7, "pr-7"), (8, "readme-only")):
            github.add_pr("acme/orders", number, head=stand.head("orders", branch), base=stand.head(),
                          title="ORD-12 Reduce default page size", head_ref=branch)
        issue = module.JIRA_ISSUE
        jira.add_issue(10012, issue["key"], issue["project"], issue["text_fields"]["summary"],
                       issue["text_fields"]["description"])
        connection = root / "private-connection.json"
        config = dict(state=str(root / "state"), policy=stand.policy(), ownership=str(stand.root / "ownership.json"),
                      github=github.url, jira=jira.url, repositories=repos, token=github.token,
                      bot_login=github.bot_login, bot_account=jira.bot_account_id)
        observations = []
        script = Path(__file__).resolve()

        def snapshot():
            return {**{"pr" + str(n): [{"id": c["id"], "body": c["body"]}
                       for c in github.service_comments("acme/orders", n)] for n in (7, 8)},
                    "jira": [{"id": c["id"], "body": adf_text(c["body"])} for c in jira.comments["10012"]]}

        def execute(checkout, action, label):
            checkout = Path(checkout).resolve()
            config["code_sha"] = subprocess.check_output(["git", "-C", str(checkout), "rev-parse", "HEAD"], text=True).strip()
            connection.write_text(json.dumps(config))
            connection.chmod(0o600)
            destination = root / (label + ".json")
            env = {**os.environ, "PYTHONPATH": str(checkout / "src") + os.pathsep + str(checkout)}
            process = subprocess.run([sys.executable, str(script), "phase", "--connection", str(connection),
                                      "--action", action, "--output", str(destination)], env=env, cwd=checkout,
                                     capture_output=True, text=True, timeout=120)
            if process.returncode:
                (root / (label + ".error.log")).write_text(process.stderr)
                raise RuntimeError("migration_phase_failed:" + label)
            data = json.loads(destination.read_text())
            observations.append(dict(label=label, report=data, comments=snapshot()))

        execute(old_checkout, "initial", "before")
        original_ids = {k: [c["id"] for c in v] for k, v in snapshot().items()}
        assert all(len(ids) == 1 for ids in original_ids.values())
        orders = stand.repo("orders")
        hidden = orders.with_name(orders.name + "-temporarily-unavailable")
        orders.rename(hidden)
        try:
            execute(new_checkout, "unavailable", "upgrade-source-unavailable")
        finally:
            hidden.rename(orders)
        execute(new_checkout, "partial", "upgrade-partial")
        github.set_head("acme/orders", 7, stand.head("orders", "unclassified"))
        pr = github.prs[("acme/orders", 7)]
        config["fresh_pr"] = {k: pr[k] for k in ("number", "title", "head", "base")}
        execute(new_checkout, "resume", "upgrade-resumed")
        execute(old_checkout, "drain", "rollback-code-reconcile-before-publication")
        execute(new_checkout, "drain", "repeat-upgrade")
        final = observations[-1]
        new_profile = final["report"]["profile"]
        for item in observations:
            assert {k: [c["id"] for c in v] for k, v in item["comments"].items()} == original_ids
        assert all(p["status"] == "STALE" for p in final["report"]["proposals"])
        by_label = {item["label"]: item for item in observations}
        for item in (by_label["upgrade-resumed"], final):
            assert all(item["report"]["profile"] in rows[0]["body"] for rows in item["comments"].values())
            assert stand.head("orders", "unclassified")[:12] in item["comments"]["pr7"][0]["body"]
        assert "STALE" in by_label["upgrade-partial"]["report"]["before_contexts"].values()
        old_bases = by_label["upgrade-source-unavailable"]["report"]["before_code_bases"]
        assert old_bases and set(old_bases) == {"STALE"}
        assert by_label["upgrade-source-unavailable"]["report"]["coverage"] == "PARTIAL"
        assert by_label["upgrade-source-unavailable"]["report"]["reconciliation"]["reanalysed"] == 0
        histories = [[x["report"]["resources"][rid]["history_count"] for x in observations]
                     for rid in final["report"]["resources"]]
        assert all(values == sorted(values) for values in histories)
        report = dict(level="CI" if os.environ.get("GITHUB_ACTIONS") == "true" else "LOCAL", status="PASS",
                      profile=new_profile, model="OFF", same_comment_ids=original_ids, phases=observations,
                      fresh_head=stand.head("orders", "unclassified"),
                      warning="Old-code rollback may assess newer pinned contexts CURRENT before reconciliation. Hold publication and rebuild; no old release safety is inferred. DB/API are not atomic; comments update over durable steps without a maximum outage window.")
        (root / "MIGRATION.json").write_text(json.dumps(report, indent=2) + "\n")
        return report
    finally:
        (root / "private-connection.json").unlink(missing_ok=True)
        github.close()
        jira.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    parent = sub.add_parser("run")
    parent.add_argument("--old-checkout", required=True, type=Path)
    parent.add_argument("--new-checkout", required=True, type=Path)
    parent.add_argument("--output", required=True, type=Path)
    child = sub.add_parser("phase")
    child.add_argument("--connection", required=True, type=Path)
    child.add_argument("--action", required=True)
    child.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "phase":
        phase(args.connection, args.action, args.output)
    else:
        print(json.dumps({k: v for k, v in run(args.old_checkout, args.new_checkout, args.output).items()
                          if k not in ("phases",)}))
