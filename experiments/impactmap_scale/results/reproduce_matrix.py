import json,os,pathlib,subprocess,sys,time
root=pathlib.Path.cwd();base=root/'work/batch05/final';base.mkdir(exist_ok=False)
# Serialized foreground workload: no overlap between measured local cases.
env={k:v for k,v in os.environ.items() if k in ('PATH','SYSTEMROOT','TEMP','TMP')};env.update(PYTHONPATH=str(root/'src')+os.pathsep+str(root),PYTHONDONTWRITEBYTECODE='1')
log=base/'progress.jsonl'
def run(name,args,expected=0):
 start=time.perf_counter();out=base/name
 try:
  p=subprocess.run([sys.executable,*args,'--output',str(out)],env=env,cwd=root,capture_output=True,text=True,timeout=1800)
  row=dict(case=name,returncode=p.returncode,expected_returncode=expected,command=['python',*args,'--output','work/batch05/final/'+name],wall_s=time.perf_counter()-start)
  if p.returncode!=expected:row['error_code']='unexpected_exit'
  if not ((out/'result.json').exists() or (out/'summary.json').exists()):
   out.mkdir(parents=True,exist_ok=True);(out/'result.json').write_text(json.dumps(dict(passed=False,error_code='worker_failed_no_result'))+'\n');row['error_code']='worker_failed_no_result'
 except (subprocess.SubprocessError,OSError):row=dict(case=name,error_code='worker_timeout_or_launch',wall_s=time.perf_counter()-start)
 with log.open('a') as f:f.write(json.dumps(row,sort_keys=True)+'\n')
 print(name,row.get('error_code','DONE'),round(row['wall_s'],2),flush=True)
for profile,short in [('repos5-lines50k','5x50k'),('repos10-lines100k','10x100k')]:
 corpus='work/batch04/corpora-v1/'+profile
 run(short+'-defaults',['-m','tools.load_impactmap','--corpus',corpus,'--probe-defaults'],expected=1 if short=='10x100k' else 0)
 run(short+'-baseline',['-m','tools.benchmark_impactmap','--manifest',corpus+'/benchmark-input.json','--repeats','3'])
 run(short+'-equality',['-m','tools.load_impactmap','--corpus',corpus,'--equivalence'])
 for family,delivery in [('independent_prs','burst'),('head_updates','sequential'),('head_updates','burst')]:
  for n in (1,5,10):
   run(short+'-'+family+'-'+delivery+'-'+str(n),['-m','tools.load_impactmap','--corpus',corpus,'--queue-size',str(n),'--family',family,'--delivery',delivery])
print('MATRIX_COMPLETE',flush=True)
