"""Separate internal lab API. Demo roles are operator declarations, not IAM."""
from contextlib import asynccontextmanager
import os
import subprocess
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from lab.runtime.core import Stop
from .store import Store
from .worker import Worker


def create_app(db_path=None,artifact_root=None,start_worker=True,**worker_options):
    db_path=Path(db_path or os.environ.get('LAB_PRODUCT_DB','/tmp/lab-product/state.sqlite'))
    db_path.parent.mkdir(parents=True,exist_ok=True)
    store=Store(db_path);worker=Worker(store,artifact_root or db_path.parent/'artifacts',**worker_options)
    @asynccontextmanager
    async def lifespan(app):
        if start_worker:worker.start()
        yield
        worker.close()
    app=FastAPI(title='Internal lab workflow - demo roles',lifespan=lifespan)
    app.state.store=store;app.state.worker=worker
    def guarded(fn,payload):
        try:return fn(payload)
        except (Stop,KeyError,TypeError,ValueError) as exc:raise HTTPException(409,detail=str(exc)) from None
    @app.get('/api/lab/healthz')
    def health():return {'ready':True,'execution_permission':False,'demo_roles':True}
    @app.get('/api/lab/state')
    def state():
        data=store.state()
        try:data['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=worker.root,text=True,timeout=5).strip()
        except Exception:data['source_commit']='UNKNOWN'
        for candidate in data['candidates']:candidate.pop('candidate_path',None)
        return data
    @app.get('/api/lab/examples')
    def examples():
        historical=json.loads((worker.root/'lab/reports/agent-ci-39066354050/agent-evidence/input.json').read_text())
        return {'breaking':historical,'safe':{'intent':'Documentation clarification only','proposed_diff':'--- a/docs/note.md\n+++ b/docs/note.md\n-old\n+clarified\n','proposed_files':{'docs/note.md':'clarified\n'},'kind':'safe'}}
    @app.post('/api/lab/changes')
    def changes(payload:dict):
        try:actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=worker.root,text=True,timeout=5).strip()
        except Exception:raise HTTPException(409,detail='Current repository commit unavailable') from None
        if payload.get('source_commit')!=actual:raise HTTPException(409,detail='Supported source is the exact current repository commit')
        return guarded(store.create_change,payload)
    @app.post('/api/lab/jobs',status_code=202)
    def jobs(payload:dict):return guarded(store.enqueue,payload)
    @app.post('/api/lab/decisions')
    def decisions(payload:dict):return guarded(store.decide,payload)
    @app.post('/api/lab/apply')
    def apply():raise HTTPException(403,detail='BLOCKED: execution criteria and fresh exact authority not satisfied; team acknowledgement is not a grant')
    ui=Path(__file__).parent/'ui'
    if ui.exists():
        app.mount('/ui',StaticFiles(directory=ui),name='ui')
        @app.get('/')
        def index():return FileResponse(ui/'index.html')
    return app

app=create_app()
