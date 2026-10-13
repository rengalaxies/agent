"""Explicitly non-production development demo of the existing deterministic V2 engine.

Only scenarios/development are served. Evaluation scenarios and oracles are never loaded.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
import subprocess
import sys
import json
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datamesh_release_protocol import __version__
from datamesh_release_protocol.engine import ReleaseEngine
from datamesh_release_protocol.loaders import load_baseline_policy, load_catalog
from datamesh_release_protocol.models import ValidationMode

ROOT=Path(__file__).resolve().parents[1]
CATALOG={s.scenario_id:s for s in load_catalog(ROOT/"scenarios"/"development")}
ENGINE=ReleaseEngine(load_baseline_policy(ROOT/"policies"/"v1-ind.yaml"))
app=FastAPI(title="Data Mesh development demo API", version=__version__)

class RunRequest(BaseModel):
    scenario_id:str

@app.get("/healthz")
def healthz():
    return {"ok": True, "engine_live": True, "purpose": "development_demo", "evaluation_oracle_loaded": False}

@app.get("/api/v1/demo/scenarios")
def scenarios():
    return {"mode": "V2", "dataset": "development", "evaluation_oracle_loaded": False,
            "scenarios":[{"id":s.scenario_id,"title":s.description,"family":s.family_id}
                         for s in CATALOG.values()]}

@app.post("/api/v1/demo/runs")
def run(payload: RunRequest):
    s=CATALOG.get(payload.scenario_id)
    if s is None: raise HTTPException(status_code=404,detail="Unknown development scenario")
    run_id="demo-"+uuid4().hex
    decision=ENGINE.run(s,ValidationMode.V2,run_id=run_id)
    return {"mode": "V2", "dataset":"development", "run_id":run_id,
            "scenario_id":s.scenario_id,"decision":decision.model_dump(mode="json"),
            "disclaimer":"Actual V2 engine output on public development scenarios; not confirmatory E3 evidence"}


class DistributedRunRequest(BaseModel):
    outcome: Literal["ACCEPT", "REJECT", "NEEDS_REVIEW"]


@app.post("/api/v1/demo/distributed-runs")
def distributed_run(payload: DistributedRunRequest):
    """Run a true three-process synthetic E4 sample, not an E3 scored evaluation.

    Each request uses a fresh isolated, non-persistent state directory and three
    independent domain worker processes from the existing experimental stand.
    """
    run_id="e4demo-"+uuid4().hex
    with TemporaryDirectory(prefix="e4-service-") as temp:
        try:
            result=subprocess.run(
                [sys.executable, str(ROOT/"stand"/"demo.py"), "--state",temp,
                 "--run-id",run_id, "--outcome",payload.outcome],
                cwd=ROOT, text=True,capture_output=True,timeout=55,check=True,
            )
            protocol=json.loads(result.stdout)
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError,ValueError):
            # The public demo API must not disclose child process stderr or
            # internal paths, keys, node tokens or signing identities.
            raise HTTPException(status_code=503, detail="E4 demo run unavailable")
    return {
        "mode":"V2", "dataset":"synthetic_E4",
        "architecture":"three_independent_domain_processes",
        "evaluation_oracle_loaded":False,
        "run_id":run_id, "requested_outcome":payload.outcome,
        "release":protocol,
        "disclaimer":"Distributed engineering demonstration, not confirmatory E3 evidence",
    }
