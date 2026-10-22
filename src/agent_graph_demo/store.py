"""Durable bounded admission, immutable artifacts and revision CAS publication."""

from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import uuid

from .contracts import DemoError, canonical, digest, now

TERMINAL = {"SUCCEEDED", "PARTIAL", "FAILED", "CANCELLED", "UNKNOWN_AFTER_RESTART"}


class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()


class Store:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.root / "web.sqlite"
        with self.connect() as c:
            c.executescript("""
              PRAGMA journal_mode=WAL;
              CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, doc TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, session TEXT, actor TEXT, key TEXT,
                body TEXT, status TEXT, doc TEXT, UNIQUE(session,actor,key));
              CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY, session TEXT, kind TEXT, doc TEXT);
              CREATE TABLE IF NOT EXISTS resets(session TEXT,actor TEXT,key TEXT,body TEXT,target TEXT,
                UNIQUE(session,actor,key));
            """)

    def connect(self):
        c = sqlite3.connect(self.path, timeout=5, factory=ClosingConnection)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA synchronous=FULL")
        return c

    @contextmanager
    def transaction(self):
        c = self.connect()
        try:
            c.execute("BEGIN IMMEDIATE")
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    @staticmethod
    def session_in(c, sid):
        r = c.execute("SELECT doc FROM sessions WHERE id=?", (sid,)).fetchone()
        if not r:
            raise DemoError("not_found", 404)
        return json.loads(r[0])

    def session(self, sid):
        with self.connect() as c:
            return self.session_in(c, sid)

    @staticmethod
    def put_session(c, s):
        c.execute(
            "INSERT OR REPLACE INTO sessions VALUES(?,?)", (s["id"], canonical(s))
        )

    def create(self, sid, owner, manifest, *, connection=None):
        s = dict(
            id=sid,
            owner=owner,
            revision=1,
            scenario_version="A",
            proposed_manifest_sha256=manifest["manifest_sha256"],
            current_context_id=None,
            base_context_id=None,
            graph_ref=None,
            pending_job_id=None,
            created_at=now(),
            closed=False,
            needs_refresh=False,
            core_sha=manifest["core_sha"],
            product_sha=manifest["product_sha"],
        )
        if connection is None:
            with self.transaction() as c:
                self.put_session(c, s)
        else:
            self.put_session(connection, s)
        return s

    def artifact(self, sid, kind, value, c=None):
        aid = uuid.uuid4().hex
        if c is None:
            with self.transaction() as db:
                db.execute(
                    "INSERT INTO artifacts VALUES(?,?,?,?)",
                    (aid, sid, kind, canonical(value)),
                )
        else:
            c.execute(
                "INSERT INTO artifacts VALUES(?,?,?,?)",
                (aid, sid, kind, canonical(value)),
            )
        return aid

    def get_artifact(self, sid, aid, kind=None):
        with self.connect() as c:
            row = c.execute(
                "SELECT kind,doc FROM artifacts WHERE session=? AND id=?", (sid, aid)
            ).fetchone()
        if not row or kind and row["kind"] != kind:
            raise DemoError("not_found", 404)
        return json.loads(row["doc"])

    def artifacts(self, sid, kind):
        with self.connect() as c:
            return [
                {**json.loads(r["doc"]), "artifact_id": r["id"]}
                for r in c.execute(
                    "SELECT id,doc FROM artifacts WHERE session=? AND kind=? ORDER BY rowid",
                    (sid, kind),
                )
            ]

    def enqueue(self, sid, actor, body):
        encoded = canonical(body)
        with self.transaction() as c:
            old = c.execute(
                "SELECT body,doc FROM jobs WHERE session=? AND actor=? AND key=?",
                (sid, actor, body["idempotency_key"]),
            ).fetchone()
            if old:
                if old["body"] != encoded:
                    raise DemoError("idempotency_conflict")
                return json.loads(old["doc"])
            s = self.session_in(c, sid)
            if s["closed"]:
                raise DemoError("session_closed")
            if s["revision"] != body["expected_revision"]:
                raise DemoError("revision_conflict")
            if s["pending_job_id"]:
                raise DemoError("session_busy")
            if (
                c.execute("SELECT count(*) FROM jobs WHERE status='QUEUED'").fetchone()[
                    0
                ]
                >= 4
            ):
                raise DemoError("queue_full", 429)
            action = body["action"]
            p = body["payload"]
            cid = p.get("base_context_id") or p.get("context_id")
            if cid:
                refs = c.execute(
                    "SELECT doc FROM artifacts WHERE session=? AND kind='graph'", (sid,)
                ).fetchall()
                if not any(json.loads(r[0]).get("context_id") == cid for r in refs):
                    raise DemoError("context_not_published_here", 422)
            if action == "propose" and (
                cid != s["current_context_id"] or s.get("needs_refresh")
            ):
                raise DemoError("stale_context")
            if action == "investigate":
                raise DemoError("model_unavailable", 503)
            j = dict(
                id=str(uuid.uuid4()),
                session_id=sid,
                actor=actor,
                action=action,
                status="QUEUED",
                session_revision=s["revision"],
                target_revision=s["revision"] + (action == "analyze_change"),
                target_version=p.get("target_version"),
                payload=p,
                input_sha256=digest(body),
                created_at=now(),
                started_at=None,
                finished_at=None,
                result_ref=None,
                error_code=None,
                cancel_requested=False,
            )
            c.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?)",
                (
                    j["id"],
                    sid,
                    actor,
                    body["idempotency_key"],
                    encoded,
                    "QUEUED",
                    canonical(j),
                ),
            )
            s["pending_job_id"] = j["id"]
            self.put_session(c, s)
            return j

    @staticmethod
    def put_job(c, job):
        c.execute(
            "UPDATE jobs SET status=?,doc=? WHERE id=?",
            (job["status"], canonical(job), job["id"]),
        )

    def job(self, jid):
        with self.connect() as c:
            r = c.execute("SELECT doc FROM jobs WHERE id=?", (jid,)).fetchone()
        if not r:
            raise DemoError("not_found", 404)
        return json.loads(r[0])

    def jobs(self, sid):
        with self.connect() as c:
            return [
                json.loads(r[0])
                for r in c.execute(
                    "SELECT doc FROM jobs WHERE session=? ORDER BY rowid", (sid,)
                )
            ]

    def claim(self):
        with self.transaction() as c:
            if c.execute("SELECT 1 FROM jobs WHERE status='RUNNING'").fetchone():
                return None
            row = c.execute(
                "SELECT doc FROM jobs WHERE status='QUEUED' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if not row:
                return None
            j = json.loads(row[0])
            j.update(status="RUNNING", started_at=now())
            self.put_job(c, j)
            return j

    def cancel(self, jid):
        with self.transaction() as c:
            r = c.execute("SELECT doc FROM jobs WHERE id=?", (jid,)).fetchone()
            if not r:
                raise DemoError("not_found", 404)
            j = json.loads(r[0])
            if j["status"] not in TERMINAL:
                j["cancel_requested"] = True
                self.put_job(c, j)
            return j

    def finish(self, j, status, *, graph=None, result=None, manifest=None, error=None):
        with self.transaction() as c:
            s = self.session_in(c, j["session_id"])
            if s["revision"] != j["session_revision"] or s["pending_job_id"] != j["id"]:
                raise DemoError("publication_conflict")
            # Cancellation wins even if it races with completed CLI output.
            current = json.loads(
                c.execute("SELECT doc FROM jobs WHERE id=?", (j["id"],)).fetchone()[0]
            )
            if graph is not None and current["cancel_requested"]:
                raise DemoError("cancelled")
            if graph is not None:
                gref = self.artifact(s["id"], "graph", graph, c)
                s.update(
                    revision=j["target_revision"],
                    current_context_id=graph["context_id"],
                    graph_ref=gref,
                    needs_refresh=False,
                )
                if s["base_context_id"] is None:
                    s["base_context_id"] = graph["context_id"]
                if manifest:
                    s.update(
                        scenario_version=manifest["scenario_version"],
                        proposed_manifest_sha256=manifest["manifest_sha256"],
                    )
                j["result_ref"] = self.artifact(s["id"], "result", result, c)
                j["graph_ref"] = gref
            if graph is None:
                s["needs_refresh"] = True
            s["pending_job_id"] = None
            j.update(status=status, finished_at=now(), error_code=error)
            self.put_session(c, s)
            self.put_job(c, j)

    def running(self):
        with self.connect() as c:
            return [
                json.loads(r[0])
                for r in c.execute("SELECT doc FROM jobs WHERE status='RUNNING'")
            ]
