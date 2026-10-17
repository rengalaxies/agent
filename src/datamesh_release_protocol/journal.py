"""Durable E4 coordinator inbox with transactional, immutable finalization."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .distributed import EventCollector
from .models import Decision


class EventJournal:
    def __init__(self, path: Path, proposal_id: str, snapshot_id: str,
                 expected_domains: frozenset[str]) -> None:
        if not expected_domains:
            raise ValueError("expected_domains must be nonempty")
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS events (seq INTEGER PRIMARY KEY AUTOINCREMENT, payload TEXT NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS final (id INTEGER PRIMARY KEY CHECK(id=1), decision TEXT NOT NULL)")
        self.identity = {"proposal_id": proposal_id, "snapshot_id": snapshot_id,
                         "expected_domains": sorted(expected_domains)}
        canonical = json.dumps(self.identity, sort_keys=True, ensure_ascii=False)
        with self.db:
            self.db.execute("INSERT OR IGNORE INTO meta(id,value) VALUES (1,?)", (canonical,))
            actual = self.db.execute("SELECT value FROM meta WHERE id=1").fetchone()[0]
        if actual != canonical:
            self.close()
            raise ValueError("journal identity mismatch")

    def replay(self) -> EventCollector:
        collector = EventCollector(self.identity["proposal_id"], self.identity["snapshot_id"],
                                   frozenset(self.identity["expected_domains"]))
        for (payload,) in self.db.execute("SELECT payload FROM events ORDER BY seq"):
            collector.ingest(json.loads(payload))
        return collector

    def append(self, event: dict) -> bool:
        """Persist before acknowledgement; refuse new events after finalization."""
        serialized = json.dumps(event, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        self.db.execute("BEGIN IMMEDIATE")
        try:
            if self.db.execute("SELECT 1 FROM final WHERE id=1").fetchone():
                self.db.execute("COMMIT")
                return False
            self.db.execute("INSERT INTO events(payload) VALUES (?)", (serialized,))
            self.db.execute("COMMIT")
            return True
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def finalize(self) -> Decision:
        """First terminal decision wins across independent coordinator processes."""
        self.db.execute("BEGIN IMMEDIATE")
        try:
            prior = self.db.execute("SELECT decision FROM final WHERE id=1").fetchone()
            if prior:
                result = Decision(prior[0])
            else:
                result = self.replay().decision
                self.db.execute("INSERT INTO final(id,decision) VALUES (1,?)", (result.value,))
            self.db.execute("COMMIT")
            return result
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def close(self) -> None:
        self.db.close()

    def __enter__(self) -> "EventJournal":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
