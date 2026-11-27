from pathlib import Path
import json,os,re,subprocess,sys,time
from concurrent.futures import ThreadPoolExecutor
root=Path.cwd();work=root/'work/batch05-removal'
print('Waiting for running verification suites before exclusive timing',flush=True)
while True:
 texts=[(work/name).read_text() for name in ('performance-final.log','graph-final.log','service-final.log')]
 if all(re.search(r'^Ran \d+ tests? in ',x,re.M) and re.search(r'^(OK|FAILED)',x,re.M) for x in texts):break
 time.sleep(5)
assert all(re.search(r'^OK$',text,re.M) for text in texts),'final_focused_suites_not_green'
def run(name,args):
 print(json.dumps({'phase':name,'state':'START'}),flush=True)
 with (work/(name+'-controller.log')).open('x') as log:
  r=subprocess.run(args,env=os.environ.copy(),cwd=root,stdout=log,stderr=subprocess.STDOUT)
 print(json.dumps({'phase':name,'returncode':r.returncode}),flush=True)
 return r.returncode
assert run('final-stages',[sys.executable,'/tmp/run_removal_stages_final.py','after-profile9'])==0
with ThreadPoolExecutor(max_workers=2) as pool:
 a=pool.submit(run,'acceptance',[sys.executable,'/tmp/removal_acceptance.py'])
 b=pool.submit(run,'quality',[sys.executable,'-m','tools.impactmap_eval.calibrate','--corpus','work/batch06/development-v2','--output','work/batch05-removal/quality','--post-tuning'])
 codes=[a.result(),b.result()]
if any(codes):raise SystemExit(1)
print('CAMPAIGN FINISHED',flush=True)
