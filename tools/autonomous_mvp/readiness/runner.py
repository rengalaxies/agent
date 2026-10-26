"""Run the service end to end on each change of the current readiness revision and record a ledger.

Per change, on a fresh stand and a fresh service installation (no state shared
between changes, so changes stay independent):

1. initial graph reconciliation, as the installer does;
2. Jira ``issue_created`` webhook, worker drained; the same delivery is sent again;
3. PR ``opened`` webhook at the change head, worker drained; the same delivery is sent again;
4. the PR is merged: the provider's default branch moves to the head and the
   periodic graph reconciliation runs once.

The ledger records what the stands and the service's own queue show: result
documents, comment bodies and counters, intents, latency from delivery to the
last accepted comment write, graph freshness after the merge, model use. It
never reads the oracle. Configuration ``service-no-model``: ``CoreAnalyzer``
with ``model=None``, the deterministic core path.

Held-out rule: the held-out split runs only when the committed manifest is
current, and only once per configuration: an existing held-out ledger is never
overwritten.

Usage:
  python -m tools.autonomous_mvp.readiness.runner --split development
  python -m tools.autonomous_mvp.readiness.runner --split heldout     # once, after the freeze commit
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

from agent_service.connectors.base import parse_marker
from tools.autonomous_mvp.readiness import program as program_mod, world

CONFIGURATION = "service-no-model"
FINAL_INTENT_STATES = ("DELIVERED", "SUPERSEDED", "FAILED")


def load_changes(split, base=None):
    base = Path(base or program_mod.PROGRAM_DIR)
    changes = []
    for path in sorted((base / "changes" / split).glob("*.json")):
        change = json.loads(path.read_text(encoding="utf-8"))
        if change["split"] != split or change["change_id"] != path.stem:
            raise ValueError("change_file_mismatch")
        changes.append(change)
    return changes


def compact_result(result):
    """The part of an AnalysisResult the scorer reads; the comment text is kept beside it."""
    if not isinstance(result, dict):
        return None
    return dict(
        status=result["status"], reason_code=result["reason_code"], graph_version=result.get("graph_version"),
        affected=[dict(service=a["service"]["service"], owner_status=a["owner"]["status"],
                       owner_teams=[t["team"] for t in a["owner"].get("teams") or []],
                       relationship_refs=a["relationship_refs"]) for a in result["affected"]],
        relationships=[dict(id=r["id"], source=r["source"]["service"], target=dict(
            service=r["target"].get("service"), method=r["target"].get("method"), route=r["target"].get("route")),
            origins=r["origins"], freshness=r["freshness"]["status"]) for r in result["relationships"]],
        findings=[dict(code=f["code"], consumer=f["consumer"]["service"], usage=f["usage"],
                       callsite=dict(repository=f["callsite"]["repository"], path=f["callsite"]["path"]))
                  for f in result.get("findings", [])],
        deltas=[dict(code=d["code"], route=d["operation"]["route"], before=d["before"], after=d["after"])
                for d in result.get("deltas", [])],
        unknowns=[[u["code"], u["subject"]] for u in result["unknowns"]],
        source_freshness=[[s["source_kind"], s["source_id"], s["freshness"]["status"]]
                          for s in result["source_freshness"]],
        costs=result.get("costs"))


def publication(bench, resource, comments, writes_before, writes_after):
    """Lost, duplicate and stale from the stand's comments and the service's own queue."""
    store = bench.service.store
    intents = store.intents(resource)
    res = store.resource(resource) or {}
    jobs = store.jobs(resource)
    latest = max((i for i in intents if i["kind"] == "result"), key=lambda i: i["generation"], default=None)
    shown = parse_marker(comments[-1]["body"])[1] if comments else None
    pending = [i["state"] for i in intents if i["state"] not in FINAL_INTENT_STATES]
    return dict(
        comments=len(comments), creates=sum(1 for _, m, _ in writes_after if m == "POST"),
        updates=sum(1 for _, m, _ in writes_after if m in ("PATCH", "PUT")),
        writes_after_redelivery=len(writes_after) - len(writes_before),
        intents=[dict(kind=i["kind"], generation=i["generation"], state=i["state"], reason=i["reason"])
                 for i in intents],
        jobs=[dict(generation=j["generation"], state=j["state"], reason=j["reason"]) for j in jobs],
        resource_generation=res.get("generation"), published_generation=res.get("published_generation"),
        lost=not comments or latest is None or latest["state"] != "DELIVERED" or bool(pending),
        duplicate=len(comments) > 1 or sum(1 for _, m, _ in writes_after if m == "POST") > 1,
        stale=bool(comments) and latest is not None and (
            shown != latest["body_digest"] or res.get("published_generation") != res.get("generation")))


def run_stage(bench, stage, deliver):
    """Deliver, drain, redeliver the same delivery id, drain; observe."""
    stand = bench.jira if stage == "jira" else bench.github
    resource = bench.jira_resource() if stage == "jira" else bench.pr_resource()
    delivery = f"readiness-{stage}-{bench.change['change_id']}"
    started_writes = len(stand.writes)
    t0 = time.time()
    status, _ = deliver(delivery)
    clock = time.monotonic()
    bench.drain()
    processing = time.monotonic() - clock
    writes = stand.writes[started_writes:]
    latency = round(writes[-1][0] - t0, 3) if writes else None
    redelivery_status, redelivery = deliver(delivery)
    bench.drain()
    writes_after = stand.writes[started_writes:]
    comments = bench.jira_comments() if stage == "jira" else [dict(id=c["id"], body=c["body"])
                                                                for c in bench.pr_comments()]
    jobs = [j for j in bench.service.store.jobs(resource) if j["result"]]
    result = jobs[-1]["result"] if jobs else None
    return dict(
        delivery_status=status, redelivery_status=redelivery_status,
        redelivery_duplicate=bool(redelivery.get("duplicate")),
        latency_seconds=latency, processing_seconds=round(processing, 3),
        result=compact_result(result), comment_texts=[c["body"] for c in comments],
        publication=publication(bench, resource, comments, writes, writes_after))


def merge_and_reconcile(bench):
    """Move the provider's default branch to the PR head; one periodic reconciliation."""
    head = bench.commits[bench.provider][bench.change["pr"]["head_branch"]]
    bench.github.branches[(bench.full[bench.provider], "main")] = head
    clock = time.monotonic()
    results = bench.service.reconcile_graph() or []
    seconds = time.monotonic() - clock
    query = bench.analyzer.query()
    sources = {s["source_id"]: s for s in query.source_freshness() if s["source_kind"] == "git"}
    provider = sources.get(bench.provider, {})
    operations = sorted(h["entity"]["route"] for h in query.find(bench.provider, kind="operation", limit=100)
                        if h["entity"]["service"] == bench.provider
                        and any(v["status"] == "ACTIVE" and v["kind"] == "declares"
                                for v in query.neighbors(h["id"], direction="in")))
    return dict(head=head, seconds=round(seconds, 3), reconcile=results,
                provider_source_version=provider.get("source_version"),
                provider_freshness=provider.get("freshness", {}).get("status"),
                active_operations=operations, graph_version=query.version)


