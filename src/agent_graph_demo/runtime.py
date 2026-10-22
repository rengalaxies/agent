"""Read-only runtime observations, independent of proposed revisions and receipts."""

from datetime import datetime, timezone
import json
from pathlib import Path


def observe(path, max_age=120):
    try:
        r = json.loads(Path(path).read_text())
        age = (
            datetime.now(timezone.utc) - datetime.fromisoformat(r["observed_at"])
        ).total_seconds()
        if r["state"] not in (
            "STOPPED",
            "STARTING",
            "RUNNING",
            "UNKNOWN",
        ) or not isinstance(r["generation"], int):
            raise ValueError()
        if age < -5 or age > max_age:
            return {**r, "state": "UNKNOWN", "reason": "runtime_observation_expired"}
        return r
    except (OSError, ValueError, KeyError, TypeError):
        return dict(
            state="UNKNOWN", generation=None, reason="runtime_registry_unavailable"
        )


def applicable(receipt, session):
    from examples.agent_graph_demo.oracle import DATASET_SHA256

    return (
        receipt["session_id"] == session["id"]
        and receipt["session_revision"] == session["revision"]
        and receipt["proposed_manifest_sha256"] == session["proposed_manifest_sha256"]
        and receipt["running_manifest_sha256"] == session["proposed_manifest_sha256"]
        and receipt["dataset_sha256"] == DATASET_SHA256
    )
