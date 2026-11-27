"""Webhook receiver. It verifies and records deliveries; all work happens in the worker."""

from __future__ import annotations

import hmac

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse, JSONResponse

from .connectors.base import MAX_WEBHOOK_BYTES


def create_app(service, *, status_token: str | None = None, ui_settings=None, ui_auth=None) -> FastAPI:
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

    def authorized(request: Request) -> bool:
        supplied = request.headers.get("authorization", "")
        return bool(status_token) and hmac.compare_digest(supplied.encode('utf-8'), f"Bearer {status_token}".encode('utf-8'))

    def diagnostic_response(payload,status=200):
        return JSONResponse(payload,status_code=status,headers={
            'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer'})

    @app.get('/resources')
    async def resources(request: Request):
        if not authorized(request):return diagnostic_response({'error':'unauthorized'},401)
        value=request.query_params.get('limit','50')
        if not value.isascii() or not value.isdigit() or len(value)>3 or not 1<=int(value)<=100:
            return diagnostic_response({'error':'invalid_limit'},400)
        return diagnostic_response(await run_in_threadpool(service.store.resource_listing,int(value)))

    @app.get('/result')
    async def result(request: Request):
        if not authorized(request):return diagnostic_response({'error':'unauthorized'},401)
        resource_id=request.query_params.get('resource_id','')
        if not 1<=len(resource_id)<=512:return diagnostic_response({'error':'invalid_resource_id'},400)
        payload=await run_in_threadpool(service.store.resource_diagnostics,resource_id)
        return diagnostic_response(payload if payload is not None else {'error':'resource_not_found'},200 if payload is not None else 404)

    @app.get("/status")
    async def status(request: Request):
        if not authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await run_in_threadpool(service.store.status)

    @app.get("/graph")
    async def graph(request: Request):
        """Read-only batch 3 view: impact paths, provenance and freshness, within the analysis grants."""
        if not authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        render = getattr(service.analyzer, "graph_html", None)
        if render is None:
            return JSONResponse({"error": "graph_not_configured"}, status_code=404)
        body = await run_in_threadpool(render)
        return HTMLResponse(body, headers={
            "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'"})

    if ui_settings is not None:
        from .ui_api import mount_ui
        mount_ui(app,service,ui_settings,ui_auth)
    return app
