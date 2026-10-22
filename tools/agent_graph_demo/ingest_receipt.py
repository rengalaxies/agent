"""Explicit external-report import, never trusted as evidence that runtime is running."""

import argparse
import json
from pathlib import Path

from agent_graph_demo.contracts import DemoError
from agent_graph_demo.locks import locked
from tools.agent_graph_demo.state_access import StateAccess


def ingest(state_root, path):
    r = json.loads(Path(path).read_text())
    required = {
        "session_id",
        "session_revision",
        "proposed_manifest_sha256",
        "running_manifest_sha256",
        "dataset_sha256",
        "status",
        "consumers",
        "version",
        "id",
    }
    if not required <= r.keys() or r["status"] not in ("PASS", "FAIL", "ERROR"):
        raise DemoError("invalid_receipt")
    # Imported arbitrary reports are kept separate from locally observed operator receipts.
    r.update(
        origin="external_import",
        graph_status="EXTERNAL_REPORTED",
        independently_verified=False,
    )
    store = StateAccess(state_root)
    with locked(Path(state_root) / "workload.lock"):
        store.session(r["session_id"])
        return store.artifact(r["session_id"], "external_report", r)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--state-root", type=Path, required=True)
    p.add_argument("--receipt", type=Path, required=True)
    args = p.parse_args()
    print(
        json.dumps(
            {"status": "EXTERNAL_REPORTED", "id": ingest(args.state_root, args.receipt)}
        )
    )
