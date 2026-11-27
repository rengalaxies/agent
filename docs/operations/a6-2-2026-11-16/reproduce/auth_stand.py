"""Isolated A6.2 browser stand; temporary accounts and short idle expiry for QA only."""
from pathlib import Path
import json,os,secrets,tempfile,time
from types import SimpleNamespace
import uvicorn
from agent_graph.contracts import Policy
from agent_service import ui_auth
from agent_service.ui_auth import AuthStore,UISettings
from agent_service.ui_scope import scope_for_service
from agent_service.queue import ServiceStore
from agent_service.api import create_app
from agent_service.envelope import canonical,digest
from tests.graph.test_output_contracts import request,result

ui_auth.IDLE_SECONDS=60 # Explicit browser-QA profile, never a deployment setting.
root=Path(__file__).resolve().parents[4]
with tempfile.TemporaryDirectory(prefix='impactmap-ui-access-') as tmp:
    tmp=Path(tmp)
    policy=Policy.model_validate(dict(installation_id='author-fixture',environment='qa',subject='author',
        capabilities=['read_context'],repositories=[dict(id=x,service=x,root=str(tmp/'repos'/x),revision='main') for x in ('orders','reporting')],addresses=[]))
    store=ServiceStore(tmp/'service.sqlite')
    service=SimpleNamespace(store=store,installation_id='author-fixture',environment='qa',analyzer=SimpleNamespace(policy=policy,runtime_sources=[]))
    settings=UISettings(tmp/'auth.sqlite','http://127.0.0.1:18088',True)
    auth=AuthStore(settings.database);scope=scope_for_service(service)
    password=secrets.token_urlsafe(24)
    for username,role in [('qa-reader','reviewer'),('qa-owner','operator')]:auth.create_user(username,password,role,scope.identity)
    secret=root/'work/a6-2/private/browser-credentials.json'
    secret.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(secret,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
    with os.fdopen(fd,'w') as f:json.dump(dict(username='qa-reader',password=password),f)
    app=create_app(service,status_token='never-sent-to-browser',ui_settings=settings,ui_auth=auth)
    @app.middleware('http')
    async def trace(request,call_next):
        response=await call_next(request)
        if request.url.path.startswith('/ui/api/'):
            path=root/'work/a6-2/private/http-statuses.jsonl'
            with path.open('a') as f:f.write(json.dumps({'method':request.method,'path':request.url.path,'status':response.status_code})+'\n')
        return response
    print('Author-only auth stand: loopback18088; idle60s; users are temporary',flush=True)
    try:uvicorn.run(app,host='127.0.0.1',port=18088,access_log=False,proxy_headers=False)
    finally:secret.unlink(missing_ok=True)
