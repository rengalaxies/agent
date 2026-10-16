"""Loopback-only launcher for the existing synthetic research demonstration.

This is not the migration product or a production deployment. No client
credentials or live systems are connected by this launcher.
"""
from pathlib import Path

from fastapi.staticfiles import StaticFiles

from services.demo_api import app, healthz

# Match the UI's existing same-origin health path without an nginx dependency.
app.add_api_route("/api/healthz", healthz, methods=["GET"], include_in_schema=False)
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parents[1] / "ui", html=True), name="research-ui")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8080)
