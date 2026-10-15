"""Explicitly non-production development demo of the existing deterministic V2 engine.

Only scenarios/development are served. Evaluation scenarios and oracles are never loaded.
"""
from __future__ import annotations
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import BoundedSemaphore
import subprocess
import sys
import json
import os
import signal
from typing import Literal
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datamesh_release_protocol import __version__
from datamesh_release_protocol.engine import ReleaseEngine
from datamesh_release_protocol.loaders import load_baseline_policy, load_catalog
from datamesh_release_protocol.models import ValidationMode
from services.knowledge_demo import development_knowledge_map
from services.audit_sink import AuditUnavailable, audit_record, audit_ready, BACKEND

ROOT=Path(__file__).resolve().parents[1]
CATALOG={s.scenario_id:s for s in load_catalog(ROOT/"scenarios"/"development")}
ENGINE=ReleaseEngine(load_baseline_policy(ROOT/"policies"/"v1-ind.yaml"))
app=FastAPI(title="Data Mesh development demo API", version=__version__)
E4_RUN_SLOT=BoundedSemaphore(value=1)  # Do not spawn unbounded domain processes.

class RunRequest(BaseModel):
    scenario_id:str

@app.get("/healthz")
def healthz():
    db_ok=audit_ready()
    if not db_ok:
        raise HTTPException(status_code=503, detail="Required audit persistence unavailable")
    return {"ok": db_ok, "api_ready": db_ok, "engine_live": True,
            "audit_ready": db_ok, "audit_backend": BACKEND,
            "postgres_audit_ready": db_ok if BACKEND == "postgres" else False, "purpose": "development_demo",
            "evaluation_oracle_loaded": False}

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
    body=decision.model_dump(mode="json")
    try:
        audit=audit_record(run_id, s.scenario_id, body)
    except AuditUnavailable:
        raise HTTPException(status_code=503, detail="Required audit persistence unavailable")
    return {"mode": "V2", "dataset":"development", "run_id":run_id,
            "scenario_id":s.scenario_id,"decision":body,"audit":audit,
            "disclaimer":"Actual V2 engine output on public development scenarios; not confirmatory E3 evidence"}


class DistributedRunRequest(BaseModel):
    outcome: Literal["ACCEPT", "REJECT", "NEEDS_REVIEW"]


@app.post("/api/v1/demo/distributed-runs")
def distributed_run(payload: DistributedRunRequest):
    """Run a true three-process synthetic E4 sample, not an E3 scored evaluation.

    Each request uses a fresh isolated, non-persistent state directory and three
    independent domain worker processes from the existing experimental stand.
    """
    if not E4_RUN_SLOT.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="Distributed demonstration already running")
    run_id="e4demo-"+uuid4().hex
    try:
        with TemporaryDirectory(prefix="e4-service-") as temp:
            try:
                process=subprocess.Popen(
                    [sys.executable, str(ROOT/"stand"/"demo.py"), "--state",temp,
                     "--run-id",run_id, "--outcome",payload.outcome],
                    cwd=ROOT, text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    start_new_session=True,
                )
                try:
                    stdout, _ = process.communicate(timeout=55)
                except subprocess.TimeoutExpired:
                    # The coordinator owns three worker children. Killing only
                    # the coordinator leaves them alive beyond the concurrency slot.
                    os.killpg(process.pid, signal.SIGKILL)
                    process.communicate()
                    raise
                if process.returncode:
                    raise subprocess.CalledProcessError(process.returncode, process.args)
                protocol=json.loads(stdout)
            except (subprocess.TimeoutExpired,subprocess.CalledProcessError,ValueError):
                # Never disclose internal paths, signing keys or process stderr.
                raise HTTPException(status_code=503, detail="E4 demo run unavailable")
    finally:
        E4_RUN_SLOT.release()
    return {
        "mode":"V2", "dataset":"synthetic_E4",
        "architecture":"three_independent_domain_processes",
        "evaluation_oracle_loaded":False,
        "run_id":run_id, "requested_outcome":payload.outcome,
        "release":protocol,
        "disclaimer":"Distributed engineering demonstration, not confirmatory E3 evidence",
    }


@app.get("/api/v1/knowledge/map")
def knowledge_map():
    """Confirmed E4 synthetic knowledge-1 consumers, without private/oracle data."""
    return development_knowledge_map()
