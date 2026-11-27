import pathlib,json,os,pwd,shutil,sqlite3,subprocess,sys,hashlib
release=pathlib.Path('/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312')
sys.path[:0]=[str(release/'app/src'),str(release/'app')]
from tools.agent_service.box.release import verify_tree
manifest,_=verify_tree(release,wheels=False);assert manifest['code']['commit'].startswith('29ed2ad')
old=pathlib.Path('/var/tmp/impactmap-kaiten-cloud-20261115-a59cd9f8')
state=pathlib.Path('/var/lib/impactmap-ui-kaiten');etc=pathlib.Path('/etc/impactmap-ui-kaiten');user=pwd.getpwnam('impactmap-ui')
assert not state.exists() and not etc.exists(),'existing_live_state_must_be_resumed_not_overwritten'
state.mkdir(mode=0o700);etc.mkdir(mode=0o750);os.chown(etc,0,user.pw_gid)
for d in ('service','core','mirrors','run','ui','tmp','dry-run','receipts'):(state/d).mkdir(mode=0o700)
# Queue08 retains the owned comment identity. Graph is rebuilt from source;
# legacy jobs stay hidden until a new trusted scope receipt is actually stamped.
src=sqlite3.connect('file:'+str(old/'state/queue.sqlite')+'?mode=ro',uri=True)
dst=sqlite3.connect(state/'service/service.sqlite');src.backup(dst);dst.close();src.close()
policy=json.loads((old/'policy.json').read_text())
policy['subject']='ImpactMap live UI: dedicated authored PR5 and Kaiten74759475'
for repo in policy['repositories']:
 dest=state/'mirrors'/pathlib.Path(repo['root']).name;shutil.copytree(repo['root'],dest)
 (dest/'config').write_text('[core]\nrepositoryformatversion = 0\nbare = true\n');repo['root']=str(dest)
cfg=json.loads((old/'service.json').read_text());cfg.update(state_path=str(state/'service/service.sqlite'),ui_config_path=str(state/'ui/ui.json'))
cfg['core']=dict(policy_path=str(etc/'policy.json'),state_dir=str(state/'core'),constitution_path=str(release/'app/constitutions/agent-service-v1.yaml'))
cfg['analysis']['code_version']=manifest['release_id'];cfg['reconcile_seconds']=60
assert cfg['publication']=='live' and cfg['kaiten']['board_ids']==['1982649'] and set(cfg['kaiten']['bindings'].values())=={'74759475'}
for name,data in [('policy.json',policy),('service.json',cfg)]:
 p=etc/name;p.write_text(json.dumps(data,indent=2)+'\n');p.chmod(0o640);os.chown(p,0,user.pw_gid)
for d,ds,fs in os.walk(state):
 os.chown(d,user.pw_uid,user.pw_gid)
 for f in fs:os.chown(pathlib.Path(d)/f,user.pw_uid,user.pw_gid)
code="""import pathlib,sys,sqlite3,json
release,state,etc=map(pathlib.Path,sys.argv[1:]);sys.path[:0]=[str(release/'app/src'),str(release/'app')]
from agent_service.ui_auth import configure_private_ui,AuthStore
from agent_service.ui_scope import scope_for_config
from agent_service.config import ServiceConfig
configure_private_ui(state,'https://82.202.141.50')
source=sqlite3.connect('file:/var/lib/impactmap-ui-pilot/ui/auth.sqlite?mode=ro',uri=True);dest=sqlite3.connect(state/'ui/auth.sqlite');source.backup(dest);dest.close();source.close()
auth=AuthStore(state/'ui/auth.sqlite',create=False)
with auth.transaction() as c:
 c.execute('UPDATE users SET disabled=1,version=version+1');c.execute('DELETE FROM sessions');c.execute('DELETE FROM challenges')
scope=scope_for_config(ServiceConfig.load(etc/'service.json'));auth.change_user('owner',scope=scope.identity,disabled=False)
print(json.dumps(dict(scope=scope.identity,owner_password='PRESERVED_INSIDE_VM',sessions='REVOKED',qa='DISABLED')))
"""
r=subprocess.run([str(release/'venv/bin/python'),'-I','-B','-c',code,str(release),str(state),str(etc)],user=user.pw_uid,group=user.pw_gid,extra_groups=[],env=dict(PATH=os.defpath,PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,check=True,timeout=30)
print(json.dumps(dict(status='PREPARED_NOT_STARTED',source_commit=manifest['code']['commit'],state=str(state),config_sha256=hashlib.sha256((etc/'service.json').read_bytes()).hexdigest(),namespace=[cfg['installation_id'],cfg['environment']],bindings=cfg['kaiten']['bindings'],auth=json.loads(r.stdout),kaiten_key='NOT_TRANSFERRED',live_writes=0,proxy='UNCHANGED_18092')))
