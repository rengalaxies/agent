"""Temporary A6.3 author-fixture stand. No real connector, worker or production DB.

Run from repo with PYTHONPATH=src:.:tests:tools; credentials stay in ignored mode0600
work/a6-3/private/credentials.json and are deleted on shutdown. Idle profile is QA-only.
"""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import secrets
import tempfile
from types import SimpleNamespace
import uvicorn
from agent_graph.contracts import Policy
from agent_service.api import create_app
from agent_service.envelope import canonical,digest
from agent_service.queue import ServiceStore
from agent_service import ui_auth
from agent_service.ui_auth import AuthStore,UISettings
from agent_service.ui_scope import scope_for_service
from tests.graph.test_output_contracts import request,result

ROOT=Path(__file__).resolve().parents[4]


def namespace(value):
    if isinstance(value,list):return [namespace(v) for v in value]
    if not isinstance(value,dict):return value
    return {k:'author-fixture' if k=='installation_id' else 'qa' if k=='environment' else namespace(v) for k,v in value.items()}


def seed(store,scope):
    def run(rid,raw=None,version='v1',state='ANALYZED'):
        jira=rid.startswith('jira:')
        store.apply_snapshot(resource_id=rid,provider='jira' if jira else 'bitbucket',kind='issue' if jira else 'pr',version=version,
            snapshot={'secret':'NEVER_SHOW_SNAPSHOT'},event_id='author',closed=False)
        job=store.claim_job('author');req=namespace(request());req.update(scope.receipt())
        if raw is not None:
            req['request_id']=raw.get('request_id','req-1');req['source_event']={'event_id':raw.get('event_id','delivery-9'),'resource_version':raw.get('resource_version','2'*40)}
            req['trigger_kind']=raw.get('trigger_kind','pr')
            if req['trigger_kind']=='jira':
                req.pop('pr',None)
                req['jira']={'project':'KAN','key':'KAN-10','revision':'author','updated_at':'2026-11-16T00:00:00Z','text_fields':{}}
        store.stamp_ui_scope(job,req)
        if state=='RUNNING':return
        store.complete_job(job,state=state,result=raw,reason=raw.get('reason_code') if raw else 'commit_unavailable',
            intent={'kind':'result','result_digest':digest(raw),'body':canonical({'secret':'NEVER_SHOW_DOCUMENT'}),
                    'body_digest':digest({'secret':'NEVER_SHOW_DOCUMENT'}),'marker':'author'} if raw else None)
    raw=namespace(result(summary='Reporting читает одну страницу Orders; размер страницы уменьшен со 100 до 20.'))
    raw['claims'][0]['statement']='Reporting вызывает GET /orders без явного размера страницы.'
    raw['checks'][0]['text']='Проверьте выгрузку более 20 заказов и сравните с полным набором.'
    run('bitbucket:author/orders#5',deepcopy(raw))
    run('bitbucket:author/orders#4',deepcopy(raw));run('bitbucket:author/orders#4',None,'v2','FAILED')
    partial=deepcopy(raw);partial.update(status='PARTIAL',reason_code='coverage_gaps',
        gaps=[dict(code='source_unavailable',repository='reporting',path='client.py')])
    run('bitbucket:author/orders#3',partial)
    with store._connect() as c:c.execute("UPDATE intents SET state='UNKNOWN' WHERE resource_id='bitbucket:author/orders#3'")
    run('bitbucket:author/orders#2',deepcopy(raw))
    with store._connect() as c:c.execute("UPDATE resources SET closed=1 WHERE resource_id='bitbucket:author/orders#2'")
    run('bitbucket:author/orders#1',None,state='FAILED')
    run('bitbucket:author/orders#6',{'schema_version':'alien','reason_code':'invalid','secret':'NEVER_SHOW_RAW'})
    with store._connect() as c:c.execute("UPDATE jobs SET state='FUTURE_JOB' WHERE resource_id='bitbucket:author/orders#6'")
    # Real CoreAnalyzer output saved during A6.0 audit; use same read path, no invented quote.
    actual=namespace(json.loads((ROOT/'docs/product/ui-admin-2026-11-16/fixture-result.json').read_text())['analysis']['raw'])
    run('jira:author/KAN-10',actual)
    run('bitbucket:author/orders#7',None,state='RUNNING')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--idle',type=int,default=1200);args=parser.parse_args()
    ui_auth.IDLE_SECONDS=args.idle
    private=ROOT/'work/a6-3/private';private.mkdir(parents=True,exist_ok=True,mode=0o700)
    credentials=private/'credentials.json'
    with tempfile.TemporaryDirectory(prefix='impactmap-a6-3-') as tmp:
        tmp=Path(tmp)
        repos=['orders','reporting','archive','billing','audit']
        policy=Policy.model_validate(dict(installation_id='author-fixture',environment='qa',subject='author',capabilities=['read_context'],
            repositories=[dict(id=x,service=x,root=str(tmp/'repos'/x),revision='main') for x in repos],addresses=[]))
        store=ServiceStore(tmp/'service.sqlite')
        service=SimpleNamespace(store=store,installation_id='author-fixture',environment='qa',analyzer=SimpleNamespace(policy=policy,runtime_sources=[]))
        settings=UISettings(tmp/'auth.sqlite','http://127.0.0.1:18089',True)
        auth=AuthStore(settings.database);scope=scope_for_service(service)
        password=secrets.token_urlsafe(24)
        for user,role in [('qa-reader','reviewer'),('qa-owner','operator')]:auth.create_user(user,password,role,scope.identity)
        seed(store,scope)
        fd=os.open(credentials,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as f:json.dump({'username':'qa-reader','password':password},f)
        def db_digest():
            with store._connect() as c:return hashlib.sha256('\n'.join(c.iterdump()).encode()).hexdigest()
        before=db_digest()
        app=create_app(service,status_token='NEVER_SEND_SERVICE_TOKEN',ui_settings=settings,ui_auth=auth)
        @app.middleware('http')
        async def trace(req,call_next):
            response=await call_next(req)
            if req.url.path.startswith('/ui/'):
                with (private/'http-statuses.jsonl').open('a') as f:f.write(json.dumps({'method':req.method,'path':req.url.path,'status':response.status_code})+'\n')
            return response
        print('Author fixture results stand:127.0.0.1:18089; no external providers; idle='+str(args.idle),flush=True)
        try:uvicorn.run(app,host='127.0.0.1',port=18089,access_log=False,proxy_headers=False)
        finally:
            credentials.unlink(missing_ok=True)
            (private/'read-only-check.json').write_text(json.dumps({'before':before,'after':db_digest(),'unchanged':before==db_digest()},indent=2)+'\n')


if __name__=='__main__':main()
