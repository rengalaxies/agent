"""Local author-only operator QA. No connectors/worker; real auth/store/config metadata."""
import importlib.util,json,os,secrets,tempfile,hashlib,argparse
from pathlib import Path
from types import SimpleNamespace
import uvicorn
from starlette.responses import JSONResponse,Response
from agent_graph.contracts import Policy
from agent_service.service import Service
from agent_service.config import ServiceConfig
from agent_service.ui_operator import metadata_for_config
from agent_service.ui_scope import scope_for_service
from agent_service.ui_auth import AuthStore,UISettings
from agent_service.queue import ServiceStore
from agent_service.api import create_app
from agent_service.envelope import canonical,digest
from tests.graph.test_output_contracts import request,result
ROOT=Path(__file__).resolve().parents[4]
WORKSPACE='11111111-1111-4111-8111-111111111111'
REPO='22222222-2222-4222-8222-222222222222'
RID=f'bitbucket:{WORKSPACE}/{REPO}#5'

def main():
 p=argparse.ArgumentParser();p.add_argument('--fail-logout-first',action='store_true');args=p.parse_args()
 spec=importlib.util.spec_from_file_location('author_seed',ROOT/'docs/operations/a6-3-2026-11-16/reproduce/serve.py')
 seed=importlib.util.module_from_spec(spec);spec.loader.exec_module(seed)
 private=ROOT/'work/a6-4/private';private.mkdir(parents=True,exist_ok=True,mode=0o700)
 credentials=private/'credentials.json'
 with tempfile.TemporaryDirectory(prefix='impactmap-a6-4-') as tmp:
  tmp=Path(tmp)
  policy=Policy.model_validate(dict(installation_id='author-fixture',environment='qa',subject='author',capabilities=['read_context'],
    repositories=[dict(id=x,service=x,root=str(tmp/'repos'/x),revision='main') for x in ['orders','reporting','archive','billing','audit']],addresses=[]))
  store=ServiceStore(tmp/'service.sqlite')
  config=ServiceConfig.model_validate(dict(installation_id='author-fixture',environment='qa',state_path=str(store.path),publication='dry_run',
   bitbucket=dict(mode='kaiten_delivery',workspace='author',workspace_uuid=WORKSPACE,repositories={'orders':dict(uuid=REPO,repository_id='orders')},auth=dict(email_env='PRIVATE_EMAIL',token_env='PRIVATE_BB_TOKEN')),
   kaiten=dict(base_url='https://author.invalid',board_ids=['100'],bot_id='1',token_env='PRIVATE_KAITEN_TOKEN',bindings={RID:'10001'})))
  service=Service(store=store,connectors={},analyzer=SimpleNamespace(policy=policy,runtime_sources=[]),installation_id='author-fixture',environment='qa',ui_metadata=metadata_for_config(config))
  scope=scope_for_service(service);seed.seed(store,scope)
  for version,state in [('v1','ANALYZED'),('v2','FAILED')]:
   store.apply_snapshot(resource_id=RID,provider='bitbucket',kind='pr',version=version,snapshot={'_tracker_target':'10002','secret':'PRIVATE_SNAPSHOT'},event_id='author',closed=False)
   job=store.claim_job('operator-qa')
   # seed leaves an author RUNNING job; only newly queued binding resource can be claimed.
   req=seed.namespace(request());req.update(scope.receipt());store.stamp_ui_scope(job,req)
   raw=seed.namespace(result()) if state=='ANALYZED' else None
   body=canonical({'secret':'PRIVATE_DOCUMENT'})
   store.complete_job(job,state=state,result=raw,reason=raw['reason_code'] if raw else 'commit_unavailable',intent=dict(kind='result' if raw else 'failure',result_digest=digest(raw) if raw else None,body=body,body_digest=digest({'secret':'PRIVATE_DOCUMENT'}),marker='PRIVATE_MARKER'))
  store.note('connection_unauthorized','kaiten','PRIVATE_AUTH_HEADER',ui_scope=scope)
  store.note('postsend_check_failed',RID,'PRIVATE_RESPONSE_BODY',ui_scope=scope)
  store.checkpoint('reconcile:bitbucket','1000')
  settings=UISettings(tmp/'auth.sqlite','http://127.0.0.1:18090',True);auth=AuthStore(settings.database)
  password=secrets.token_urlsafe(24)
  for name,role in [('qa-owner','operator'),('qa-reader','reviewer')]:auth.create_user(name,password,role,scope.identity)
  fd=os.open(credentials,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
  with os.fdopen(fd,'w') as f:json.dump({'username':'qa-owner','password':password},f)
  def state_hash():
   with store._connect() as c:return hashlib.sha256('\n'.join(c.iterdump()).encode()).hexdigest()
  before=state_hash();failed=False
  app=create_app(service,status_token='PRIVATE_SERVICE_TOKEN',ui_settings=settings,ui_auth=auth)
  @app.get('/qa/lifecycle.js')
  async def lifecycle():
   # Deterministic browser harness for lifecycle events; never shipped in product assets.
   return Response("let qaVisible=document.visibilityState;Object.defineProperty(document,'visibilityState',{get:()=>qaVisible,configurable:true});document.getElementById('qa-hide').onclick=()=>{qaVisible='hidden';document.dispatchEvent(new Event('visibilitychange'));};document.getElementById('qa-show').onclick=()=>{qaVisible='visible';document.dispatchEvent(new Event('visibilitychange'));};",media_type='text/javascript')
  @app.middleware('http')
  async def trace(req,call_next):
   nonlocal failed
   if args.fail_logout_first and not failed and req.url.path=='/ui/api/logout':
    failed=True;response=JSONResponse({'error':'qa_forced_unavailable'},status_code=503)
   else:response=await call_next(req)
   if args.fail_logout_first and req.url.path in ('/ui/operations','/ui/connections','/ui/session') and response.headers.get('content-type','').startswith('text/html'):
    body=b''.join([chunk async for chunk in response.body_iterator])
    body=body.replace(b'</body>',b'<aside><button id="qa-hide">QA: hidden</button><button id="qa-show">QA: visible</button></aside><script src="/qa/lifecycle.js" defer></script></body>')
    headers={k:v for k,v in response.headers.items() if k.lower()!='content-length'}
    response=Response(body,status_code=response.status_code,headers=headers)
   if req.url.path.startswith('/ui/'):
    with (private/'http-statuses.jsonl').open('a') as f:f.write(json.dumps({'method':req.method,'path':req.url.path,'status':response.status_code})+'\n')
   return response
  print('Author-only operator stand:127.0.0.1:18090; no external connectors or worker',flush=True)
  try:uvicorn.run(app,host='127.0.0.1',port=18090,access_log=False,proxy_headers=False)
  finally:
   credentials.unlink(missing_ok=True)
   (private/'read-only-check.json').write_text(json.dumps({'before':before,'after':state_hash(),'unchanged':before==state_hash()},indent=2)+'\n')
if __name__=='__main__':main()
