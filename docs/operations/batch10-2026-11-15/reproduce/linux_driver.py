"""This run's isolated Linux CI control; never changes installed service/config."""
from pathlib import Path
import argparse,hashlib,io,json,shlex,subprocess,tarfile
LOCAL=Path(__file__).resolve().parent
BUILD=json.loads((LOCAL/'build.log').read_text());SHA=BUILD['commit']
REMOTE='/var/tmp/impactmap-batch10-'+SHA[:12]+'-20261115'
SSH=['ssh','-F','/Users/user/Documents/ChatGPT/ВКР/.private/m3-ssh-20261101/config','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ControlMaster=auto','-o','ControlPersist=600','-o','ControlPath=/tmp/impactmap10-ssh-control','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=2','dm-p1-ui']

RUNNER=r'''
from pathlib import Path
import hashlib,json,os,platform,re,subprocess,sys,time,traceback,tarfile
root=Path(__file__).resolve().parent
report=dict(status='RUNNING',root=str(root),platform=platform.platform(),python=sys.version.split()[0],stages=[])
def save():
 p=root/'status.tmp';p.write_text(json.dumps(report,indent=2)+'\n');os.replace(p,root/'status.json')
def stage(name,argv,cwd=None,env=None,timeout=900):
 report['stage']=name;save();start=time.monotonic()
 with (root/(name+'.log')).open('w') as f:
  try:r=subprocess.run(argv,cwd=cwd,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=timeout);code=r.returncode
  except subprocess.TimeoutExpired:code=124
 item=dict(name=name,returncode=code,wall_s=time.monotonic()-start)
 text=(root/(name+'.log')).read_text(errors='replace');match=re.search(r'Ran (\d+) tests',text)
 if match:item['tests']=int(match[1])
 report['stages'].append(item);save();return code==0
try:
 source=root/'app'
 if not source.exists():subprocess.run(['git','clone','--quiet',str(root/'candidate.bundle'),str(source)],check=True)
 report['source_commit']=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip();save()
 with tarfile.open(root/'release.tar.gz','r:gz') as t:
  for m in t.getmembers():
   p=Path(m.name);assert not p.is_absolute() and '..' not in p.parts
   if m.isdir():continue
   assert m.isfile();dest=root/'release'/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(t.extractfile(m).read());dest.chmod(m.mode&0o777)
 package=next((root/'release').iterdir());report['package']=str(package)
 assert stage('venv',[sys.executable,'-m','venv',str(root/'env')],timeout=120)
 python=str(root/'env/bin/python');env=dict(PATH=str(root/'env/bin')+':'+os.defpath,LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1')
 assert stage('install-runtime',[python,'-m','pip','install','--no-index','--no-cache-dir','--find-links',str(package/'wheels'),'--require-hashes','-r',str(package/'app/infra/agent_service/requirements.lock')],env=env,timeout=120)
 assert stage('install-test-deps',[python,'-m','pip','install','--no-index','--no-cache-dir','--no-deps','--target',str(root/'testdeps'),'--find-links',str(root/'test-wheels'),'-r',str(root/'test-requirements.txt')],env=env,timeout=120)
 assert stage('verify-package',[python,str(package/'app/tools/agent_service/box/release.py'),'verify',str(package)],env=env,timeout=120)
 testenv={**env,'PYTHONPATH':str(source/'src')+':'+str(source)+':'+str(root/'testdeps')}
 stage('full-tests',[python,'-m','unittest','discover','-s','tests','-v'],cwd=source,env=testenv,timeout=1200)
 stage('box-tests',[python,'-m','unittest','discover','-s','tools/agent_service/box/tests','-t','.','-v'],cwd=source,env=testenv,timeout=300)
 packaged={**env,'PYTHONPATH':str(package/'app/src')+':'+str(package/'app')}
 stage('artifact-smoke',[python,'-m','agent_service','smoke','--keep',str(root/'artifact-smoke')],cwd=package/'app',env=packaged,timeout=180)
 stage('artifact-core',[python,'-c','import agent_graph,json;print(json.dumps(agent_graph.core_identity(),sort_keys=True))'],cwd=package/'app',env=packaged,timeout=30)
 report['status']='PASS' if all(s['returncode']==0 for s in report['stages']) else 'FAILED'
except BaseException as e:
 report.update(status='FAILED',error_type=type(e).__name__);traceback.print_exc()
finally:save()
'''

def remote(code,data=None,timeout=45):
 cmd=SSH+['sudo -n /opt/agent-bitbucket/current/venv/bin/python -c '+shlex.quote(code)]
 r=subprocess.run(cmd,input=data,capture_output=True,timeout=timeout)
 if r.returncode:
  (LOCAL/'ssh-last-error.log').write_bytes(r.stderr)
  reason=[v for v in ('Connection timed out','Connection reset','Broken pipe','Permission denied','Host key verification failed','FileExistsError','SyntaxError') if v.lower() in r.stderr.decode(errors='replace').lower()]
  raise RuntimeError('remote_control_failed:'+str(r.returncode)+':'+','.join(reason))
 return json.loads(r.stdout)

