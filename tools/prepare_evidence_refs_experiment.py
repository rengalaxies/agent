"""Offline manifest and ledger rehearsal. NO HTTP client, key lookup or live entrypoint."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3

from agent_graph.contracts import GraphError, canonical, digest, model_action_schema
from agent_graph.evidence_refs import ReferenceReply
from agent_graph.inference import REFERENCE_SYSTEM

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/graph/fixtures/pr31"
PLAN = ROOT / "experiments/evidence_refs_v2/plan.json"
CORPORA = {
    "reporting-http": "partial-series/1-reporting-http/corpus",
    "export-E": "final/1-export-E/corpus",
    "status-decoy": "final/1-status-decoy/corpus",
}


def manifest():
    plan = json.loads(PLAN.read_text())
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    for item in provenance["files"]:
        if hashlib.sha256((FIXTURES / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
            raise GraphError("fixture_digest_mismatch")
    files = {}
    for case, prefix in CORPORA.items():
        files[case] = {str(p.relative_to(FIXTURES / prefix)): hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in sorted((FIXTURES / prefix).rglob("*.py"))}
    history = []
    for p in sorted((FIXTURES / "final").glob("*/report.json")):
        report = json.loads(p.read_text())
        for r in report["requests"]:
            history.append(dict(id=r["global_request"], case=report["case"], model=report["model"],
                                http_status=r.get("http_status"), usage=r.get("usage"),
                                phase="CLOSED_PR31_HISTORICAL"))
    history.sort(key=lambda r: r["id"])
    if [r["id"] for r in history] != list(range(1, 22)):
        raise GraphError("historical_ledger_mismatch")
    core_files = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                  for p in sorted((ROOT / "src/agent_graph").glob("*.py"))}
    runner_files = [ROOT / "tools" / name for name in ("run_evidence_refs_experiment.py", "evidence_refs_ledger.py")]
    packet = dict(plan=plan, runner_files_sha256={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in runner_files}, corpus_sha256=files, core_files_sha256=core_files,
                  harness_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  system=REFERENCE_SYSTEM, schema=model_action_schema(ReferenceReply),
                  oracle_sha256=hashlib.sha256((ROOT / "experiments/evidence_refs_v2/oracle.json").read_bytes()).hexdigest(),
                  historical_requests=history, live_enabled=False,
                  execution="NO_MODEL_CALLS; runner prepared; no live authorization; initialize requires separately specified NEW limits")
    return {**packet, "manifest_digest": digest(packet)}


class RehearsalLedger:
    """Shared durable OFFLINE admission rehearsal, not an authorized live runner.

    One series deadline and persistent per-case deadlines survive object/process
    restart. All rehearsed attempts reserve irreversibly before a hypothetical
    send; failed/unknown attempts never refund. No transport is implemented here.
    """
    def __init__(self, path, packet, *, now):
        self.db = sqlite3.connect(path, isolation_level=None)
        self.packet = packet
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS stops(reason TEXT);
            CREATE TABLE IF NOT EXISTS series(digest TEXT, started REAL, deadline REAL, last_seen REAL);
            CREATE TABLE IF NOT EXISTS cases(model TEXT, name TEXT, deadline REAL, PRIMARY KEY(model,name));
            CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, model TEXT, name TEXT,
                phase TEXT, http_status INTEGER, usage TEXT);
        """)
        with self._transaction():
            row = self.db.execute("SELECT digest FROM series").fetchone()
            if row:
                if row[0] != packet["manifest_digest"]:
                    raise GraphError("experiment_manifest_changed")
            else:
                self.db.execute("INSERT INTO series VALUES(?,?,?,?)", (
                    packet["manifest_digest"], now, now + packet["plan"]["deadlines"]["series_seconds"], now))
                for r in packet["historical_requests"]:
                    self.db.execute("INSERT INTO attempts VALUES(?,?,?,?,?,?)", (
                        r["id"], r["model"], r["case"], r["phase"], r["http_status"], canonical(r["usage"])))

    @contextmanager
    def _transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def simulate_attempt(self, model, case, *, now):
        stopped = self.db.execute("SELECT reason FROM stops LIMIT 1").fetchone()
        if stopped:
            raise GraphError(stopped[0])
        try:
            return self._simulate_attempt(model, case, now=now)
        except GraphError as exc:
            if exc.code in ("case_deadline", "series_deadline", "clock_moved_backwards"):
                # Autocommit outside the rolled-back admission transaction.
                self.db.execute("INSERT INTO stops VALUES(?)", (exc.code,))
            raise

    def _simulate_attempt(self, model, case, *, now):
        plan = self.packet["plan"]
        if model not in plan["models"] or case not in plan["case_order"]:
            raise GraphError("unregistered_case")
        with self._transaction():
            _, _, series_deadline, last_seen = self.db.execute("SELECT * FROM series").fetchone()
            if now < last_seen:
                raise GraphError("clock_moved_backwards")
            if now >= series_deadline:
                raise GraphError("series_deadline")
            self.db.execute("UPDATE series SET last_seen=?", (now,))
            row = self.db.execute("SELECT deadline FROM cases WHERE model=? AND name=?", (model, case)).fetchone()
            case_deadline = row[0] if row else now + plan["deadlines"]["case_seconds"]
            if now >= case_deadline:
                raise GraphError("case_deadline")
            if not row:
                self.db.execute("INSERT INTO cases VALUES(?,?,?)", (model, case, case_deadline))
            budget = plan["budget_proposal_not_authorization"]
            count = self.db.execute("SELECT count(*) FROM attempts").fetchone()[0]
            if count >= budget["proposed_lifetime_request_cap"]:
                raise GraphError("series_request_limit")
            used = self.db.execute("SELECT count(*) FROM attempts WHERE model=? AND name=? AND phase='SIMULATED'", (model, case)).fetchone()[0]
            if used >= budget["max_new_requests_per_model_case"]:
                raise GraphError("case_request_limit")
            cur = self.db.execute("INSERT INTO attempts(model,name,phase) VALUES(?,?,'SIMULATED')", (model, case))
            return dict(id=cur.lastrowid, status="SIMULATED_NO_HTTP",
                        deadline=min(series_deadline, case_deadline),
                        timeout_seconds=min(plan["parameters"]["request_timeout_seconds"], series_deadline-now, case_deadline-now))

    def close(self):
        self.db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    packet = manifest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(packet, ensure_ascii=False, indent=2) + "\n")
    print("PREPARED_OFFLINE_ONLY " + packet["manifest_digest"])


if __name__ == "__main__":
    main()
