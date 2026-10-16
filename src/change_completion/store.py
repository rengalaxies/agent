"""Local durable coordination, not a tamper-proof audit service.

A surviving RUNNING claim is deliberately not reclaimed after a restart: an
operator must investigate whether an external effect happened before the crash.
"""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


TERMINAL_STATUSES = frozenset({"READY_FOR_REVIEW", "FAIL", "STOP"})
MAX_PAYLOAD_BYTES = 1024 * 1024


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: dict) -> str:
    if not isinstance(value, dict):
        raise TypeError("payload and result must be dictionaries")
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_PAYLOAD_BYTES:
        raise ValueError("payload exceeds 1 MiB")
    return encoded


class RunStore:
    """One database per trusted local installation, with atomic run claims."""

    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ValueError("state path must be a regular file, not a symlink")
        if not self.path.parent.exists():
            self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if not self.path.exists():
            try:
                descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass  # A concurrent initializer created the private file.
            else:
                os.close(descriptor)
        with self._connection() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    transition_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    finished_at TEXT,
                    result TEXT,
                    UNIQUE(transition_id, fingerprint)
                );
                CREATE TABLE IF NOT EXISTS events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    timestamp TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE TRIGGER IF NOT EXISTS events_no_update
                BEFORE UPDATE ON events BEGIN
                    SELECT RAISE(ABORT, 'events are append-only');
                END;
                CREATE TRIGGER IF NOT EXISTS events_no_delete
                BEFORE DELETE ON events BEGIN
                    SELECT RAISE(ABORT, 'events are append-only');
                END;
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute("PRAGMA synchronous=FULL")
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _event(connection, run_id: str, kind: str, payload: str) -> None:
        connection.execute(
            "INSERT INTO events(run_id,timestamp,kind,payload) VALUES (?,?,?,?)",
            (run_id, _timestamp(), kind, payload),
        )

    def claim(self, transition_id: str, fingerprint: str) -> dict:
        if not isinstance(transition_id, str) or not transition_id.strip():
            raise ValueError("transition_id must be non-empty")
        if not isinstance(fingerprint, str) or not fingerprint.strip():
            raise ValueError("fingerprint must be non-empty")
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT run_id,status FROM runs WHERE transition_id=? AND fingerprint=?",
                (transition_id, fingerprint),
            ).fetchone()
            if row is not None:
                return {"run_id": row["run_id"], "claimed": False, "status": row["status"]}
            run_id = uuid.uuid4().hex
            connection.execute(
                "INSERT INTO runs(run_id,transition_id,fingerprint,status,created_at) VALUES (?,?,?,?,?)",
                (run_id, transition_id, fingerprint, "RUNNING", _timestamp()),
            )
            self._event(connection, run_id, "CLAIMED", _json({"transition_id": transition_id, "fingerprint": fingerprint}))
            return {"run_id": run_id, "claimed": True, "status": "RUNNING"}

    def append(self, run_id: str, kind: str, payload: dict) -> None:
        if not isinstance(kind, str) or not kind.strip():
            raise ValueError("event kind must be non-empty")
        if kind in {"CLAIMED", "FINISHED"}:
            raise ValueError("reserved event kind")
        encoded = _json(payload)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] != "RUNNING":
                raise ValueError("cannot append to a completed run")
            self._event(connection, run_id, kind, encoded)

    def finish(self, run_id: str, status: str, result: dict) -> None:
        if status not in TERMINAL_STATUSES:
            raise ValueError("invalid terminal status")
        encoded = _json(result)
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT status,result FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            if row["status"] != "RUNNING":
                if row["status"] == status and row["result"] == encoded:
                    return
                raise ValueError("completed run cannot be changed")
            connection.execute("UPDATE runs SET status=?,result=?,finished_at=? WHERE run_id=?", (status, encoded, _timestamp(), run_id))
            self._event(connection, run_id, "FINISHED", _json({"status": status}))

    def get(self, run_id: str) -> dict:
        with self._connection() as connection:
            connection.execute("BEGIN")
            row = connection.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if row is None:
                raise KeyError(run_id)
            result = dict(row)
            result["result"] = json.loads(result["result"]) if result["result"] is not None else None
            result["events"] = [
                {**dict(event), "payload": json.loads(event["payload"])}
                for event in connection.execute("SELECT sequence,timestamp,kind,payload FROM events WHERE run_id=? ORDER BY sequence", (run_id,))
            ]
            return result
