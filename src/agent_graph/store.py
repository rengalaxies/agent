"""Local immutable snapshots, optimistic publication and durable budget reservations.

Schema 2 adds the persistent graph tables (used by graph_store) and gives each
proposal its own cited bases, scope and visibility (side table proposal_bases),
so knowledge no longer hangs on one corpus-wide basis or one view. Version 1 data
is migrated in place after a file backup; no table, column or row is dropped or
altered, so a rolled-back v1 binary can still read and append proposals.
"""
from __future__ import annotations

from contextlib import contextmanager
import math
import os
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from .contracts import GraphError, canonical, digest, load_json
from .portable import lock_nonblocking, open_lock_file, private_directory


STORE_SCHEMA = 2


def scope_id(installation_id, environment):
    return digest([installation_id, environment])


def proposal_identity(view, record):
    # Keep the original publication/citations immutable; subsequent contexts
    # with the same basis reuse its identity, including records from v1 stores.
    return digest([view, {k: v for k, v in record.items() if k not in ("context_id", "id")}])


GRAPH_DDL = (
    "CREATE TABLE IF NOT EXISTS graph_entities(id TEXT PRIMARY KEY, scope TEXT, kind TEXT, data TEXT)",
    "CREATE TABLE IF NOT EXISTS graph_relationships(id TEXT PRIMARY KEY, scope TEXT, kind TEXT, source TEXT,"
    " target TEXT)",
    "CREATE TABLE IF NOT EXISTS graph_bases(id TEXT PRIMARY KEY, scope TEXT, relationship TEXT, origin TEXT,"
    " source_kind TEXT, source_id TEXT, visibility TEXT, data TEXT, opened_version INTEGER,"
    " closed_version INTEGER, closed_reason TEXT, successor TEXT, checked_at TEXT)",
    "CREATE INDEX IF NOT EXISTS graph_bases_relationship ON graph_bases(scope, relationship)",
    "CREATE INDEX IF NOT EXISTS graph_bases_source ON graph_bases(scope, source_kind, source_id)",
    "CREATE TABLE IF NOT EXISTS graph_versions(version INTEGER PRIMARY KEY AUTOINCREMENT, scope TEXT,"
    " created_at TEXT, trigger TEXT, source_kind TEXT, source_id TEXT, summary TEXT)",
    "CREATE TABLE IF NOT EXISTS graph_events(scope TEXT, version INTEGER, basis TEXT, relationship TEXT,"
    " event TEXT, reason TEXT, successor TEXT, at TEXT)",
    "CREATE INDEX IF NOT EXISTS graph_events_basis ON graph_events(scope, basis)",
    "CREATE TABLE IF NOT EXISTS proposal_bases(id TEXT PRIMARY KEY, scope TEXT, visibility TEXT, bases TEXT,"
    " config TEXT)",
    "CREATE TABLE IF NOT EXISTS graph_sources(scope TEXT, source_kind TEXT, source_id TEXT, status TEXT,"
    " checked_at TEXT, last_success_at TEXT, source_version TEXT, reasons TEXT,"
    " PRIMARY KEY(scope, source_kind, source_id))",
)


def cited_bases(context, citations):
    """What a proposal depends on: each cited file's repository, path and content digest."""
    result = []
    for citation in citations:
        source = context["sources"].get(citation["source_id"])
        if source is None:
            raise GraphError("not_found")
        result.append(dict(source_id=source["id"], repository=source["repository"], path=source["path"],
                           sha256=source["sha256"]))
    return sorted(result, key=lambda b: (b["repository"], b["path"], b["source_id"]))


