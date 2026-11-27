"""Final source/archive gates after scoped acceptance inventory correction."""
from pathlib import Path
import json,os,re,subprocess,tarfile,time,traceback
root=Path(__file__).resolve().parent;inputs=json.loads((root/'final-transfer.json').read_text())
old=json.loads((root/'status.json').read_text());(root/'status-source5d.json').write_text(json.dumps(old,indent=2)+'\n')
user=json.loads((root/'test-user.json').read_text());uid,gid=user['uid'],user['gid'];python=str(root/'env/bin/python');source=root/'app'
env=dict(PATH=str(root/'env/bin')+':'+os.defpath,LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',
         PYTHONPATH=':'.join(map(str,[source/'src',source,source/'tests',source/'tools',root/'testdeps'])))
report=dict(status='RUNNING',complete=False,source_commit=inputs['commit'],root=str(root),uid=uid,gid=gid,stages=[],previous='status-source5d.json')
def save():
 p=root/'status.tmp';p.write_text(json.dumps(report,indent=2)+'\n');os.replace(p,root/'status.json')
def stage(name,args,cwd=source,environment=env,ordinary=False,timeout=1200):
 report['stage']=name;save();start=time.monotonic();options=dict(user=uid,group=gid,extra_groups=[gid]) if ordinary else {}
 with (root/(name+'.log')).open('w') as f:
  try:r=subprocess.run(args,cwd=cwd,env=environment,stdout=f,stderr=f,timeout=timeout,**options);code=r.returncode
  except subprocess.TimeoutExpired:code=124
 text=(root/(name+'.log')).read_text(errors='replace');match=re.search(r'Ran (\d+) tests',text)
 item=dict(name=name,returncode=code,wall_s=time.monotonic()-start)
 if match:item['tests']=int(match[1])
 report['stages'].append(item);save();return code==0
try:
 assert old['status']=='PASS' and json.loads((root/'install-status-v2.json').read_text())['isolated_service_stopped']
 subprocess.run(['git','-C',str(source),'fetch','--quiet',str(root/'final-update.bundle'),'HEAD'],env=env,user=uid,group=gid,extra_groups=[gid],check=True)
 subprocess.run(['git','-C',str(source),'checkout','--quiet','--detach',inputs['commit']],env=env,user=uid,group=gid,extra_groups=[gid],check=True)
 actual=subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],env=env,user=uid,group=gid,text=True).strip();assert actual==inputs['commit']
 with tarfile.open(root/'release-final.tar.gz','r:gz') as t:
  for m in t.getmembers():
   p=Path(m.name);assert not p.is_absolute() and '..' not in p.parts
   if m.isdir():continue
   assert m.isfile();dest=root/'release-final'/p;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(t.extractfile(m).read());dest.chmod(m.mode&0o777)
 package=next((root/'release-final').iterdir());report['package']=str(package);save()
 assert stage('verify-package-release',[python,str(package/'app/tools/agent_service/box/release.py'),'verify',str(package)],timeout=120)
 assert stage('full-tests-release',[python,'-m','unittest','discover','-s','tests','-v'],ordinary=True)
 assert report['stages'][-1]['tests']==1291
 assert stage('box-tests-release',[python,'-m','unittest','discover','-s','tools/agent_service/box/tests','-t','.','-v'],timeout=300)
 assert report['stages'][-1]['tests']==78
 packaged={**env,'PYTHONPATH':str(package/'app/src')+':'+str(package/'app')}
 assert stage('artifact-smoke-release',[python,'-m','agent_service','smoke','--keep',str(root/'artifact-smoke-release')],cwd=package/'app',environment=packaged,timeout=180)
 assert stage('artifact-core-release',[python,'-c','import agent_graph,json;print(json.dumps(agent_graph.core_identity(),sort_keys=True))'],cwd=package/'app',environment=packaged,timeout=30)
 report['status']='PASS';save()  # install runner requires successful CI before creating its prefix
 assert stage('install-acceptance-release',[python,str(root/'install-runner-v3.py')],timeout=1000)
 assert json.loads((root/'install-status-v3.json').read_text())['status']=='PASS'
 report['status']='PASS'
except BaseException as e:report.update(status='FAILED',error_type=type(e).__name__);traceback.print_exc()
finally:report['complete']=True;save()
