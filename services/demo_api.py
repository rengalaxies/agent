"""Explicitly non-production development demo of the existing deterministic V2 engine.

Only scenarios/development are served. Evaluation scenarios and oracles are never loaded.
"""
from __future__ import annotations
from pathlib import Path
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
