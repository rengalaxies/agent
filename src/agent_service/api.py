"""Webhook receiver. It verifies and records deliveries; all work happens in the worker."""

from __future__ import annotations

import hmac

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from .connectors.base import MAX_WEBHOOK_BYTES


def create_app(service, *, status_token: str | None = None) -> FastAPI:
    app = FastAPI(title="agent-service", docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/webhooks/{provider}")
    async def webhook(provider: str, request: Request):
        declared = request.headers.get("content-length")
        if declared and (not declared.isdigit() or int(declared) > MAX_WEBHOOK_BYTES):
            return JSONResponse({"error": "payload_too_large"}, status_code=413)
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > MAX_WEBHOOK_BYTES:
                return JSONResponse({"error": "payload_too_large"}, status_code=413)
        status, payload = await run_in_threadpool(service.receive, provider, dict(request.headers), bytes(body))
        return JSONResponse(payload, status_code=status)

    @app.get("/healthz")
    async def healthz():
        # Liveness only: says nothing about Jira/Git permissions or the analysis.
        return {"live": True}

    @app.get("/status")
    async def status(request: Request):
        supplied = request.headers.get("authorization", "")
        if not status_token or not hmac.compare_digest(supplied, f"Bearer {status_token}"):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await run_in_threadpool(service.store.status)

    return app
