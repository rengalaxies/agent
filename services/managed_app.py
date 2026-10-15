"""Single-port managed hosting adapter; uses the existing demo engine and audit.

Credentials are supplied by the hosting environment, never in the repository.
Readiness requires PostgreSQL; a missing DB cannot silently become a successful demo.
"""
import base64
import binascii
import hashlib
import hmac
import os
from pathlib import Path

from fastapi.responses import FileResponse, Response
from services.demo_api import app, healthz

USERNAME = os.environ["DMRP_UI_USERNAME"]
PASSWORD_SHA256 = os.environ["DMRP_UI_PASSWORD_SHA256"]
if not USERNAME or len(PASSWORD_SHA256) != 64:
    raise RuntimeError("Managed hosting authentication is not configured")
bytes.fromhex(PASSWORD_SHA256)
if os.environ.get("DMRP_REQUIRE_AUDIT") != "1":
    raise RuntimeError("Managed hosting requires PostgreSQL audit")


@app.middleware("http")
async def authenticate(request, call_next):
    if request.url.path != "/healthz":
        valid = False
        header = request.headers.get("authorization", "")
        try:
            scheme, encoded = header.split(" ", 1)
            if scheme.lower() == "basic":
                username, password = base64.b64decode(encoded, validate=True).decode("utf-8").split(":", 1)
                valid = hmac.compare_digest(username.encode(), USERNAME.encode()) & hmac.compare_digest(
                    hashlib.sha256(password.encode()).hexdigest(), PASSWORD_SHA256
                )
        except (ValueError, UnicodeError, binascii.Error):
            pass
        if not valid:
            return Response(status_code=401, headers={"WWW-Authenticate": 'Basic realm="Data Mesh", charset="UTF-8"'})
    if request.url.path.startswith("/api/") and request.method == "POST":
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 8192:
                return Response(status_code=413)
        request._body = bytes(body)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(Path(__file__).resolve().parents[1] / "ui" / "index.html")


@app.get("/api/healthz", include_in_schema=False)
def api_health():
    return healthz()
