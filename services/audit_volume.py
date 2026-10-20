"""Audit for the public development demo on a mounted persistent object volume.

One closed and fsynced JSON file per run. No shared database file, append log,
or claim of cross-object transactions. PostgreSQL remains the default backend.
"""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from services.audit_pg import AuditUnavailable

def _root() -> Path:
    root = Path(os.environ.get("DMRP_AUDIT_DIRECTORY", "/audit-data"))
    if not root.is_absolute() or not root.is_dir():
        raise AuditUnavailable("Persistent audit volume unavailable")
    if os.environ.get("DMRP_AUDIT_REQUIRE_MOUNT", "1") == "1":
        mounts = Path("/proc/self/mountinfo").read_text().splitlines()
        if not any(line.split()[4] == str(root) for line in mounts):
            raise AuditUnavailable("Persistent audit volume is not mounted")
    marker = json.loads((root / ".dmrp-audit-volume-v1.json").read_text())
    if marker != {"project_id": "20853297-65b7-42a8-af40-25c8d2df4e11", "dataset": "development", "format": 1}:
        raise AuditUnavailable("Persistent audit volume identity invalid")
    return root

def _path(run_id: str) -> Path:
    if not re.fullmatch(r"demo-[0-9a-f]{32}", run_id):
        raise AuditUnavailable("Invalid audit identifier")
    return _root() / (run_id + ".json")

def _serialized(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()

def audit_read(run_id: str) -> dict:
    try:
        record = json.loads(_path(run_id).read_bytes())
        if record["run_id"] != run_id or record["dataset"] != "development" or record["mode"] != "V2":
            raise ValueError("Invalid record")
        digest = hashlib.sha256(_serialized(record["decision"])).hexdigest()
        if record["payload_sha256"] != digest:
            raise ValueError("Corrupt record")
        return record
    except FileNotFoundError:
        raise
    except Exception:
        raise AuditUnavailable("Audit record unavailable or invalid") from None

def audit_record(run_id: str, scenario_id: str, decision: dict) -> dict:
    try:
        digest = hashlib.sha256(_serialized(decision)).hexdigest()
        record = {"format": 1, "run_id": run_id, "scenario_id": scenario_id,
                  "dataset": "development", "mode": "V2", "decision": decision,
                  "payload_sha256": digest, "created_at": datetime.now(timezone.utc).isoformat()}
        path = _path(run_id)
        try:
            with path.open("xb") as stream:
                stream.write(_serialized(record))
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            pass
        saved = audit_read(run_id)
        if saved["scenario_id"] != scenario_id or saved["payload_sha256"] != digest:
            raise ValueError("Conflicting audit identifier")
    except Exception:
        raise AuditUnavailable("Persistent audit write failed") from None
    return {"persisted": True, "backend": "object_storage_volume",
            "sha256": digest, "run_id": run_id}

def audit_ready() -> bool:
    try:
        return _root().is_dir() and os.access(_root(), os.W_OK)
    except Exception:
        return False