class Store:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not private_directory(directory):
            raise GraphError("private_state_directory_required")
        path = directory / "graph.sqlite3"
        if path.is_symlink():
            raise GraphError("invalid_state_path")
        self.path, self.directory = path, directory
        self._leases = {}
        self.db = sqlite3.connect(path, timeout=5, isolation_level=None)
        os.chmod(path, 0o600)
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS heads(view TEXT PRIMARY KEY, generation INTEGER, id TEXT);
            CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, view TEXT, kind TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS proposals(id TEXT PRIMARY KEY, view TEXT, data TEXT);
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY, installation TEXT,
                run TEXT, tokens INTEGER, micro INTEGER, currency TEXT, until REAL, active INTEGER);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        try:
            self._migrate()
        except BaseException:
            self.db.close()
            raise

    def schema_version(self):
        row = self.db.execute("SELECT value FROM meta WHERE key='store_schema'").fetchone()
        return int(row[0]) if row else 1

    def _migrate(self):
        """v1 -> v2: file backup of the v1 state, then additive tables; rerunning is a no-op.

        Tables are only added, never altered, so a v1 binary still works on this file.
        """
        if self.schema_version() > STORE_SCHEMA:
            raise GraphError("store_schema_newer")
        if self.schema_version() < STORE_SCHEMA and (
                self.db.execute("SELECT count(*) FROM artifacts").fetchone()[0]
                or self.db.execute("SELECT count(*) FROM proposals").fetchone()[0]):
            backup = self.directory / "graph.v1-backup.sqlite3"
            if not backup.exists():
                target = sqlite3.connect(backup)
                try:
                    self.db.backup(target)
                finally:
                    target.close()
                os.chmod(backup, 0o600)
        with self.transaction():
            for statement in GRAPH_DDL:
                self.db.execute(statement)
            # proposal_bases is a schema 2 table; development files made before the
            # config column existed get it here. v1 tables are never altered.
            if "config" not in {r[1] for r in self.db.execute("PRAGMA table_info(proposal_bases)")}:
                self.db.execute("ALTER TABLE proposal_bases ADD COLUMN config TEXT")
            self.db.execute("INSERT OR IGNORE INTO meta VALUES('store_schema', ?)", (str(STORE_SCHEMA),))
            self.db.execute("UPDATE meta SET value=? WHERE key='store_schema' AND CAST(value AS INTEGER) < ?",
                            (str(STORE_SCHEMA), STORE_SCHEMA))
        # Rows written by a v1 binary after the migration get their bases here too.
        if self.db.execute("SELECT 1 FROM proposals p LEFT JOIN proposal_bases b ON p.id=b.id"
                           " WHERE b.id IS NULL LIMIT 1").fetchone():
            with self.transaction():
                for id, view, data in self.db.execute(
                        "SELECT p.id,p.view,p.data FROM proposals p LEFT JOIN proposal_bases b ON p.id=b.id"
                        " WHERE b.id IS NULL").fetchall():
                    self.db.execute("INSERT OR IGNORE INTO proposal_bases VALUES(?,?,?,?,?)",
                                    (id, *self._derive_bases(view, load_json(data)), None))

    def _derive_bases(self, view, record):
        """(scope, visibility, bases) of a proposal from the context it was made in."""
        row = self.db.execute("SELECT data FROM artifacts WHERE id=? AND view=? AND kind='context'",
                              (record.get("context_id"), view)).fetchone()
        context = load_json(row[0]) if row else None
        try:
            bases = cited_bases(context, record["proposal"]["citations"]) if context else None
        except GraphError:
            bases = None
        if bases is None:
            # Unknown origin: kept for history, never CURRENT and visible to nobody.
            return "unknown", canonical(["?"]), canonical([])
        return (scope_id(context["installation_id"], context["environment"]),
                canonical(sorted({b["repository"] for b in bases})), canonical(bases))

    def close(self):
        # Abrupt owner teardown keeps the durable charge/lease. The OS releases
        # a live request's detached lock only when its worker/process ends.
        for fd in self._leases.values():
            os.close(fd)
        self._leases.clear()
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

    def scoped_proposals(self, scope, grants):
        """Proposals of one installation/environment whose cited repositories are all granted.

        Another view of the same scope sees them too (adding a repository keeps memory);
        a narrower grant never sees a proposal that cites a revoked repository.
        """
        grants = set(grants)
        result = []
        for view, data, b_scope, visibility, bases, config in self.db.execute(
                "SELECT p.view,p.data,b.scope,b.visibility,b.bases,b.config FROM proposals p"
                " LEFT JOIN proposal_bases b ON p.id=b.id ORDER BY p.id"):
            record = load_json(data)
            if b_scope is None:  # appended by a v1 binary while this store is open
                b_scope, visibility, bases = self._derive_bases(view, record)
            if b_scope == scope and set(load_json(visibility)) <= grants:
                # config: digest of the addresses and requirements the proposal was judged
                # under; None for v1 rows, whose view (which includes both) stands in.
                result.append({**record, "cited_bases": load_json(bases), "cited_config": config,
                               "cited_view": view})
        return result

    def propose(self, view, proposal, expected_head, *, limit, admission_check=None, scope=None,
                bases=None, grants=None, active=None, config=None):
        """scope/bases/grants/active: per-basis knowledge (schema 2). Without them the
        v1 rule applies: the limit counts the active set at the corpus basis."""
        id = proposal_identity(view, proposal)
        data = {**proposal, "id": id}
        with self.transaction():
            if admission_check:
                admission_check()
            if self.head(view)[1] != expected_head:
                raise GraphError("concurrent_update")
            rows = self.scoped_proposals(scope, grants) if scope is not None else self.proposals(view)
            duplicate = next((r for r in self.proposals(view) if proposal_identity(view, r) == id), None)
            if duplicate:
                return duplicate
            superseded = {r["proposal"]["supersedes"] for r in rows if r["proposal"]["supersedes"]}
            target = proposal["proposal"]["supersedes"]
            old = next((r for r in rows if r["id"] == target), None)
            if target:
                if (not old or old["proposal"]["key"] != proposal["proposal"]["key"]
                        or proposal["proposal"]["kind"] != "human_correction"):
                    raise GraphError("invalid_supersession")
                if target in superseded:
                    raise GraphError("concurrent_update")
            # The limit is the active set, not lifetime history. Replacement frees
            # its target's slot atomically with insertion.
            def live(row):
                return active(row) if active is not None else row["basis"] == proposal["basis"]
            counted = {r["id"] for r in rows if r["id"] not in superseded and live(r)}
            if old:
                counted.discard(old["id"])
            if len(counted) >= limit:
                raise GraphError("proposal_limit")
            self.db.execute("INSERT OR IGNORE INTO proposals VALUES(?,?,?)", (id, view, canonical(data)))
            if bases is not None:
                self.db.execute("INSERT OR IGNORE INTO proposal_bases VALUES(?,?,?,?,?)",
                                (id, scope, canonical(sorted({b["repository"] for b in bases})), canonical(bases),
                                 config))
            if admission_check:
                admission_check()
        return data

    def reserve(self, installation, run, tokens, config):
        lock = self.directory / ("inflight-" + digest(installation) + ".lock")
        fd = open_lock_file(lock)
        try:
            lock_nonblocking(fd)
        except OSError as exc:
            os.close(fd)
            if isinstance(exc, BlockingIOError):
                raise GraphError("model_busy") from None
            raise
        try:
            id = self._reserve(installation, run, tokens, config)
        except BaseException:
            os.close(fd)
            raise
        self._leases[id] = fd
        return id

    def _reserve(self, installation, run, tokens, config):
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
        try:
            self.db.execute("UPDATE reservations SET active=0 WHERE id=?", (id,))
        finally:
            fd = self._leases.pop(id, None)
            if fd is not None:
                os.close(fd)

    def reservation_finalizer(self, id):
        """Transfer ownership to a request worker; never use this connection there."""
        fd = self._leases.pop(id)
        path = self.path
        guard = threading.Lock()
        finished = False
        def finish():
            nonlocal finished
            with guard:
                if finished:
                    return
                finished = True
            try:
                db = sqlite3.connect(path, timeout=5)
                try:
                    db.execute("UPDATE reservations SET active=0 WHERE id=?", (id,))
                    db.commit()
                finally:
                    db.close()
            finally:
                os.close(fd)
        return finish

    def budget_totals(self, installation):
        row = self.db.execute("SELECT count(*),coalesce(sum(tokens),0),coalesce(sum(micro),0) FROM reservations WHERE installation=?",
                              (installation,)).fetchone()
        return dict(attempts=row[0], reserved_token_units=row[1], reserved_micro=row[2])
