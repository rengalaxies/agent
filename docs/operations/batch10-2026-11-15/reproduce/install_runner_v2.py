"""Isolated process-supervisor package acceptance, never production paths."""
from pathlib import Path
import json,os,socket,subprocess,sys,time,traceback
root=Path(__file__).resolve().parent
ci=json.loads((root/'status.json').read_text())
assert ci['status']=='PASS','ci_must_pass_first'
prefix=root/'install-prefix-v2';stand=root/'install-stand-v2'
assert not prefix.exists() and not stand.exists()
python=str(root/'env/bin/python');source=root/'app';package=Path(ci['package'])
env=dict(PATH=str(root/'env/bin')+':'+os.defpath,LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',PYTHONPATH=str(source/'src')+':'+str(source))
result=dict(status='RUNNING',source_commit=ci['source_commit'],supervisor='process',external_live=False)
def save():
 p=root/'install-status-v2.tmp';p.write_text(json.dumps(result,indent=2)+'\n');os.replace(p,root/'install-status-v2.json')
save();server=None
try:
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 with (root/'install-stand-v2.log').open('w') as f:
  server=subprocess.Popen([python,str(source/'tools/agent_service/box/teststand.py'),'serve','--dir',str(stand),'--service-port',str(port)],env=env,cwd=source,stdin=subprocess.DEVNULL,stdout=f,stderr=f)
 deadline=time.monotonic()+45
 while not (stand/'stand.json').exists():
  if server.poll() is not None or time.monotonic()>deadline:raise RuntimeError('stand_not_ready')
  time.sleep(.2)
 destination=prefix/'etc/agent-service/secrets.env';destination.parent.mkdir(parents=True,mode=0o700)
 destination.write_bytes((stand/'secrets.env').read_bytes());destination.chmod(0o600)
 scenarios='fresh_install,end_to_end_on_installed_release,reinstall_is_idempotent,service_killed_comes_back,backup_restore'
 args=[python,str(source/'tools/agent_service/box/acceptance.py'),'--stand',str(stand/'stand.json'),'--release',str(package),
       '--prefix',str(prefix),'--supervisor','process','--only',scenarios,'--call-timeout','180','--output',str(root/'install-acceptance-v2.json')]
 with (root/'install-acceptance-v2.log').open('w') as f:run=subprocess.run(args,env=env,cwd=source,stdout=f,stderr=f,timeout=900)
 result.update(status='PASS' if run.returncode==0 else 'FAILED',returncode=run.returncode)
 if (root/'install-acceptance-v2.json').exists():
  report=json.loads((root/'install-acceptance-v2.json').read_text());result['scenarios']=[dict(name=r['scenario'],result=r['result']) for r in report['scenarios']]
  assert {r['scenario'] for r in report['scenarios']}==set(scenarios.split(',')) and len(report['scenarios'])==5,'incomplete_scenarios'
except BaseException as e:result.update(status='FAILED',error_type=type(e).__name__);traceback.print_exc()
finally:
 # Stop only the service guarded by this exact isolated prefix.
 if prefix.exists():
  code="from tools.agent_service.box.layout import Layout;from tools.agent_service.box.supervisor import choose;choose(Layout.at("+repr(str(prefix))+"),'process').stop()"
  with (root/'install-stop-v2.log').open('w') as f:
   stopped=subprocess.run([python,'-c',code],env=env,cwd=source,stdout=f,stderr=f,timeout=45)
  result['isolated_service_stopped']=stopped.returncode==0
  if stopped.returncode:result['status']='FAILED'
 if server is not None:
  server.terminate()
  try:server.wait(10)
  except subprocess.TimeoutExpired:server.kill();server.wait()
 save()
