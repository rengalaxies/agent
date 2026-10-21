"""Local immutable snapshots, optimistic publication and durable budget reservations."""
from __future__ import annotations

from contextlib import contextmanager
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid

from .contracts import GraphError, canonical, digest, load_json


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if directory.is_symlink() or directory.stat().st_mode & 0o077:
            raise GraphError("private_state_directory_required")
        path = directory / "graph.sqlite3"
        if path.is_symlink():
            raise GraphError("invalid_state_path")
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        os.chmod(path, 0o600)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS heads(view TEXT PRIMARY KEY, generation INTEGER, id TEXT);
            CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, view TEXT, kind TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, view TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY, installation TEXT,
                run TEXT, tokens INTEGER, micro INTEGER, currency TEXT, until REAL, active INTEGER);
        """)

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def head(self, view):
        row = self.db.execute("SELECT generation,id FROM heads WHERE view=?", (view,)).fetchone()
        return row if row else (0, None)

    def save(self, view, kind, artifact, expected_generation=None):
        artifact = {**artifact, "id": digest([view, kind, artifact])}
        with self.transaction():
            if expected_generation is not None and self.head(view)[0] != expected_generation:
                raise GraphError("concurrent_update")
            self.db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?)",
                            (artifact["id"], view, kind, canonical(artifact)))
            if expected_generation is not None:
                self.db.execute("INSERT OR REPLACE INTO heads VALUES(?,?,?)",
                                (view, expected_generation + 1, artifact["id"]))
        return artifact

    def get(self, view, id, kind="context"):
        row = self.db.execute("SELECT data FROM artifacts WHERE id=? AND view=? AND kind=?", (id, view, kind)).fetchone()
        if not row:
            raise GraphError("not_found")
        return load_json(row[0])

    def proposals(self, view):
        return [load_json(r[0]) for r in self.db.execute("SELECT data FROM proposals WHERE view=? ORDER BY id", (view,))]

    def propose(self, view, proposal, expected_head):
        id = digest([view, proposal])
        data = {**proposal, "id": id}
        with self.transaction():
            if self.head(view)[1] != expected_head:
                raise GraphError("concurrent_update")
            self.db.execute("INSERT OR IGNORE INTO proposals VALUES(?,?,?)", (id, view, canonical(data)))
        return data

    def reserve(self, installation, run, tokens, config):
        micro = math.ceil(tokens * config.micro_per_million_tokens / 1_000_000)
        id = uuid.uuid4().hex
        with self.transaction():
            rows = self.db.execute("SELECT run,tokens,micro,currency,until,active FROM reservations WHERE installation=?",
                                   (installation,)).fetchall()
            if any(r[3] != config.currency for r in rows):
                raise GraphError("budget_currency_changed")
            if any(r[5] and r[4] > time.time() for r in rows):
                raise GraphError("model_busy")
            if (sum(r[1] for r in rows) + tokens > config.installation_token_cap
                    or sum(r[1] for r in rows if r[0] == run) + tokens > config.run_token_cap
                    or config.micro_per_million_tokens and (
                        sum(r[2] for r in rows) + micro > config.installation_micro_cap
                        or sum(r[2] for r in rows if r[0] == run) + micro > config.run_micro_cap)):
                raise GraphError("budget_exhausted")
            # No refund after timeout/crash or invalid output. A new context/run
            # cannot reset the installation allowance. One active request total.
            self.db.execute("INSERT INTO reservations VALUES(?,?,?,?,?,?,?,1)",
                            (id, installation, run, tokens, micro, config.currency,
                             time.time() + config.timeout_seconds + 5))
        return id

    def finish_reservation(self, id):
        self.db.execute("UPDATE reservations SET active=0 WHERE id=?", (id,))

    def budget_totals(self, installation):
        row = self.db.execute("SELECT count(*),coalesce(sum(tokens),0),coalesce(sum(micro),0) FROM reservations WHERE installation=?",
                              (installation,)).fetchone()
        return dict(attempts=row[0], reserved_token_units=row[1], reserved_micro=row[2])
