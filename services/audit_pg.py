"""Optional PostgreSQL audit sink for demo V2 releases.

Only synthetic development events are persisted. The evaluation oracle is
never read. When DMRP_REQUIRE_AUDIT=1, failure to write the audit entry
prevents the API from reporting a successful completed release check.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlparse


class AuditUnavailable(RuntimeError):
    pass


SCHEMA = """
CREATE TABLE IF NOT EXISTS demo_release_audit (
    run_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    dataset TEXT NOT NULL CHECK(dataset = 'development'),
    mode TEXT NOT NULL CHECK(mode = 'V2'),
    decision_json JSONB NOT NULL,
    payload_sha256 CHAR(64) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def _dsn() -> str | None:
    path = os.getenv("DMRP_DATABASE_URL_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8").strip()
    return os.getenv("DATABASE_URL")


def audit_record(run_id: str, scenario_id: str, decision: dict) -> dict:
    dsn = _dsn()
    required = os.getenv("DMRP_REQUIRE_AUDIT") == "1"
    if not dsn:
        if required:
            raise AuditUnavailable("required audit database is not configured")
        return {"persisted": False, "reason": "optional_local_demo"}

    parsed = urlparse(dsn)
    if parsed.scheme not in ("postgresql", "postgres") or not parsed.hostname:
        raise AuditUnavailable("audit database configuration invalid")
    if not parsed.username or not parsed.password:
        raise AuditUnavailable("audit database credentials missing")

    serialized = json.dumps(decision, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    try:
        import psycopg
        from psycopg.types.json import Jsonb
        with psycopg.connect(dsn, connect_timeout=5) as connection:
            connection.execute(SCHEMA)
            connection.execute(
                """INSERT INTO demo_release_audit
                   (run_id,scenario_id,dataset,mode,decision_json,payload_sha256)
                   VALUES (%s,%s,'development','V2',%s,%s)""",
                (run_id, scenario_id, Jsonb(decision), digest),
            )
    except Exception:
        # A public HTTP error must not include database URL, credentials or SQL
        # response details, even if the provider propagates those in exceptions.
        raise AuditUnavailable("audit database temporarily unavailable") from None

    return {"persisted": True, "sha256": digest, "run_id": run_id}
