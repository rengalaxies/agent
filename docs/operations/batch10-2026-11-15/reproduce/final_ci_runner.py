"""Final Linux test invocation after test-only environment preparation."""
from pathlib import Path
import json,os,re,subprocess,time,traceback
root=Path(__file__).resolve().parent;old=json.loads((root/'status-infra-v1.json').read_text())
uid,gid=json.loads((root/'test-user.json').read_text()).values()
python=str(root/'env/bin/python');source=root/'app'
env=dict(PATH=str(root/'env/bin')+':'+os.defpath,LANG='C.UTF-8',PYTHONDONTWRITEBYTECODE='1',PYTHONUNBUFFERED='1',
         PYTHONPATH=':'.join(map(str,[source/'src',source,source/'tests',source/'tools',root/'testdeps'])))
report={**old,'status':'RUNNING','stage':'full-tests-final','uid':uid,'gid':gid,
        'stages':[s for s in old['stages'] if s['name']!='full-tests'],'superseded_infrastructure_run':'status-infra-v1.json'}
def save():
 p=root/'status.tmp';p.write_text(json.dumps(report,indent=2)+'\n');os.replace(p,root/'status.json')
save()
try:
 discovery="import json,unittest; s=unittest.defaultTestLoader.discover('tests');\ndef walk(x):\n for y in x:\n  if isinstance(y,unittest.TestSuite):yield from walk(y)\n  else:yield y\nt=list(walk(s));bad=[x.id() for x in t if x.__class__.__name__=='_FailedTest'];print(json.dumps(dict(cases=len(t),loader_errors=bad)));raise SystemExit(bool(bad))"
 pre=subprocess.run([python,'-c',discovery],cwd=source,env=env,user=uid,group=gid,extra_groups=[gid],capture_output=True,text=True,timeout=120)
 (root/'discovery-final.log').write_text(pre.stdout+'\n'+pre.stderr);assert pre.returncode==0,'discovery_failed'
 report['discovery']=json.loads(pre.stdout);save();start=time.monotonic()
 with (root/'full-tests-final.log').open('w') as f:
  run=subprocess.run([python,'-m','unittest','discover','-s','tests','-v'],cwd=source,env=env,user=uid,group=gid,extra_groups=[gid],stdout=f,stderr=f,timeout=1200)
 text=(root/'full-tests-final.log').read_text(errors='replace');match=re.search(r'Ran (\d+) tests',text)
 item=dict(name='full-tests-final',returncode=run.returncode,wall_s=time.monotonic()-start,tests=int(match[1]) if match else 0)
 report['stages'].append(item)
 report['status']='PASS' if run.returncode==0 and item['tests']==report['discovery']['cases'] and item['tests']>1000 else 'FAILED'
except BaseException as e:report.update(status='FAILED',error_type=type(e).__name__);traceback.print_exc()
finally:save()
