import base64,hashlib,io,json,os,re,secrets,subprocess,sys,tarfile
from pathlib import Path
ROOT=Path('/Users/user/.codex/worktrees/impactmap-batch-00/agent-bitbucket-read')
PRIVATE=ROOT/'work/batch08-cloud/private';PRIVATE.mkdir(parents=True,exist_ok=True,mode=0o700)
SSH=['ssh','-F','/Users/user/Documents/ChatGPT/ВКР/.private/m3-ssh-20261101/config','-o','ControlMaster=auto','-o','ControlPersist=600','-o','ControlPath=/tmp/impactmap08-ssh-control','-o','ConnectTimeout=15','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2','dm-p1-ui','sudo -n /opt/agent-bitbucket/current/venv/bin/python -']

def remote(code,timeout=180):
 r=subprocess.run(SSH,input=code,text=True,capture_output=True,timeout=timeout)
 if r.returncode:
  # Source programs contain no embedded secrets in stdout; do not expose stderr.
  diag={}
  try:
   candidate=json.loads(r.stdout)
   if candidate.get('status')=='CLONE_FAILED' and candidate.get('repo') in {'bb.orders','bb.reporting'}:
    diag={'safe_status':'CLONE_FAILED','repository':candidate['repo'],'reason_tags':[x for x in candidate.get('reason_tags',[]) if x in {'dubious ownership','Permission denied','transport','not a git repository'}]}
  except (ValueError,TypeError,AttributeError): pass
  print(json.dumps({'status':'REMOTE_FAILED','returncode':r.returncode,'error':'remote_control_failed_no_output_exported','safe_diagnostic':diag,'transport_categories':[x for x in ('Broken pipe','Connection reset','Connection timed out','Operation timed out','Permission denied','No route','Host key verification failed','Timeout','Connection closed','SyntaxError','ImportError','ModuleNotFoundError','AssertionError','KeyError','FileExistsError','CalledProcessError','PermissionError','ValueError','TypeError','sudo:','password is required','not a git repository','dubious ownership') if x.lower() in r.stderr.lower()]}));sys.exit(1)
 return json.loads(r.stdout)

