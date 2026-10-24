"""One authenticated same-origin demo app and one persistent CLI worker."""

from contextlib import asynccontextmanager
import json
from pathlib import Path
import threading
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import authenticate, authorize_session
from .contracts import (
    CorrectionRequest,
    DemoError,
    DemoSettings,
    JobRequest,
    ResetRequest,
    Strict,
    VERSIONS,
    canonical,
)
from .graph_cli import GraphCLI
from .locks import locked
from .runtime import applicable, observe
from .snapshots import Snapshots
from .store import Store
from .worker import Worker

WEB = Path(__file__).parent / "web"


def create_app(settings: DemoSettings):
    store = Store(settings.state_root)
    snapshots = Snapshots(settings.state_root, settings.product_sha)
    cli = GraphCLI(settings.core_root)
    worker = Worker(store, snapshots, cli, settings.job_seconds)
    failure = []

    @asynccontextmanager
    async def lifespan(app):
        thread = None
        if settings.start_worker:

            def run():
                try:
                    worker.run()
                except Exception:
                    failure.append("worker_unavailable")

            thread = threading.Thread(target=run, daemon=True)
            thread.start()
        yield
        worker.stop.set()
        if thread:
            thread.join(timeout=3)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.store, app.state.snapshots, app.state.worker = store, snapshots, worker

    @app.exception_handler(DemoError)
    async def error(request, exc):
        return JSONResponse(
            {"error": exc.code},
            status_code=exc.status,
            headers={"WWW-Authenticate": 'Basic realm="Agent Graph Demo"'}
            if exc.status == 401
            else {},
        )

    @app.middleware("http")
    async def guard(request: Request, call_next):
        try:
            if (
                request.headers.get("content-length")
                and int(request.headers["content-length"]) > 16384
            ):
                raise DemoError("request_too_large", 413)
            request.state.actor = authenticate(request, settings)
            # Public TLS terminates at pinned proxy. Never trust arbitrary forwarded-proto headers here.
            if request.method not in ("GET", "HEAD"):
                if request.state.actor.role != "operator":
                    raise DemoError("operator_required", 403)
                if request.headers.get("origin") not in settings.allowed_origins:
                    raise DemoError("origin_forbidden", 403)
                if failure:
                    raise DemoError("worker_unavailable", 503)
            response = await call_next(request)
        except DemoError as exc:
            response = await error(request, exc)
        response.headers.update(
            {
                "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'",
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
            }
        )
        return response

    def session(request, sid, write=False):
        try:
            uuid.UUID(sid)
        except ValueError:
            raise DemoError("not_found", 404) from None
        s = store.session(sid)
        authorize_session(request.state.actor, s, write)
        return s

    def decorate(s):
        runtime = observe(settings.runtime_registry_path)
        if runtime.get("session_id") and runtime["session_id"] != s["id"]:
            runtime = {
                k: v
                for k, v in runtime.items()
                if k in ("state", "generation", "observed_at", "reason")
            }
            runtime["reason"] = "another_session"
        running = (
            runtime.get("manifest_sha256")
            if runtime["state"] == "RUNNING" and runtime.get("session_id") == s["id"]
            else None
        )
        return {
            **s,
            "runtime": runtime,
            "running_manifest_sha256": running,
            "running_version": next(
                (
                    v
                    for v in ("A", "B", "D", "E")
                    if snapshots.manifest(s["id"], v)["manifest_sha256"] == running
                ),
                None,
            ),
            "external_reports": store.artifacts(s["id"], "external_report"),
            "jobs": store.jobs(s["id"]),
            "checks": [
                {**r, "applicable": applicable(r, s)}
                for r in store.artifacts(s["id"], "receipt")
            ],
            "model": {
                "status": "UNAVAILABLE",
                "reason": "Квалификация реальной модели выполняется отдельно",
            },
            "operator_action": "Для реальной проверки оператор запускает закреплённый runner. Выбор версии в UI не запускает сервисы.",
        }

    @app.get("/api/demo/me")
    def me(request: Request):
        return {"role": request.state.actor.role}

    @app.get("/")
    def index():
        return FileResponse(WEB / "index.html")

    @app.get("/api/demo/sessions")
    def sessions(request: Request):
        actor = request.state.actor
        with store.connect() as c:
            ss = [
                json.loads(r[0])
                for r in c.execute("SELECT doc FROM sessions ORDER BY rowid DESC")
            ]
        return [
            {
                "id": s["id"],
                "scenario_version": s["scenario_version"],
                "created_at": s["created_at"],
                "closed": s["closed"],
            }
            for s in ss
            if s["owner"] == actor.subject or s["id"] in actor.allowed_session_ids
        ]

    @app.post("/api/demo/sessions", status_code=201)
    def create_session(request: Request, body: Strict):
        with locked(settings.state_root / "workload.lock"):
            sid = str(uuid.uuid4())
            return decorate(
                store.create(sid, request.state.actor.subject, snapshots.create(sid))
            )

    @app.get("/api/demo/sessions/{sid}")
    def get_session(sid: str, request: Request):
        return decorate(session(request, sid))

    @app.post("/api/demo/sessions/{sid}/jobs", status_code=202)
    def jobs(sid: str, body: JobRequest, request: Request):
        session(request, sid, True)
        return store.enqueue(
            sid, request.state.actor.subject, body.model_dump(exclude_none=True)
        )

    @app.get("/api/demo/jobs/{jid}")
    def get_job(jid: str, request: Request):
        j = store.job(jid)
        session(request, j["session_id"])
        return {
            **j,
            "result": store.get_artifact(j["session_id"], j["result_ref"])
            if j["result_ref"]
            else None,
        }

    @app.post("/api/demo/jobs/{jid}/cancel", status_code=202)
    def cancel_job(jid: str, request: Request):
        j = store.job(jid)
        session(request, j["session_id"], True)
        return store.cancel(jid)

    @app.get("/api/demo/sessions/{sid}/graph")
    def graph(sid: str, request: Request, job_id: str | None = None):
        s = session(request, sid)
        ref = s["graph_ref"]
        revision = s["revision"]
        if job_id:
            j = store.job(job_id)
            if j["session_id"] != sid:
                raise DemoError("session_forbidden", 403)
            ref, revision = j.get("graph_ref"), j["target_revision"]
        if not ref:
            return {
                "dependencies": [],
                "operations": [],
                "coverage": "UNKNOWN",
                "freshness": {"status": "UNKNOWN"},
                "proposals": [],
                "gaps": [],
            }
        g = store.get_artifact(sid, ref, "graph")
        # No hidden rescan on polling. Freshness is last assessment, explicitly timestamped.
        historical = (
            revision != s["revision"] or g["context_id"] != s["current_context_id"]
        )
        from datetime import datetime, timezone

        assessed = g["freshness"].get("assessed_at")
        expired = (
            not assessed
            or (
                datetime.now(timezone.utc) - datetime.fromisoformat(assessed)
            ).total_seconds()
            > 3600
        )
        return {
            **g,
            "historical": historical,
            "session_revision": revision,
            "freshness": {
                **g["freshness"],
                **(
                    {"status": "STALE", "reason": "historical_result"}
                    if historical
                    else {
                        "status": "UNKNOWN",
                        "reason": "refresh_after_interrupted_job",
                    }
                    if s.get("needs_refresh")
                    else {"status": "STALE", "reason": "assessment_expired"}
                    if expired
                    else {}
                ),
            },
        }

    @app.get("/api/demo/sessions/{sid}/evidence/{eid}")
    def evidence(sid: str, eid: str, request: Request):
        s = session(request, sid)
        e = store.get_artifact(sid, eid, "evidence")
        return {**e, "historical": e["context_id"] != s["current_context_id"]}

    @app.get("/api/demo/sessions/{sid}/diff")
    def diff(sid: str, request: Request, job_id: str | None = None):
        import difflib

        s = session(request, sid)
        version = s["scenario_version"]
        if job_id:
            j = store.job(job_id)
            if j["session_id"] != sid:
                raise DemoError("session_forbidden", 403)
            if j.get("graph_ref"):
                version = store.get_artifact(sid, j["graph_ref"], "graph")["demo_version"]
            elif j["target_version"]:
                version = j["target_version"]
            else:
                raise DemoError("historical_diff_unavailable")
            if version not in VERSIONS:
                raise DemoError("historical_diff_unavailable")
        base = snapshots.session_root(sid) / "snapshots/A/corpus"
        target = snapshots.session_root(sid) / "snapshots" / version / "corpus"
        patches = []
        for f in sorted(base.rglob("*")):
            if f.is_file():
                name = f.relative_to(base).as_posix()
                patches.extend(
                    difflib.unified_diff(
                        f.read_text().splitlines(),
                        (target / name).read_text().splitlines(),
                        fromfile="A/" + name,
                        tofile=version + "/" + name,
                        lineterm="",
                    )
                )
        return {"version": version, "text": "\n".join(patches)}

    @app.post("/api/demo/sessions/{sid}/proposals", status_code=202)
    def correction(sid: str, body: CorrectionRequest, request: Request):
        session(request, sid, True)
        e = store.get_artifact(sid, body.evidence_id, "evidence")
        if e["context_id"] != body.context_id:
            raise DemoError("stale_context")
        p = dict(
            key=body.key,
            kind="human_correction",
            statement=body.statement,
            citations=[e["citation"]],
            supersedes=body.supersedes,
        )
        return store.enqueue(
            sid,
            request.state.actor.subject,
            dict(
                action="propose",
                expected_revision=body.expected_revision,
                idempotency_key=body.idempotency_key,
                payload=dict(context_id=body.context_id, proposal=p),
            ),
        )

    @app.post("/api/demo/sessions/{sid}/reset", status_code=201)
    def reset(sid: str, body: ResetRequest, request: Request):
        s = session(request, sid, True)
        actor = request.state.actor.subject
        if s["pending_job_id"]:
            raise DemoError("session_busy")
        encoded = canonical(body.model_dump())
        with locked(settings.state_root / "workload.lock"):
            with store.transaction() as c:
                prior = c.execute(
                    "SELECT body,target FROM resets WHERE session=? AND actor=? AND key=?",
                    (sid, actor, body.idempotency_key),
                ).fetchone()
                if prior:
                    if prior["body"] != encoded:
                        raise DemoError("idempotency_conflict")
                    new = store.session_in(c, prior["target"])
                else:
                    s = store.session_in(c, sid)
                    if s["pending_job_id"]:
                        raise DemoError("session_busy")
                    if s["revision"] != body.expected_revision or s["closed"]:
                        raise DemoError("revision_conflict")
                    runtime = observe(settings.runtime_registry_path)
                    if runtime["state"] == "UNKNOWN":
                        raise DemoError("runtime_unknown")
                    if runtime["state"] != "STOPPED":
                        raise DemoError("operator_stop_required")
                    target = str(uuid.uuid4())
                    new = store.create(
                        target, actor, snapshots.create(target), connection=c
                    )
                    s["closed"] = True
                    store.put_session(c, s)
                    c.execute(
                        "INSERT INTO resets VALUES(?,?,?,?,?)",
                        (sid, actor, body.idempotency_key, encoded, target),
                    )
        return decorate(new)

    app.mount("/assets", StaticFiles(directory=WEB), name="assets")
    return app
