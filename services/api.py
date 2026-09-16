from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from datamesh_release_protocol import __version__
from datamesh_release_protocol.engine import ReleaseEngine
from datamesh_release_protocol.loaders import load_baseline_policy
from datamesh_release_protocol.models import ReleaseDecision, Scenario, ValidationMode

app = FastAPI(title="Domain Release Check", version=__version__)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
engine = ReleaseEngine(
    load_baseline_policy(PROJECT_ROOT / "policies" / "v1-ind.yaml")
)


@app.post("/release-check", response_model=ReleaseDecision)
def release_check(scenario: Scenario, mode: ValidationMode, run_id: str) -> ReleaseDecision:
    return engine.run(scenario, mode, run_id)