BOOTSTRAP=r'''
import base64,hashlib,io,json,os,subprocess,tarfile
from pathlib import Path
root=Path(ROOT_PATH);root.mkdir(mode=0o700,exist_ok=False);app=root/'app';app.mkdir()
with tarfile.open(fileobj=io.BytesIO(base64.b64decode(BUNDLE)),mode='r:gz') as t:
 for m in t.getmembers():
  p=Path(m.name)
  assert not p.is_absolute() and '..' not in p.parts and m.isfile()
  dest=app/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(t.extractfile(m).read())
manifest=MANIFEST
assert all(hashlib.sha256((app/n).read_bytes()).hexdigest()==h for n,h in manifest.items())
(root/'candidate-files.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
loaded=json.loads(Path('/var/lib/agent-bitbucket/run/loaded.json').read_text())
prod=json.loads(Path('/etc/agent-bitbucket/service.json').read_text());policy=json.loads(Path(prod['core']['policy_path']).read_text())
assert not policy.get('model')
pid=int(subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True))
env=dict(x.split('=',1) for x in Path(f'/proc/{pid}/environ').read_text().split('\x00') if '=' in x)
needed=prod['bitbucket']['auth'];creds={needed['email_env']:env[needed['email_env']],needed['token_env']:env[needed['token_env']],'IM_KAITEN_TOKEN':KAITEN_TOKEN}
fd=os.open(root/'secrets.json',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:json.dump(creds,f)
for name in ('mirrors','state','receipts'): (root/name).mkdir()
for repo in policy['repositories']:
 dest=root/'mirrors'/(repo['id']+'.git')
 subprocess.run(['git','-c','safe.directory='+repo['root'],'clone','--mirror','--no-hardlinks','--quiet',repo['root'],str(dest)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
 repo['root']=str(dest)
policy['installation_id']='impactmap-kaiten-cloud-20261115';policy['environment']='acceptance'
(root/'policy.json').write_text(json.dumps(policy,indent=2)+'\n')
config={k:v for k,v in prod.items() if k not in ('jira','confluence','github','dry_run_dir')}
config.update(installation_id=policy['installation_id'],environment=policy['environment'],state_path=str(root/'state'/'queue.sqlite'),publication='live',allow_loopback_http=False)
config['bitbucket']['mode']='kaiten_delivery';config['bitbucket']['refresh_mirrors']=True
config['core']={'policy_path':str(root/'policy.json'),'state_dir':str(root/'state'/'core'),'constitution_path':str(app/'constitutions'/'agent-service-v1.yaml')}
rid='bitbucket:'+prod['bitbucket']['workspace_uuid']+'/'+str(prod['bitbucket']['repositories']['agent-pilot-orders']['uuid'])+'#'+str(PR_NUMBER)
config['kaiten']={'base_url':'https://rengalaxies.kaiten.ru','board_ids':['1982649'],'bot_id':'1000388','token_env':'IM_KAITEN_TOKEN','bindings':{rid:'74759475'}}
config['analysis']={**config.get('analysis',{}),'code_version':CODE_VERSION}
(root/'service.json').write_text(json.dumps(config,indent=2)+'\n')
scope={'resource_id':rid,'workspace_uuid':prod['bitbucket']['workspace_uuid'],'repository_uuids':[str(r['uuid']) for r in prod['bitbucket']['repositories'].values()],
       'kaiten_origin':'https://rengalaxies.kaiten.ru','board_ids':['1982649'],'card_ids':['74759475',SECONDARY_CARD],'bot_id':'1000388','secondary_card':SECONDARY_CARD,'secondary_title':'ImpactMap08 — disposable lifecycle acceptance 20261115',
       'installation_id':policy['installation_id'],'environment':policy['environment'],'head_ref':'impactmap-kaiten-cloud-20261115','base_ref':'main',
       'provider_repository':'bb.orders','destination_tip':subprocess.check_output(['git','--git-dir',str(root/'mirrors'/'bb.orders.git'),'rev-parse','refs/heads/main'],text=True).strip(),
       'consumer_pins':{'bb.reporting':subprocess.check_output(['git','--git-dir',str(root/'mirrors'/'bb.reporting.git'),'rev-parse','refs/heads/main'],text=True).strip()}}
(root/'scope.json').write_text(json.dumps(scope,indent=2)+'\n')
pre={'installed_commit':loaded['commit'],'installed_pid':pid,'installed_service_config_sha256':hashlib.sha256(Path('/etc/agent-bitbucket/service.json').read_bytes()).hexdigest()}
(root/'installed-before.json').write_text(json.dumps(pre,indent=2)+'\n')
print(json.dumps({'root':str(root),'resource_id':rid,'source_file_count':len(manifest),'manifest_sha256':hashlib.sha256((root/'candidate-files.json').read_bytes()).hexdigest(),'installed_before':pre}))
'''

BOOTSTRAP=BOOTSTRAP.replace(chr(92)+chr(92)+'n',chr(92)+'n')

