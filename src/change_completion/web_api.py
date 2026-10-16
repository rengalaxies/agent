"""Private product UI/API. All data routes require deployment bearer identities."""
import asyncio
import base64
from contextlib import asynccontextmanager
from hashlib import sha256
from pathlib import Path
import re
import secrets
import sqlite3
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import Field, StrictBool

from .models import Contract


class ReviewBody(Contract):
    decision: Literal["approve", "reject"]
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    comment: str = Field(default="", max_length=4000)


class DeliveryBody(Contract):
    kind: Literal["pr", "notification"]
    send: StrictBool = False


class ReopenBody(Contract):
    package_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


class BoundedRequests:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        from fastapi.responses import JSONResponse
        events, total = [], 0
        deadline = asyncio.get_running_loop().time() + 10
        try:
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise TimeoutError
                message = await asyncio.wait_for(receive(), timeout=remaining)
                if message["type"] == "http.disconnect":
                    return
                total += len(message.get("body", b""))
                if total > 16_384:
                    return await JSONResponse({"detail": "body limit"}, status_code=413)(scope, receive, send)
                events.append(message)
                if not message.get("more_body", False):
                    break
        except TimeoutError:
            return await JSONResponse({"detail": "body timeout"}, status_code=408)(scope, receive, send)
        async def replay():
            return events.pop(0) if events else await receive()
        return await self.app(scope, replay, send)


def create_product_app(service, identities, *, tick_seconds=5):
    if not identities or any(not token or len(token) < 16 for token in identities):
        raise ValueError("deployment identities require nonempty strong bearer tokens")
    if type(tick_seconds) not in (int, float) or not 0.1 <= tick_seconds <= 3600:
        raise ValueError("invalid timer interval")
    tokens = dict(identities)

    async def timer():
        while True:
            try:
                await asyncio.to_thread(service.tick)
            except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error):
                pass  # Every read/action also validates fresh state and fails closed.
            await asyncio.sleep(tick_seconds)

    @asynccontextmanager
    async def lifespan(app):
        task = asyncio.create_task(timer())
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app = FastAPI(title="Модуль межсистемных изменений", lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(BoundedRequests)
    html = Path(__file__).with_name("web").joinpath("index.html").read_text()
    script_hashes = ["'sha256-"+base64.b64encode(sha256(script.encode()).digest()).decode()+"'"
                     for script in re.findall(r"<script>(.*?)</script>", html, re.S)]
    csp = "default-src 'self'; script-src " + " ".join(script_hashes) + "; style-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"

    @app.middleware("http")
    async def secure_response(request: Request, call_next):
        # No permissive CORS; requests carrying credentials from another Origin are denied.
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": "cross-origin request denied"}, status_code=403)
        if request.method == "POST":
            raw_length = request.headers.get("content-length", "0")
            if not raw_length.isdigit() or int(raw_length) > 16_384 or request.headers.get("transfer-encoding"):
                from fastapi.responses import JSONResponse
                return JSONResponse({"detail": "body limit"}, status_code=413)
        response = await call_next(request)
        response.headers.update({"Cache-Control": "no-store", "Content-Security-Policy": csp,
                                 "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                                 "X-Frame-Options": "DENY"})
        return response

    def identity(authorization: str | None = Header(default=None)):
        value = authorization[7:] if authorization and authorization.startswith("Bearer ") else ""
        for token, principal in tokens.items():
            if secrets.compare_digest(token, value):
                return principal
        raise HTTPException(401, "deployment identity required")

    def invoke(fn):
        try:
            return fn()
        except PermissionError:
            raise HTTPException(403, "project role or current authority required") from None
        except KeyError:
            raise HTTPException(404, "run not available") from None
        except ValueError:
            raise HTTPException(409, "package, role or delivery state does not permit action") from None
        except (OSError, RuntimeError, sqlite3.Error):
            raise HTTPException(503, "installation state unavailable") from None

    @app.get("/", response_class=HTMLResponse)
    def index():
        return html  # Public shell contains no run data or credentials.

    @app.get("/api/runs")
    def runs(principal=Depends(identity)):
        return invoke(lambda: service.list_runs(principal))

    @app.get("/api/runs/{run_id}")
    def run(run_id: str, principal=Depends(identity)):
        return invoke(lambda: service.view(run_id, principal))

    @app.post("/api/runs/{run_id}/review")
    def review(run_id: str, body: ReviewBody, principal=Depends(identity)):
        return invoke(lambda: service.review(run_id, principal, body.decision, body.package_digest, body.comment))

    @app.post("/api/runs/{run_id}/deliver")
    def deliver(run_id: str, body: DeliveryBody, principal=Depends(identity)):
        return invoke(lambda: service.deliver(run_id, principal, body.kind, send=body.send))

    @app.post("/api/runs/{run_id}/revalidate")
    def reopen(run_id: str, body: ReopenBody, principal=Depends(identity)):
        return invoke(lambda: service.reopen(run_id, principal, body.package_digest))

    @app.post("/api/tick")
    def tick(principal=Depends(identity)):
        if "tick" not in principal.permissions:
            raise HTTPException(403, "timer operator role required")
        return invoke(service.tick)

    return app
