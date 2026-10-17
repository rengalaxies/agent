"""Separate internal lab API. Demo roles are operator declarations, not IAM."""
from contextlib import asynccontextmanager
import os
import subprocess
import json
import base64
import secrets
import threading
import uuid
from pathlib import Path
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from lab.runtime.core import Stop
from .store import Store, MODES
from .worker import Worker
from .sessions import Sessions, SCENARIOS, CONSENT_NOTICE, CONSENT_VERSION, session_options


def create_app(db_path=None,artifact_root=None,start_worker=True,**worker_options):
    db_path=Path(db_path or os.environ.get('LAB_PRODUCT_DB','/tmp/lab-product/state.sqlite'))
    db_path.parent.mkdir(parents=True,exist_ok=True)
    store=Store(db_path);worker=Worker(store,artifact_root or db_path.parent/'artifacts',**worker_options)
    sessions=Sessions(db_path.parent/'interview-sessions');session_workers={};workspace_lock=threading.RLock();interview_mode={'enabled':False}
    @asynccontextmanager
    async def lifespan(app):
        if start_worker and os.environ.get('LAB_REQUIRE_AUTH','').lower() not in ('1','true','yes'):worker.start()
        yield
        worker.close()
        for active_worker in session_workers.values():active_worker.close()
    app=FastAPI(title='Internal lab workflow - demo roles',lifespan=lifespan)
    app.state.store=store;app.state.worker=worker;app.state.sessions=sessions
    @app.middleware('http')
    async def protect(request,call_next):
        # Optional server-side boundary covers UI, exports and every API route.
        if os.environ.get('LAB_REQUIRE_AUTH','').lower() in ('1','true','yes'):
            username=os.environ.get('LAB_AUTH_USERNAME','');password=os.environ.get('LAB_AUTH_PASSWORD','')
            valid=False
            try:
                scheme,encoded=request.headers.get('authorization','').split(' ',1)
                supplied_user,supplied_password=base64.b64decode(encoded,validate=True).decode().split(':',1)
                valid=bool(username and password and scheme.lower()=='basic' and secrets.compare_digest(supplied_user,username) and secrets.compare_digest(supplied_password,password))
            except (ValueError,UnicodeError):pass
            if not valid:return JSONResponse({'detail':'Protected lab: authentication required'},status_code=401,headers={'WWW-Authenticate':'Basic realm="Internal lab", charset="UTF-8"'})
        if request.method not in ('GET','HEAD','OPTIONS'):
            origin=request.headers.get('origin')
            if request.headers.get('sec-fetch-site')=='cross-site' or (origin and origin!=str(request.base_url).rstrip('/')):
                return JSONResponse({'detail':'Cross-origin mutation denied'},status_code=403)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store'
        response.headers['Referrer-Policy']='no-referrer'
        return response
    def sid(request):return request.headers.get('x-lab-session') or request.cookies.get('lab_session')
    def stop_other_workers(selected=None):
        with workspace_lock:
            for key,active_worker in list(session_workers.items()):
                if key[0]==selected:continue
                if any(j['status'] in ('QUEUED','RUNNING') for j in active_worker.store.rows('jobs')):raise Stop('Finish or reconcile current session work before switching sessions')
            for key in list(session_workers):
                if key[0]!=selected:session_workers.pop(key).close()
    def context(request):
        selected=sid(request)
        if not selected:
            if interview_mode['enabled'] or os.environ.get('LAB_REQUIRE_AUTH','').lower() in ('1','true','yes'):raise HTTPException(409,detail='Select an isolated interview session first')
            return store,worker
        try:
            with workspace_lock:
                stop_other_workers(selected)
                active=sessions.workspace(selected);row=sessions.get(selected);key=(selected,row['generation'])
                if key not in session_workers:
                    _,artifacts=sessions.paths(selected)
                    options=session_options(sessions,selected,worker_options)
                    session_workers[key]=Worker(active,artifacts,**options)
                    if start_worker:session_workers[key].start()
                return active,session_workers[key]
        except Stop as exc:raise HTTPException(409,detail=str(exc)) from None
    def selected_session(request):
        selected=sid(request)
        if not selected:raise HTTPException(409,detail='Select an interview session first')
        return selected
    @app.get('/api/lab/sessions/current')
    def current_session(request:Request):
        selected=sid(request)
        return guarded(lambda _: {'session':sessions.get(selected) if selected else None,'scenario':sessions.scenario(selected) if selected else None,'scenarios':SCENARIOS,'consent_notice':CONSENT_NOTICE,'consent_version':CONSENT_VERSION},None)
    @app.post('/api/lab/sessions')
    def create_session(payload:dict,response:Response):
        def create(p):
            with workspace_lock:
                if p.get('scenario') not in SCENARIOS or p.get('mode','REPLAY') not in MODES:raise Stop('Unknown scenario or mode')
                if any(j['status'] in ('QUEUED','RUNNING') for j in store.rows('jobs')):raise Stop('Finish or reconcile legacy lab work before starting interview')
                stop_other_workers()
                worker.close()
                interview_mode['enabled']=True
                return sessions.create(p['scenario'],p.get('mode','REPLAY'))
        row=guarded(create,payload)
        response.set_cookie('lab_session',row['session_id'],httponly=True,samesite='strict',secure=os.environ.get('LAB_COOKIE_SECURE','').lower() in ('1','true','yes'))
        return row
    @app.post('/api/lab/sessions/consent')
    def session_consent(request:Request,payload:dict):return guarded(lambda p:sessions.consent(selected_session(request),p['enabled'],p['notice_version']),payload)
    @app.get('/api/lab/sessions/export')
    def session_export(request:Request):return guarded(lambda _:sessions.export(selected_session(request)),None)
    @app.post('/api/lab/sessions/delete-research')
    def session_delete(request:Request):return guarded(lambda _:sessions.delete_research(selected_session(request)),None)
    @app.post('/api/lab/sessions/help')
    def session_help(request:Request,payload:dict):return guarded(lambda p:sessions.record(selected_session(request),uuid.uuid4().hex,'MODERATOR_HELP',help_category=p['category']),payload)
    @app.post('/api/lab/sessions/reset')
    def session_reset(request:Request):
        def reset(_):
            selected=selected_session(request)
            with workspace_lock:
                row=sessions.reset(selected)
                for key in list(session_workers):
                    if key[0]==selected:session_workers.pop(key).close()
                return row
        return guarded(reset,None)
    @app.post('/api/lab/sessions/end')
    def session_end(request:Request):
        def end(_):
            selected=selected_session(request)
            if any(j['status'] in ('QUEUED','RUNNING') for j in sessions.workspace(selected).rows('jobs')):raise Stop('Stop/reconcile pending work before ending session')
            result=sessions.end(selected)
            for key in list(session_workers):
                if key[0]==selected:session_workers.pop(key).close()
            return result
        return guarded(end,None)
    def guarded(fn,payload):
        try:return fn(payload)
        except (Stop,KeyError,TypeError,ValueError) as exc:raise HTTPException(409,detail=str(exc)) from None
    @app.get('/api/lab/healthz')
    def health():return {'ready':True,'execution_permission':False,'demo_roles':True}
    @app.get('/api/lab/state')
    def state(request:Request):
        active,active_worker=context(request)
        if sid(request):sessions.sync_audit(sid(request))
        data=active.state()
        try:data['source_commit']=subprocess.check_output(['git','rev-parse','HEAD'],cwd=active_worker.root,text=True,timeout=5).strip()
        except Exception:data['source_commit']='UNKNOWN'
        for candidate in data['candidates']:candidate.pop('candidate_path',None)
        return data
    @app.get('/api/lab/examples')
    def examples():
        historical=json.loads((worker.root/'lab/reports/agent-ci-39066354050/agent-evidence/input.json').read_text())
        return {'breaking':historical,'safe':{'intent':'Documentation clarification only','proposed_diff':'--- a/docs/note.md\n+++ b/docs/note.md\n-old\n+clarified\n','proposed_files':{'docs/note.md':'clarified\n'},'kind':'safe'}}
    @app.post('/api/lab/changes')
    def changes(request:Request,payload:dict):
        active,active_worker=context(request)
        try:actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=active_worker.root,text=True,timeout=5).strip()
        except Exception:raise HTTPException(409,detail='Current repository commit unavailable') from None
        if payload.get('source_commit')!=actual:raise HTTPException(409,detail='Supported source is the exact current repository commit')
        return guarded(active.create_change,payload)
    @app.post('/api/lab/jobs',status_code=202)
    def jobs(request:Request,payload:dict):
        with workspace_lock:return guarded(context(request)[0].enqueue,payload)
    @app.post('/api/lab/decisions')
    def decisions(request:Request,payload:dict):return guarded(context(request)[0].decide,payload)
    @app.post('/api/lab/apply')
    def apply():raise HTTPException(403,detail='BLOCKED: execution criteria and fresh exact authority not satisfied; team acknowledgement is not a grant')
    ui=Path(__file__).parent/'ui'
    if ui.exists():
        app.mount('/ui',StaticFiles(directory=ui),name='ui')
        @app.get('/')
        def index():return FileResponse(ui/'index.html')
    return app

app=create_app()
