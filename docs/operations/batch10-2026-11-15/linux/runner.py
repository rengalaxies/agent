
from pathlib import Path
import hashlib,json,os,platform,re,subprocess,sys,time,traceback
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
 source=root/'app';subprocess.run(['git','clone','--quiet',str(root/'candidate.bundle'),str(source)],check=True)
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