def run_change(change, work: Path) -> dict:
    from tools.autonomous_mvp.readiness.bench import ChangeBench

    record = dict(change_id=change["change_id"], split=change["split"], family=change["family"],
                  configuration=CONFIGURATION)
    started = time.monotonic()
    bench = None
    try:
        bench = ChangeBench(change, work)
        record.update(commits=bench.commits, setup_seconds=round(bench.setup_seconds, 3),
                      initial_graph=bench.initial_graph)
        record["jira"] = run_stage(bench, "jira", lambda d: bench.deliver_jira(d))
        bench.open_pr()
        record["pr"] = run_stage(bench, "pr", lambda d: bench.deliver_pr("opened", d))
        record["merge"] = merge_and_reconcile(bench)
        record["notices"] = sorted({n["kind"] for n in bench.service.store.notices()})
        calls = [(record[s]["result"] or {}).get("costs") or {} for s in ("jira", "pr")]
        record["costs"] = dict(model_calls=sum(c.get("model_calls") or 0 for c in calls),
                               prompt_tokens=sum(c.get("prompt_tokens") or 0 for c in calls),
                               completion_tokens=sum(c.get("completion_tokens") or 0 for c in calls))
        record["error"] = None
    except Exception as exc:  # a crash is a recorded failure of this change, never a skipped one
        record["error"] = f"{type(exc).__name__}: {exc}"
        record["traceback"] = traceback.format_exc()[-4000:]
    finally:
        if bench is not None:
            bench.close()
    record["wall_seconds"] = round(time.monotonic() - started, 3)
    # No step of this run waits for a person; minutes a person spends on the comments are not measured here.
    record["human"] = dict(interventions=0, active_minutes=None, status="NOT_RECORDED")
    return record


