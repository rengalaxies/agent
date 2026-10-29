"""Durable SQLite queue for one installation.

Boundaries: one database file, one active worker (leases guard restarts and
an accidental second process, not horizontal scaling). Every state change is
a single ``BEGIN IMMEDIATE`` transaction with compare-and-set on generation
and lease owner, so a stale worker can never publish or overwrite state.

Tables:
- events: one row per provider delivery (dedup by provider+event_id);
- resources: current generation/version and the known comment per resource;
- jobs: one analysis per (resource, generation);
- intents: durable publication outbox, at most one live intent per resource;
- history: append-only audit (no payloads, no secrets);
- notices: bounded counters for connection problems;
- checkpoints: reconciliation cursors.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import time
import uuid

from .envelope import EventEnvelope, canonical

SCHEMA_VERSION = 1
LIVE_JOB_STATES = ("QUEUED", "RUNNING", "ANALYZED")
LIVE_INTENT_STATES = ("PENDING", "UNKNOWN", "BLOCKED")


class _Connection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Limits:
    def __init__(self, *, lease_seconds=300.0, max_analysis_attempts=4, max_publish_attempts=6,
                 backoff_base=5.0, backoff_cap=900.0, job_deadline_seconds=3600.0, create_settle_seconds=30.0):
        self.lease_seconds = lease_seconds
        self.max_analysis_attempts = max_analysis_attempts
        self.max_publish_attempts = max_publish_attempts
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.job_deadline_seconds = job_deadline_seconds
        self.create_settle_seconds = create_settle_seconds

    def backoff(self, attempts: int) -> float:
        return min(self.backoff_base * (2 ** max(attempts - 1, 0)), self.backoff_cap)


class ServiceStore:
    def __init__(self, path: Path, *, clock=time.time, limits: Limits | None = None):
        self.path = Path(path)
        self.clock = clock
        self.limits = limits or Limits()
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ValueError("state path must be a regular file")
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self._connect() as c:
            c.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS events(
                provider TEXT NOT NULL, event_id TEXT NOT NULL, source TEXT NOT NULL, event_kind TEXT NOT NULL,
                resource_id TEXT NOT NULL, version_hint TEXT, payload_digest TEXT NOT NULL,
                received_at REAL NOT NULL, state TEXT NOT NULL, reason TEXT, attempts INTEGER NOT NULL DEFAULT 0,
                not_before REAL NOT NULL, PRIMARY KEY(provider, event_id));
              CREATE INDEX IF NOT EXISTS events_due ON events(state, not_before);
              CREATE TABLE IF NOT EXISTS resources(
                resource_id TEXT PRIMARY KEY, provider TEXT NOT NULL, kind TEXT NOT NULL,
                generation INTEGER NOT NULL DEFAULT 0, version TEXT, snapshot TEXT, closed INTEGER NOT NULL DEFAULT 0,
                comment_id TEXT, comment_digest TEXT, published_generation INTEGER,
                create_unknown_at REAL, updated_at REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS jobs(
                job_id TEXT PRIMARY KEY, resource_id TEXT NOT NULL REFERENCES resources(resource_id),
                generation INTEGER NOT NULL, resource_version TEXT NOT NULL, event_id TEXT NOT NULL,
                state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, not_before REAL NOT NULL,
                deadline REAL NOT NULL, lease_owner TEXT, lease_expires REAL, claimed_at REAL,
                result TEXT, reason TEXT, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                UNIQUE(resource_id, generation));
              CREATE TABLE IF NOT EXISTS intents(
                intent_id TEXT PRIMARY KEY, resource_id TEXT NOT NULL REFERENCES resources(resource_id),
                generation INTEGER NOT NULL, resource_version TEXT NOT NULL, kind TEXT NOT NULL,
                job_id TEXT, result_digest TEXT, body TEXT NOT NULL, body_digest TEXT NOT NULL, marker TEXT NOT NULL,
                comment_id TEXT, operation TEXT, state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                not_before REAL NOT NULL, lease_owner TEXT, lease_expires REAL, reason TEXT, receipt TEXT,
                created_at REAL NOT NULL, updated_at REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS intents_due ON intents(state, not_before);
              CREATE TABLE IF NOT EXISTS history(
                seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, resource_id TEXT,
                entry TEXT NOT NULL, detail TEXT NOT NULL);
              CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
              CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history
                BEGIN SELECT RAISE(ABORT, 'append-only'); END;
              CREATE TABLE IF NOT EXISTS notices(
                key TEXT PRIMARY KEY, kind TEXT NOT NULL, subject TEXT, count INTEGER NOT NULL,
                first_at REAL NOT NULL, last_at REAL NOT NULL, detail TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS checkpoints(name TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)
            row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            if row is None:
                c.execute("INSERT INTO meta VALUES('schema_version', ?)", (str(SCHEMA_VERSION),))
            elif row[0] != str(SCHEMA_VERSION):
                raise ValueError("unsupported_state_schema")

    # -- plumbing ---------------------------------------------------------

    def _connect(self):
        c = sqlite3.connect(self.path, timeout=10, factory=_Connection, isolation_level=None)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA synchronous=FULL")
        c.execute("PRAGMA foreign_keys=ON")
        return c

    @contextmanager
    def _tx(self):
        c = self._connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.execute("COMMIT")
        except BaseException:
            c.execute("ROLLBACK")
            raise
        finally:
            c.close()

    def _history(self, c, resource_id, entry, **detail):
        c.execute("INSERT INTO history(at, resource_id, entry, detail) VALUES (?,?,?,?)",
                  (self.clock(), resource_id, entry, canonical(detail)))

    @staticmethod
    def _dict(row):
        if row is None:
            return None
        out = dict(row)
        for key in ("snapshot", "result", "receipt"):
            if out.get(key):
                out[key] = json.loads(out[key])
        return out

    # -- events -----------------------------------------------------------

    def add_event(self, env: EventEnvelope) -> tuple[bool, str]:
        """Insert a delivery once. Returns (inserted, state). Duplicate delivery ids are no-ops."""
        state = "IGNORED" if env.ignored_reason else "RECEIVED"
        with self._tx() as c:
            old = c.execute("SELECT state FROM events WHERE provider=? AND event_id=?",
                            (env.provider, env.event_id)).fetchone()
            if old:
                self._history(c, env.resource_id, "event_duplicate", provider=env.provider, event_id=env.event_id)
                return False, old["state"]
            c.execute(
                "INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,0,?)",
                (env.provider, env.event_id, env.source, env.event_kind, env.resource_id,
                 env.resource_version_hint, env.payload_digest, env.received_at, state,
                 env.ignored_reason, env.received_at))
            self._history(c, env.resource_id, "event_received", provider=env.provider, event_id=env.event_id,
                          event_kind=env.event_kind, state=state)
        return True, state

    def due_event(self):
        with self._connect() as c:
            return self._dict(c.execute(
                "SELECT * FROM events WHERE state='RECEIVED' AND not_before<=? ORDER BY received_at, rowid LIMIT 1",
                (self.clock(),)).fetchone())

    def defer_event(self, event, reason: str, delay: float | None = None) -> str:
        with self._tx() as c:
            attempts = event["attempts"] + 1
            if attempts >= self.limits.max_publish_attempts:
                c.execute("UPDATE events SET state='FAILED', reason=?, attempts=? WHERE provider=? AND event_id=?",
                          (reason, attempts, event["provider"], event["event_id"]))
                self._history(c, event["resource_id"], "event_failed", event_id=event["event_id"], reason=reason)
                return "FAILED"
            wait = delay if delay is not None else self.limits.backoff(attempts)
            c.execute("UPDATE events SET reason=?, attempts=?, not_before=? WHERE provider=? AND event_id=?",
                      (reason, attempts, self.clock() + wait, event["provider"], event["event_id"]))
            self._history(c, event["resource_id"], "event_deferred", event_id=event["event_id"], reason=reason,
                          attempts=attempts)
            return "RECEIVED"

    def finish_event(self, event, state: str, reason: str | None = None):
        with self._tx() as c:
            c.execute("UPDATE events SET state=?, reason=? WHERE provider=? AND event_id=? AND state='RECEIVED'",
                      (state, reason, event["provider"], event["event_id"]))

    def newer_event_pending(self, resource_id: str, version: str, since: float) -> bool:
        """A signed delivery received after ``since`` claims a different version."""
        with self._connect() as c:
            return c.execute(
                "SELECT 1 FROM events WHERE resource_id=? AND state='RECEIVED' AND received_at>=? "
                "AND version_hint IS NOT NULL AND version_hint<>? LIMIT 1",
                (resource_id, since, version)).fetchone() is not None

    # -- resources and generations ---------------------------------------

    def resource(self, resource_id: str):
        with self._connect() as c:
            return self._dict(c.execute("SELECT * FROM resources WHERE resource_id=?", (resource_id,)).fetchone())

    def apply_snapshot(self, *, resource_id: str, provider: str, kind: str, version: str, snapshot: dict,
                       event_id: str, closed: bool = False, stale_notice=None) -> dict:
        """Record the fetched state. A new version opens a new generation and revokes the old one.

        ``stale_notice(generation) -> (body, body_digest, marker)`` renders a
        notice replacing an already published older result.
        """
        now = self.clock()
        with self._tx() as c:
            row = c.execute("SELECT * FROM resources WHERE resource_id=?", (resource_id,)).fetchone()
            if row is None:
                c.execute("INSERT INTO resources(resource_id, provider, kind, updated_at) VALUES (?,?,?,?)",
                          (resource_id, provider, kind, now))
                row = c.execute("SELECT * FROM resources WHERE resource_id=?", (resource_id,)).fetchone()
            if closed:
                if not row["closed"]:
                    self._revoke(c, resource_id, row["generation"] + 1, "resource_closed")
                    c.execute("UPDATE resources SET closed=1, updated_at=? WHERE resource_id=?", (now, resource_id))
                    self._history(c, resource_id, "resource_closed", event_id=event_id)
                return {"action": "closed", "generation": row["generation"]}
            if row["version"] == version and not row["closed"]:
                self._history(c, resource_id, "event_coalesced", event_id=event_id, generation=row["generation"])
                return {"action": "coalesced", "generation": row["generation"]}
            generation = row["generation"] + 1
            self._revoke(c, resource_id, generation, "superseded_by_new_version")
            c.execute("UPDATE resources SET generation=?, version=?, snapshot=?, closed=0, updated_at=? "
                      "WHERE resource_id=?", (generation, version, canonical(snapshot), now, resource_id))
            job_id = uuid.uuid4().hex
            c.execute("INSERT INTO jobs(job_id, resource_id, generation, resource_version, event_id, state, "
                      "not_before, deadline, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (job_id, resource_id, generation, version, event_id, "QUEUED", now,
                       now + self.limits.job_deadline_seconds, now, now))
            self._history(c, resource_id, "generation_opened", generation=generation, event_id=event_id,
                          version_digest=version[:16])
            if stale_notice and row["published_generation"] is not None:
                body, body_digest, marker = stale_notice(generation)
                self._insert_intent(c, resource_id, generation, version, "stale", None, None, body,
                                    body_digest, marker, now)
            return {"action": "new_generation", "generation": generation, "job_id": job_id}

    def _revoke(self, c, resource_id, generation, reason):
        now = self.clock()
        jobs = c.execute("UPDATE jobs SET state='SUPERSEDED', reason=?, updated_at=? WHERE resource_id=? "
                         f"AND generation<? AND state IN {LIVE_JOB_STATES}", (reason, now, resource_id, generation))
        intents = c.execute("UPDATE intents SET state='SUPERSEDED', reason=?, updated_at=? WHERE resource_id=? "
                            f"AND generation<? AND state IN {LIVE_INTENT_STATES}",
                            (reason, now, resource_id, generation))
        if jobs.rowcount or intents.rowcount:
            self._history(c, resource_id, "generation_revoked", below=generation, jobs=jobs.rowcount,
                          intents=intents.rowcount, reason=reason)

    def resources(self, provider: str | None = None):
        with self._connect() as c:
            sql, args = "SELECT * FROM resources", ()
            if provider:
                sql, args = sql + " WHERE provider=?", (provider,)
            return [self._dict(r) for r in c.execute(sql, args)]

    # -- analysis jobs ----------------------------------------------------

    def job(self, job_id):
        with self._connect() as c:
            return self._dict(c.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone())

    def jobs(self, resource_id):
        with self._connect() as c:
            return [self._dict(r) for r in c.execute(
                "SELECT * FROM jobs WHERE resource_id=? ORDER BY generation", (resource_id,))]

    def published_result(self, resource_id: str, generation: int):
        """(generation, resource version, result) last delivered as current before ``generation``, or None."""
        with self._connect() as c:
            row = c.execute("SELECT generation, resource_version, result FROM jobs WHERE resource_id=? "
                            "AND generation<? AND state='DONE' AND result IS NOT NULL "
                            "ORDER BY generation DESC LIMIT 1", (resource_id, generation)).fetchone()
        return (row["generation"], row["resource_version"], json.loads(row["result"])) if row else None

    def claim_job(self, worker: str):
        now = self.clock()
        with self._tx() as c:
            while True:
                row = c.execute("SELECT * FROM jobs WHERE state='QUEUED' AND not_before<=? "
                                "ORDER BY not_before, created_at LIMIT 1", (now,)).fetchone()
                if row is None:
                    return None
                if row["deadline"] <= now:
                    c.execute("UPDATE jobs SET state='FAILED', reason='deadline_exceeded', updated_at=? "
                              "WHERE job_id=?", (now, row["job_id"]))
                    self._history(c, row["resource_id"], "job_failed", generation=row["generation"],
                                  reason="deadline_exceeded")
                    continue
                c.execute("UPDATE jobs SET state='RUNNING', attempts=attempts+1, lease_owner=?, lease_expires=?, "
                          "claimed_at=?, updated_at=? WHERE job_id=?",
                          (worker, now + self.limits.lease_seconds, now, now, row["job_id"]))
                self._history(c, row["resource_id"], "job_claimed", generation=row["generation"],
                              attempt=row["attempts"] + 1)
                job = self._dict(c.execute("SELECT * FROM jobs WHERE job_id=?", (row["job_id"],)).fetchone())
                job["snapshot"] = json.loads(c.execute("SELECT snapshot FROM resources WHERE resource_id=?",
                                                       (row["resource_id"],)).fetchone()[0])
                return job

    def job_is_current(self, job) -> bool:
        with self._connect() as c:
            row = c.execute("SELECT j.state, j.lease_owner, r.generation FROM jobs j JOIN resources r "
                            "USING(resource_id) WHERE j.job_id=?", (job["job_id"],)).fetchone()
        return bool(row) and row["state"] == "RUNNING" and row["lease_owner"] == job["lease_owner"] \
            and row["generation"] == job["generation"]

    def requeue_job(self, job, reason: str, *, count_attempt: bool, delay: float | None = None) -> str:
        """Release a RUNNING job. Bounded: exhausted attempts end in FAILED."""
        now = self.clock()
        with self._tx() as c:
            if not self._owns_job(c, job):
                return "LOST"
            attempts = job["attempts"] if count_attempt else job["attempts"] - 1
            if count_attempt and attempts >= self.limits.max_analysis_attempts:
                c.execute("UPDATE jobs SET state='FAILED', reason=?, lease_owner=NULL, updated_at=? WHERE job_id=?",
                          (reason, now, job["job_id"]))
                self._history(c, job["resource_id"], "job_failed", generation=job["generation"], reason=reason)
                return "FAILED"
            delay = delay if delay is not None else (self.limits.backoff(attempts) if count_attempt else 0.0)
            c.execute("UPDATE jobs SET state='QUEUED', attempts=?, not_before=?, reason=?, lease_owner=NULL, "
                      "lease_expires=NULL, updated_at=? WHERE job_id=?",
                      (attempts, now + delay, reason, now, job["job_id"]))
            self._history(c, job["resource_id"], "job_requeued", generation=job["generation"], reason=reason,
                          delay=delay)
            return "QUEUED"

    def _owns_job(self, c, job) -> bool:
        row = c.execute("SELECT j.state, j.lease_owner, r.generation FROM jobs j JOIN resources r "
                        "USING(resource_id) WHERE j.job_id=?", (job["job_id"],)).fetchone()
        return bool(row) and row["state"] == "RUNNING" and row["lease_owner"] == job["lease_owner"] \
            and row["generation"] == job["generation"]

    def complete_job(self, job, *, state: str, result: dict | None, reason: str | None, intent: dict | None):
        """CAS: only the lease owner of the current generation stores a result and its intent."""
        now = self.clock()
        with self._tx() as c:
            if not self._owns_job(c, job):
                # Either a newer generation exists (already SUPERSEDED by _revoke) or the
                # lease expired and recovery handed the job on: in both cases discard.
                if result is not None and c.execute("SELECT 1 FROM jobs WHERE job_id=? AND state='SUPERSEDED'",
                                                    (job["job_id"],)).fetchone():
                    c.execute("UPDATE jobs SET result=? WHERE job_id=?", (canonical(result), job["job_id"]))
                self._history(c, job["resource_id"], "result_discarded_superseded", generation=job["generation"])
                return None
            c.execute("UPDATE jobs SET state=?, result=?, reason=?, lease_owner=NULL, lease_expires=NULL, "
                      "updated_at=? WHERE job_id=?",
                      (state, canonical(result) if result is not None else None, reason, now, job["job_id"]))
            self._history(c, job["resource_id"], "job_" + state.lower(), generation=job["generation"], reason=reason)
            if intent is None:
                return None
            # The result supersedes any not yet sent notice of the same generation.
            c.execute("UPDATE intents SET state='SUPERSEDED', reason='replaced_by_result', updated_at=? "
                      f"WHERE resource_id=? AND state IN {LIVE_INTENT_STATES}", (now, job["resource_id"]))
            return self._insert_intent(c, job["resource_id"], job["generation"], job["resource_version"],
                                       intent["kind"], job["job_id"], intent.get("result_digest"), intent["body"],
                                       intent["body_digest"], intent["marker"], now)

    # -- publication intents ---------------------------------------------

    def _insert_intent(self, c, resource_id, generation, version, kind, job_id, result_digest, body, body_digest,
                       marker, now):
        intent_id = uuid.uuid4().hex
        c.execute("INSERT INTO intents(intent_id, resource_id, generation, resource_version, kind, job_id, "
                  "result_digest, body, body_digest, marker, state, not_before, created_at, updated_at) "
                  "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (intent_id, resource_id, generation, version, kind, job_id, result_digest, body, body_digest,
                   marker, "PENDING", now, now, now))
        self._history(c, resource_id, "intent_created", generation=generation, intent_kind=kind,
                      body_digest=body_digest[:16])
        return intent_id

    def intent(self, intent_id):
        with self._connect() as c:
            return self._dict(c.execute("SELECT * FROM intents WHERE intent_id=?", (intent_id,)).fetchone())

    def intents(self, resource_id):
        with self._connect() as c:
            return [self._dict(r) for r in c.execute(
                "SELECT * FROM intents WHERE resource_id=? ORDER BY created_at, rowid", (resource_id,))]

    def claim_intent(self, worker: str):
        now = self.clock()
        with self._tx() as c:
            row = c.execute(
                "SELECT * FROM intents WHERE state IN ('PENDING','UNKNOWN') AND not_before<=? "
                "AND (lease_expires IS NULL OR lease_expires<=?) ORDER BY not_before, created_at LIMIT 1",
                (now, now)).fetchone()
            if row is None:
                return None
            c.execute("UPDATE intents SET lease_owner=?, lease_expires=?, attempts=attempts+1, updated_at=? "
                      "WHERE intent_id=?", (worker, now + self.limits.lease_seconds, now, row["intent_id"]))
            return self._dict(c.execute("SELECT * FROM intents WHERE intent_id=?", (row["intent_id"],)).fetchone())

    def _owns_intent(self, c, intent, states=("PENDING", "UNKNOWN", "SENDING")):
        row = c.execute("SELECT state, lease_owner FROM intents WHERE intent_id=?", (intent["intent_id"],)).fetchone()
        return bool(row) and row["lease_owner"] == intent["lease_owner"] and row["state"] in states

    def intent_is_current(self, intent) -> bool:
        """Publication right: newest generation, resource open, intent not revoked."""
        with self._connect() as c:
            row = c.execute("SELECT i.state, i.lease_owner, r.generation, r.closed FROM intents i "
                            "JOIN resources r USING(resource_id) WHERE i.intent_id=?",
                            (intent["intent_id"],)).fetchone()
        return bool(row) and row["state"] in ("PENDING", "UNKNOWN", "SENDING") and \
            row["lease_owner"] == intent["lease_owner"] and row["generation"] == intent["generation"] and \
            not row["closed"]

    def mark_sending(self, intent, *, operation: str, comment_id: str | None) -> bool:
        """Persist the write we are about to make. After a crash this row says the outcome is unknown."""
        now = self.clock()
        with self._tx() as c:
            if not self._owns_intent(c, intent, ("PENDING", "UNKNOWN")):
                return False
            row = c.execute("SELECT r.generation, r.closed FROM resources r WHERE resource_id=?",
                            (intent["resource_id"],)).fetchone()
            if row["generation"] != intent["generation"] or row["closed"]:
                return False
            c.execute("UPDATE intents SET state='SENDING', operation=?, comment_id=?, updated_at=? WHERE intent_id=?",
                      (operation, comment_id, now, intent["intent_id"]))
            if operation == "create":
                c.execute("UPDATE resources SET create_unknown_at=? WHERE resource_id=?", (now, intent["resource_id"]))
            self._history(c, intent["resource_id"], "intent_sending", generation=intent["generation"],
                          operation=operation)
            return True

    def intent_delivered(self, intent, *, comment_id: str, comment_digest: str, wrote: bool) -> bool:
        """Record a confirmed comment state. Returns False if the generation was superseded meanwhile."""
        now = self.clock()
        with self._tx() as c:
            if not self._owns_intent(c, intent, ("PENDING", "UNKNOWN", "SENDING")):
                return False
            res = c.execute("SELECT generation, closed FROM resources WHERE resource_id=?",
                            (intent["resource_id"],)).fetchone()
            current = res["generation"] == intent["generation"] and not res["closed"]
            c.execute("UPDATE intents SET state='DELIVERED', comment_id=?, lease_owner=NULL, receipt=?, updated_at=? "
                      "WHERE intent_id=?",
                      (comment_id, canonical({"wrote": wrote, "current_at_delivery": current}), now,
                       intent["intent_id"]))
            # The comment now shows this body whether or not it is still current.
            c.execute("UPDATE resources SET comment_id=?, comment_digest=?, create_unknown_at=NULL, "
                      "published_generation=CASE WHEN ? THEN ? ELSE published_generation END WHERE resource_id=?",
                      (comment_id, comment_digest, current, intent["generation"], intent["resource_id"]))
            if current and intent["kind"] == "result" and intent["job_id"]:
                # A FAILED job stays FAILED after its failure notice so reconciliation can retry it.
                c.execute("UPDATE jobs SET state='DONE', updated_at=? WHERE job_id=? AND state='ANALYZED'",
                          (now, intent["job_id"]))
            self._history(c, intent["resource_id"], "intent_delivered", generation=intent["generation"],
                          wrote=wrote, current=current)
            return current

    def intent_retry(self, intent, reason: str, *, delay: float | None = None, state: str = "PENDING") -> str:
        """Bounded retry. ``state='UNKNOWN'`` means the last write may have happened."""
        now = self.clock()
        with self._tx() as c:
            if not self._owns_intent(c, intent):
                return "LOST"
            if intent["attempts"] >= self.limits.max_publish_attempts:
                c.execute("UPDATE intents SET state='FAILED', reason=?, lease_owner=NULL, updated_at=? "
                          "WHERE intent_id=?", (reason, now, intent["intent_id"]))
                self._history(c, intent["resource_id"], "intent_failed", generation=intent["generation"],
                              reason=reason)
                return "FAILED"
            wait = delay if delay is not None else self.limits.backoff(intent["attempts"])
            c.execute("UPDATE intents SET state=?, reason=?, not_before=?, lease_owner=NULL, lease_expires=NULL, "
                      "updated_at=? WHERE intent_id=?", (state, reason, now + wait, now, intent["intent_id"]))
            self._history(c, intent["resource_id"], "intent_retry", generation=intent["generation"], reason=reason,
                          delay=wait, state=state)
            return state

    def intent_final(self, intent, state: str, reason: str):
        now = self.clock()
        with self._tx() as c:
            if not self._owns_intent(c, intent):
                return
            c.execute("UPDATE intents SET state=?, reason=?, lease_owner=NULL, updated_at=? WHERE intent_id=?",
                      (state, reason, now, intent["intent_id"]))
            self._history(c, intent["resource_id"], "intent_" + state.lower(), generation=intent["generation"],
                          reason=reason)

    def forget_comment(self, resource_id: str, comment_id: str):
        with self._tx() as c:
            c.execute("UPDATE resources SET comment_id=NULL, comment_digest=NULL WHERE resource_id=? AND comment_id=?",
                      (resource_id, comment_id))
            self._history(c, resource_id, "comment_missing", comment_id=comment_id)

    def clear_create_unknown(self, resource_id: str):
        with self._tx() as c:
            c.execute("UPDATE resources SET create_unknown_at=NULL WHERE resource_id=?", (resource_id,))

    # -- recovery and reconciliation -------------------------------------

    def recover(self) -> dict:
        """Startup/periodic: expired leases return work; an interrupted write becomes UNKNOWN."""
        now = self.clock()
        with self._tx() as c:
            jobs = c.execute("SELECT * FROM jobs WHERE state='RUNNING' AND lease_expires<=?", (now,)).fetchall()
            for job in jobs:
                exhausted = job["attempts"] >= self.limits.max_analysis_attempts
                c.execute("UPDATE jobs SET state=?, reason='lease_expired', lease_owner=NULL, lease_expires=NULL, "
                          "not_before=?, updated_at=? WHERE job_id=?",
                          ("FAILED" if exhausted else "QUEUED", now, now, job["job_id"]))
                self._history(c, job["resource_id"], "job_recovered", generation=job["generation"],
                              failed=exhausted)
            sending = c.execute("SELECT * FROM intents WHERE state='SENDING' AND lease_expires<=?", (now,)).fetchall()
            for intent in sending:
                c.execute("UPDATE intents SET state='UNKNOWN', reason='interrupted_during_send', lease_owner=NULL, "
                          "lease_expires=NULL, not_before=?, updated_at=? WHERE intent_id=?",
                          (now, now, intent["intent_id"]))
                self._history(c, intent["resource_id"], "intent_recovered_unknown", generation=intent["generation"],
                              operation=intent["operation"])
            released = c.execute("UPDATE intents SET lease_owner=NULL, lease_expires=NULL WHERE state IN "
                                 "('PENDING','UNKNOWN') AND lease_expires<=?", (now,)).rowcount
            # A superseded write in doubt is never resent; the newer generation overwrites the comment.
            c.execute("UPDATE intents SET state='SUPERSEDED', reason='superseded_while_unknown' WHERE state='UNKNOWN' "
                      "AND generation < (SELECT generation FROM resources r WHERE r.resource_id=intents.resource_id)")
        return {"jobs": len(jobs), "sending": len(sending), "released": released}

    def revive(self) -> int:
        """Reconciliation pass: give current-generation work that ran out of retries one more bounded round."""
        now = self.clock()
        with self._tx() as c:
            intents = c.execute(
                "UPDATE intents SET state='PENDING', attempts=0, not_before=?, updated_at=? WHERE state IN "
                "('BLOCKED','FAILED') AND reason IN ('connection_unauthorized','rate_limited','provider_unavailable',"
                "'outcome_unknown') AND generation=(SELECT generation FROM resources r "
                "WHERE r.resource_id=intents.resource_id AND r.closed=0)", (now, now)).rowcount
            # A repeated identical failure renders the same body digest, so the
            # publisher finds the comment unchanged and writes nothing.
            jobs = c.execute(
                "UPDATE jobs SET state='QUEUED', attempts=0, not_before=?, deadline=?, updated_at=? WHERE "
                "state='FAILED' AND result IS NULL AND reason IN ('analysis_unavailable','analysis_not_wired',"
                "'source_unavailable','provider_unavailable','rate_limited','lease_expired','outcome_unknown',"
                "'deadline_exceeded') AND generation=(SELECT generation FROM resources r "
                "WHERE r.resource_id=jobs.resource_id AND r.closed=0)",
                (now, now + self.limits.job_deadline_seconds, now)).rowcount
            events = c.execute("UPDATE events SET state='RECEIVED', attempts=0, not_before=? WHERE state='FAILED' AND "
                               "reason IN ('connection_unauthorized','rate_limited','provider_unavailable',"
                               "'outcome_unknown')", (now,)).rowcount
            if intents or jobs or events:
                self._history(c, None, "revived", intents=intents, jobs=jobs, events=events)
            return intents + jobs + events

    def block_intent(self, intent, reason: str, delay: float):
        """Connection problem: do not burn retries, wait for reconciliation or the delay."""
        now = self.clock()
        with self._tx() as c:
            if not self._owns_intent(c, intent):
                return
            c.execute("UPDATE intents SET state='BLOCKED', reason=?, not_before=?, lease_owner=NULL, "
                      "lease_expires=NULL, updated_at=? WHERE intent_id=?", (reason, now + delay, now,
                                                                             intent["intent_id"]))
            self._history(c, intent["resource_id"], "intent_blocked", generation=intent["generation"], reason=reason)

    def unblock_due(self):
        now = self.clock()
        with self._tx() as c:
            c.execute("UPDATE intents SET state='PENDING' WHERE state='BLOCKED' AND not_before<=?", (now,))

    def note(self, kind: str, subject: str | None, detail: str) -> int:
        """Count a repeated problem once per kind/subject (provider or resource) instead of one record each."""
        now = self.clock()
        key = f"{kind}:{subject or '-'}"
        with self._tx() as c:
            row = c.execute("SELECT count FROM notices WHERE key=?", (key,)).fetchone()
            if row:
                c.execute("UPDATE notices SET count=count+1, last_at=?, detail=? WHERE key=?", (now, detail, key))
                return row["count"] + 1
            c.execute("INSERT INTO notices VALUES (?,?,?,?,?,?,?)", (key, kind, subject, 1, now, now, detail))
            self._history(c, None, "notice", notice=kind, subject=subject, detail=detail)
            return 1

    def clear_notice(self, kind: str, subject: str | None):
        with self._tx() as c:
            c.execute("DELETE FROM notices WHERE key=?", (f"{kind}:{subject or '-'}",))

    def notices(self):
        with self._connect() as c:
            return [dict(r) for r in c.execute("SELECT * FROM notices ORDER BY key")]

    def checkpoint(self, name: str, value: str | None = None):
        with self._tx() as c:
            if value is not None:
                c.execute("INSERT OR REPLACE INTO checkpoints VALUES (?,?)", (name, value))
                return value
            row = c.execute("SELECT value FROM checkpoints WHERE name=?", (name,)).fetchone()
            return row["value"] if row else None

    def history(self, resource_id: str | None = None):
        with self._connect() as c:
            sql, args = "SELECT * FROM history", ()
            if resource_id is not None:
                sql, args = sql + " WHERE resource_id=?", (resource_id,)
            return [{**dict(r), "detail": json.loads(r["detail"])} for r in c.execute(sql + " ORDER BY seq", args)]

    def status(self) -> dict:
        """Safe diagnostics: counts and reason codes only."""
        with self._connect() as c:
            out = {}
            for table in ("events", "jobs", "intents"):
                out[table] = {r[0]: r[1] for r in c.execute(f"SELECT state, count(*) FROM {table} GROUP BY state")}
            out["notices"] = [{k: r[k] for k in ("kind", "subject", "count", "last_at", "detail")}
                              for r in c.execute("SELECT * FROM notices ORDER BY key")]
            return out