def bootstrap():
 files={'candidate.bundle':LOCAL/'candidate.bundle','release.tar.gz':Path(BUILD['archive']), 'test-requirements.txt':LOCAL/'test-requirements.txt'}
 files.update({'test-wheels/'+p.name:p for p in (LOCAL/'test-wheels').glob('*.whl')})
 payload=io.BytesIO()
 with tarfile.open(fileobj=payload,mode='w') as t:
  for name,path in files.items():
   raw=path.read_bytes();m=tarfile.TarInfo(name);m.size=len(raw);t.addfile(m,io.BytesIO(raw))
  raw=RUNNER.encode();m=tarfile.TarInfo('runner.py');m.size=len(raw);t.addfile(m,io.BytesIO(raw))
 expected={n:hashlib.sha256(p.read_bytes()).hexdigest() for n,p in files.items()};expected['runner.py']=hashlib.sha256(RUNNER.encode()).hexdigest()
 code='''import hashlib,io,json,os,subprocess,sys,tarfile\nfrom pathlib import Path\nroot=Path(ROOT);root.mkdir(mode=0o700,exist_ok=False)\nwith tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:') as t:\n for m in t.getmembers():\n  p=Path(m.name);assert m.isfile() and not p.is_absolute() and '..' not in p.parts and m.name in EXPECTED\n  raw=t.extractfile(m).read();assert hashlib.sha256(raw).hexdigest()==EXPECTED[m.name]\n  dest=root/p;dest.parent.mkdir(exist_ok=True);dest.write_bytes(raw)\n(root/'inputs.json').write_text(json.dumps(EXPECTED,indent=2))\nwith (root/'runner.log').open('wb') as log:process=subprocess.Popen([sys.executable,str(root/'runner.py')],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True)\nprint(json.dumps(dict(root=str(root),pid=process.pid,status='STARTED')))'''.replace('ROOT',repr(REMOTE)).replace('EXPECTED',repr(expected))
 result=remote(code,payload.getvalue(),timeout=120);(LOCAL/'linux-start.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

def status(collect=False):
 names=['status.json','runner.log','inputs.json','venv.log','install-runtime.log','install-test-deps.log','verify-package.log','full-tests.log','box-tests.log','artifact-smoke.log','artifact-core.log','runner-v2.log','status-v1.json','status-infra-v1.json','testenv-prepare.log','install-test-deps-v2.log','ci-final-runner.log','discovery-final.log','full-tests-final.log','rg.json','test-user.json','runner.py','runner-v2.py','ci-final-runner.py','prepare-testenv.py','install-status.json','install-acceptance.json','install-acceptance.log','install-stop.log','install-runner.log','install-status-v2.json','install-acceptance-v2.json','install-acceptance-v2.log','install-runner-v2.log','install-stop-v2.log','status-source5d.json','release-ci-runner.log','verify-package-release.log','full-tests-release.log','box-tests-release.log','artifact-smoke-release.log','artifact-core-release.log','install-acceptance-release.log','install-status-v3.json','install-acceptance-v3.json','install-acceptance-v3.log','install-stop-v3.log','installed-api-release.json','release-ci-runner.py','install-runner-v3.py','final-transfer.json']
 code='''import json\nfrom pathlib import Path\nroot=Path(ROOT)\nprint(json.dumps({n:(root/n).read_text(errors='replace') for n in NAMES if (root/n).exists()}))'''.replace('ROOT',repr(REMOTE)).replace('NAMES',repr(names))
 files=remote(code,timeout=30)
 if collect:
  target=LOCAL/'linux-results';target.mkdir(exist_ok=True)
  for name,value in files.items():(target/name).write_text(value)
 print(files.get('status.json',json.dumps(dict(status='STARTING'))))

def resume_setup():
 code="""import hashlib,json,subprocess,sys
from pathlib import Path
root=Path(ROOT);old=json.loads((root/'status.json').read_text())
assert old['status']=='FAILED' and old['error_type']=='NameError' and old['stages']==[]
assert subprocess.check_output(['git','-C',str(root/'app'),'rev-parse','HEAD'],text=True).strip()==SHA
assert not (root/'runner-v2.py').exists()
(root/'status-v1.json').write_text((root/'status.json').read_text())
raw=RUNNER.encode();(root/'runner-v2.py').write_bytes(raw)
(root/'runner-v2.sha256').write_text(hashlib.sha256(raw).hexdigest())
with (root/'runner-v2.log').open('wb') as log:process=subprocess.Popen([sys.executable,str(root/'runner-v2.py')],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True)
print(json.dumps(dict(root=str(root),pid=process.pid,status='STARTED_SETUP_REPAIR')))""".replace('ROOT',repr(REMOTE)).replace('SHA',repr(SHA)).replace('RUNNER',repr(RUNNER))
 print(json.dumps(remote(code)))

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('mode',choices=['bootstrap','status','collect','resume-setup']);a=p.parse_args()
 bootstrap() if a.mode=='bootstrap' else resume_setup() if a.mode=='resume-setup' else status(a.mode=='collect')