def source_sha():
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], cwd=program_mod.ROOT, capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def ledger_path(split, configuration=CONFIGURATION, base=None):
    return Path(base or program_mod.PROGRAM_DIR) / "results" / f"{split}-{configuration}.json"


def guard(split, path, *, manifest_current: bool):
    """Held-out: frozen manifest, and once per configuration."""
    if split != "heldout":
        return
    if not manifest_current:
        raise SystemExit("REFUSED manifest_stale: freeze (program.py) and commit before the held-out run")
    if path.exists():
        raise SystemExit(f"REFUSED heldout_already_run: {path.name} exists; a held-out run is never repeated")


def run_split(split, *, out: Path | None = None, only=None, keep=None, base=None):
    current, digest = program_mod.status(base)
    path = Path(out) if out else ledger_path(split, base=base)
    guard(split, path, manifest_current=current)
    changes = [c for c in load_changes(split, base) if not only or c["change_id"] in only]
    ledger = dict(schema="readiness-ledger-1", program=world.CURRENT, split=split, configuration=CONFIGURATION,
                  manifest_digest=digest, manifest_current=current, source_sha=source_sha(),
                  python=sys.version.split()[0], platform=platform.platform(),
                  started_at=datetime.now(timezone.utc).isoformat(), records=[])
    path.parent.mkdir(parents=True, exist_ok=True)
    root = Path(keep) if keep else Path(tempfile.mkdtemp(prefix="readiness-6-"))
    try:
        for change in changes:
            record = run_change(change, root / change["change_id"])
            ledger["records"].append(record)
            print(f"{change['change_id']} {change['family']} jira={_status(record, 'jira')} "
                  f"pr={_status(record, 'pr')} wall={record['wall_seconds']}s"
                  + (f" ERROR {record['error']}" if record["error"] else ""), flush=True)
            ledger["finished_at"] = datetime.now(timezone.utc).isoformat()
            path.write_bytes((json.dumps(ledger, ensure_ascii=False, indent=1, sort_keys=True) + "\n").encode())
    finally:
        if not keep:
            shutil.rmtree(root, ignore_errors=True)
    return ledger, path


def _status(record, stage):
    result = (record.get(stage) or {}).get("result") or {}
    return result.get("status", "NONE")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--split", choices=world.SPLITS, required=True)
    parser.add_argument("--only", nargs="*", help="development only: a subset of change ids")
    parser.add_argument("--out", help="ledger path (default: the program's results directory)")
    parser.add_argument("--keep", help="keep the stands in this directory")
    args = parser.parse_args()
    if args.split == "heldout" and (args.only or args.out):
        raise SystemExit("REFUSED: the held-out run covers every change and writes the program ledger")
    ledger, path = run_split(args.split, out=args.out, only=args.only, keep=args.keep)
    print(f"LEDGER {path} records={len(ledger['records'])} manifest={ledger['manifest_digest']} "
          f"current={ledger['manifest_current']}")


if __name__ == "__main__":
    main()