def bootstrap(pr):
 paths=subprocess.check_output(['git','ls-files','-z','src','tests','tools','constitutions','examples','pyproject.toml'],cwd=ROOT).decode().split('\0')
 paths=sorted(set(p for p in paths if p)|{'tools/agent_service/kaiten_live_acceptance.py','tests/service/test_kaiten_live_acceptance.py'})
 buf=io.BytesIO();manifest={}
 with tarfile.open(fileobj=buf,mode='w:gz') as t:
  for name in paths:
   path=ROOT/name
   if not path.is_file() or path.is_symlink():raise ValueError('unsupported_bundle_entry')
   data=path.read_bytes();manifest[name]=hashlib.sha256(data).hexdigest()
   info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o644;info.mtime=0;t.addfile(info,io.BytesIO(data))
 session=PRIVATE/'session.json'
 assert not session.exists(),'Existing remote sandbox must be reused'
 root='/var/tmp/impactmap-kaiten-cloud-20261115-'+secrets.token_hex(4)
 token=(ROOT/'work/batch08/private/kaiten-token.txt').read_text().strip()
 version='e22413a+cloud-helper:'+manifest['tools/agent_service/kaiten_live_acceptance.py'][:12]
 setup='ROOT_PATH='+repr(root)+'\nBUNDLE='+repr(base64.b64encode(buf.getvalue()).decode())+'\nMANIFEST='+repr(manifest)+'\nKAITEN_TOKEN='+repr(token)+'\nPR_NUMBER='+repr(pr)+'\nCODE_VERSION='+repr(version)+'\nSECONDARY_CARD='+repr(json.loads((PRIVATE/'disposable-card.json').read_text())['card_id'])+'\n'
 compile(setup+BOOTSTRAP,'<bootstrap>','exec')
 result=remote(setup+BOOTSTRAP,timeout=240)
 expected=hashlib.sha256((json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()).hexdigest()
 assert result['manifest_sha256']==expected
 session.write_text(json.dumps(result,indent=2)+'\n');(PRIVATE/'candidate-files.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n')
 print(json.dumps(result))

PRELUDE=r'''
import json,os,subprocess,time,signal,sys
from pathlib import Path
root=Path(ROOT_PATH);py='/opt/agent-bitbucket/current/venv/bin/python'
env={k:v for k,v in os.environ.items() if k in {'PATH','HOME','LANG','LC_ALL','TZ'}}
env['PYTHONPATH']=str(root/'app'/'src')+':'+str(root/'app');env['PYTHONDONTWRITEBYTECODE']='1'
sys.path[:0]=[str(root/'app'/'src'),str(root/'app')]
sys.dont_write_bytecode=True
from tools.agent_service.kaiten_live_acceptance import safe_test_summary,recovery_errors
'''

if __name__=='__main__':
 sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
 from tools.agent_service.kaiten_live_acceptance import validate_control_request
 action=sys.argv[1];name=sys.argv[2] if len(sys.argv)>2 else None
 validate_control_request(action,name)
 if action=='bootstrap':bootstrap(int(sys.argv[2]));sys.exit()
 session=json.loads((PRIVATE/'session.json').read_text());root=session['root'];assert re.fullmatch('/var/tmp/impactmap-kaiten-cloud-20261115-[a-f0-9]{8}',root)
 code='ROOT_PATH='+repr(root)+'\n'+PRELUDE
 if action=='linux-tests':
  code+=r'''
log=open(root/'linux-tests.log','x');cmd=[py,'-m','unittest','tests.service.test_kaiten','tests.service.test_kaiten_delivery','tests.service.test_kaiten_live_acceptance','tests.service.test_tracker_api_probe','tests.service.test_tracker_contract','tests.service.test_bitbucket_jira','tests.service.test_bitbucket_analysis','tests.service.test_jira_bootstrap','tests.service.test_jira_listing_recovery','tests.service.test_jira_presentation','tests.service.test_delivery','tests.service.test_errors','tests.service.test_races','tests.service.test_restart','tests.service.test_connection','-v']
p=subprocess.Popen(cmd,cwd=root/'app',env=env,stdout=log,stderr=subprocess.STDOUT);(root/'linux-test-pid').write_text(str(p.pid));print(json.dumps({'test_pid':p.pid}))
'''
 elif action=='tests-status':
  code+=r'''
print(json.dumps(safe_test_summary((root/'linux-tests.log').read_text())))
'''
 elif action=='run':
  runid,head,status=sys.argv[2:5];fault=sys.argv[5] if len(sys.argv)>5 else 'none';card=sys.argv[6] if len(sys.argv)>6 else '74759475';closed=len(sys.argv)>7 and sys.argv[7]=='closed'
  assert re.fullmatch('[0-9a-f]{40}',head) and status in {'USEFUL','PARTIAL','ABSTAINED'} and fault in {'none','after_send'} and card.isdigit()
  args=['-m','tools.agent_service.kaiten_live_acceptance','--root',root,'--run-id',runid,'--expected-head',head,'--expected-status',status,'--fault',fault,'--expected-card',card,'--manifest-sha256',session['manifest_sha256']]
  if status=='USEFUL':args+=['--expected-finding','POSSIBLE_TRUNCATION']
  if closed:args+=['--expect-closed']
  code+='ARGS='+repr(args)+'\n'
  code+=r'''
env.update(json.loads((root/'secrets.json').read_text()))
log=open(root/(ARGS[ARGS.index('--run-id')+1]+'.log'),'x');p=subprocess.Popen([py]+ARGS,cwd=root/'app',env=env,stdout=log,stderr=subprocess.STDOUT);print(json.dumps({'pid':p.pid,'run_id':ARGS[ARGS.index('--run-id')+1]}))
'''
 elif action=='fault-ready':
  code+=r'''
p=root/'fault-ready.json';print(p.read_text() if p.exists() else json.dumps({'status':'PENDING'}))
'''
 elif action=='receipt':
  code+='NAME='+repr(name)+'\n'
  code+=r'''
p=root/'receipts'/(NAME+'.json')
if p.exists():print(p.read_text())
else:
 log=root/(NAME+'.log');lines=log.read_text().splitlines() if log.exists() else []
 error={}
 for line in lines:
  try:
   item=json.loads(line)
   if item.get('status')=='FAIL' and isinstance(item.get('error_type'),str) and item['error_type'].isidentifier():error={'status':'FAIL','error_type':item['error_type']}
  except (ValueError,TypeError,AttributeError):pass
 print(json.dumps(error or {'status':'PENDING'}))
'''
 elif action=='kill-ready':
  code+='EXPECTED_RUN='+repr(name)+'\n'
  code+=r'''
f=json.loads((root/'fault-ready.json').read_text());assert f['run_id']==EXPECTED_RUN and f['kind']=='result' and f['state']=='SENDING'
pid=f['pid'];cmd=Path(f'/proc/{pid}/cmdline').read_bytes();stat=Path(f'/proc/{pid}/stat').read_text().split()
assert stat[21]==f['start_ticks'] and b'tools.agent_service.kaiten_live_acceptance' in cmd and str(root).encode() in cmd
import sqlite3
with sqlite3.connect(root/'state'/'queue.sqlite') as db:
 row=db.execute('select state from intents where intent_id=?',(f['intent_id'],)).fetchone();assert row[0]=='SENDING'
 st=(root/'state'/'queue.sqlite').stat();assert st.st_dev==f['db_device'] and st.st_ino==f['db_inode']
os.kill(pid,signal.SIGKILL)
not_running=False
for _ in range(100):
 p=Path(f'/proc/{pid}/stat')
 if not p.exists() or p.read_text().split()[2]=='Z':not_running=True;break
 time.sleep(.05)
assert not_running
k={'run_id':EXPECTED_RUN,'killed_pid':pid,'start_ticks':f['start_ticks'],'signal':9,'not_running':not_running,'lease_expires':f['lease_expires']}
(root/'fault-killed.json').write_text(json.dumps(k));print(json.dumps(k))
'''
 elif action=='recovery-proof':
  code+='NAME='+repr(name)+'\n'
  code+=r'''
a=json.loads((root/'fault-ready.json').read_text());b=json.loads((root/'fault-killed.json').read_text());c=json.loads((root/'receipts'/(NAME+'.json')).read_text())
errors=recovery_errors(a,b,c);print(json.dumps({'status':'PASS' if not errors else 'FAIL','errors':errors,'before_pid':a['pid'],'after_pid':c['pid'],'same_comment_id':a['comment_id'],'before_state':'SENDING','after_state':'DELIVERED','recovery_wrote':False if not errors else None}))
'''
 elif action in {'relink','archive','restore','delete-result','delete-card'}:
  assert name in ({'primary','secondary'} if action=='relink' else {'secondary'})
  code+='ACTION='+repr(action)+'\nROLE='+repr(name)+'\n'
  code+=r'''
import fcntl,sqlite3
from agent_service.http import HttpClient,NotFound
from agent_service.publisher import resource_marker
from agent_service.connectors.kaiten import KaitenConnector
from agent_service.connectors.tracker_contract import CommentIdentity
from tools.agent_service.kaiten_live_acceptance import durable_json
lock=(root/'acceptance.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
scope=json.loads((root/'scope.json').read_text());cfg=json.loads((root/'service.json').read_text());secrets=json.loads((root/'secrets.json').read_text())
assert cfg['kaiten']['base_url']==scope['kaiten_origin']=='https://rengalaxies.kaiten.ru'
card=scope['secondary_card'] if ROLE=='secondary' else '74759475';assert card in scope['card_ids']
api=HttpClient(scope['kaiten_origin']);headers={'Authorization':'Bearer '+secrets['IM_KAITEN_TOKEN']}
card_path='/api/v1/cards/'+card
raw=api.request('GET',card_path,headers=headers).json()
assert str(raw['id'])==card and str(raw['board_id'])=='1982649'
if ROLE=='secondary': assert raw['title']==scope['secondary_title'] and not raw.get('parents_count') and not raw.get('children_count')
report={'action':ACTION,'card_id':card,'provenance':'REAL_KAITEN_API'}
if ACTION=='relink':
 old=cfg['kaiten']['bindings'][scope['resource_id']];cfg['kaiten']['bindings'][scope['resource_id']]=card
 durable_json(root/'service.json',cfg);report.update(previous_card=old,current_card=card)
elif ACTION in {'archive','restore'}:
 condition=2 if ACTION=='archive' else 1
 durable_json(root/('pending-'+ACTION+'.json'),report)
 if raw['condition']!=condition:api.request('PATCH',card_path,headers=headers,json_body={'condition':condition})
 after=api.request('GET',card_path,headers=headers).json();assert after['condition']==condition
 report['condition']=condition
elif ACTION=='delete-result':
 assert cfg['kaiten']['bindings'][scope['resource_id']]==card
 connector=KaitenConnector(api,lambda:headers['Authorization'],board_ids=['1982649'],bot_id=scope['bot_id'])
 marker=resource_marker(cfg['installation_id'],scope['resource_id']);owned=[c for c in connector.list_comments(card) if c.marker==marker and c.author==scope['bot_id']]
 assert len(owned)==1
 with sqlite3.connect(root/'state'/'queue.sqlite') as db:
  locator,stored_digest=db.execute('select comment_id,comment_digest from resources where resource_id=?',(scope['resource_id'],)).fetchone()
 decoded=CommentIdentity.decode(locator,expected=connector.identity(card));assert decoded.native_id==owned[0].comment_id and stored_digest==owned[0].digest
 report['deleted_comment_id']=owned[0].comment_id;durable_json(root/'pending-delete-result.json',report)
 result=api.request('DELETE',card_path+'/comments/'+owned[0].comment_id,headers=headers).json();assert str(result['id'])==owned[0].comment_id
 assert not any(c.comment_id==owned[0].comment_id for c in connector.list_comments(card))
 # The product reconciles missing comments during a subsequent generation;
 # make this semantic trigger explicit rather than modifying its SQLite.
 api.request('PATCH',card_path,headers=headers,json_body={'description':'Disposable lifecycle acceptance: owned result removed; explicit card-context change triggers a new analysis.'})
 report['trigger']='explicit_semantic_card_context_update'
elif ACTION=='delete-card':
 assert ROLE=='secondary' and raw['condition']==1
 durable_json(root/'pending-delete-card.json',report)
 api.request('DELETE',card_path,headers=headers)
 try:
  after=api.request('GET',card_path,headers=headers).json();assert after.get('condition')==3 or after.get('deleted') or after.get('archived')
  report['unavailable_status']='deleted_or_archived'
 except NotFound:report['unavailable_status']='HTTP_404'
report['status']='PASS';durable_json(root/('lifecycle-'+ACTION+'-'+ROLE+'.json'),report);print(json.dumps(report))
'''
 elif action=='postflight':
  code+=r'''
import hashlib
before=json.loads((root/'installed-before.json').read_text());loaded=json.loads(Path('/var/lib/agent-bitbucket/run/loaded.json').read_text());pid=int(subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True))
now={'installed_commit':loaded['commit'],'installed_pid':pid,'installed_service_config_sha256':hashlib.sha256(Path('/etc/agent-bitbucket/service.json').read_bytes()).hexdigest()}
print(json.dumps({'same_installed_runtime':now==before,'before':before,'after':now,'active':subprocess.check_output(['systemctl','is-active','agent-bitbucket'],text=True).strip()}))
'''
 else:raise ValueError('lifecycle_operation_not_implemented')
 compile(code,'<remote-control>','exec')
 print(json.dumps(remote(code,timeout=60),ensure_ascii=False))
