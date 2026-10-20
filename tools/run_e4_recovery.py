"""Reproducible E4 recovery from a killed coordinator and immutable timeout."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from datamesh_release_protocol.distributed import run_distributed
from datamesh_release_protocol.engine import scenario_snapshot_id
from datamesh_release_protocol.journal import EventJournal
from datamesh_release_protocol.loaders import load_baseline_policy
from datamesh_release_protocol.models import ValidationMode
from run_e4 import three_domains


def main() -> None:
    scenario = three_domains()
    policy = load_baseline_policy(Path("policies/v1-ind.yaml"))
    domains = frozenset(item.consumer_domain for item in scenario.obligations)
    with tempfile.TemporaryDirectory(prefix="e4-recovery-") as directory:
        journal_path = Path(directory) / "crash.sqlite"
        env = dict(os.environ, PYTHONPATH="src")
        crashed = subprocess.run([sys.executable, "tools/e4_crash_writer.py", str(journal_path)],
                                 env=env, check=False, capture_output=True, text=True)
        if crashed.returncode != 23:
            raise RuntimeError(f"crash harness failed: {crashed.stderr}")
        with EventJournal(journal_path, f"E4:{scenario.scenario_id}:V2", scenario_snapshot_id(scenario), domains) as journal:
            before = journal.replay()
            stored_before = sorted(before.received)
        resumed = run_distributed(scenario, policy, timeout_s=1.5, journal_path=journal_path)
        independent = subprocess.run([sys.executable, "tools/e4_replay_reader.py", str(journal_path)],
                                     env=env, check=True, capture_output=True, text=True)
        replayed = independent.stdout.strip()
        with EventJournal(journal_path, f"E4:{scenario.scenario_id}:V2", scenario_snapshot_id(scenario), domains) as journal:
            event_count = journal.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]
        missing_path = Path(directory) / "missing.sqlite"
        missing = run_distributed(scenario, policy, timeout_s=1.5,
                                  unavailable=frozenset({"mobility"}), journal_path=missing_path)
        after_timeout = run_distributed(scenario, policy, timeout_s=1.5, journal_path=missing_path)
        cases = {
            "crash_after_durable_write": len(stored_before) == 1 and resumed["decision"] == "ACCEPT",
            "replay_deduplicates": resumed["duplicates"] >= 1 and event_count == 4,
            "independent_finalizer": replayed == "ACCEPT",
            "missing_domain_escalates": missing["decision"] == "NEEDS_REVIEW" and missing["missing_domains"] == ["mobility"],
            "late_replay_cannot_promote": after_timeout["decision"] == "NEEDS_REVIEW",
        }
        result = {"experiment": "E4-R durable recovery development demonstration",
                  "confirmatory": False, "scenario_source": "development/T-03 plus synthetic fintech obligation",
                  "crash_exit_code": crashed.returncode, "stored_before_restart": stored_before,
                  "resumed": resumed, "journal_event_count": event_count,
                  "replayed_by_independent_process": replayed,
                  "missing": missing, "after_timeout": after_timeout,
                  "checks": cases, "passed": sum(cases.values()), "total": len(cases)}
        dest = Path("results/e4-recovery-development.json")
        dest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{result['passed']}/{result['total']} recovery checks passed: {dest}")
    if not all(cases.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
