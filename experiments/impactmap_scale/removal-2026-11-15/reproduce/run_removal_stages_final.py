from pathlib import Path
import json,os,subprocess,sys
from agent_graph import core_identity
from tools.prepare_impactmap_corpora import load_benchmark_input
root=Path.cwd();work=root/'work/batch05-removal';phase=sys.argv[1];assert phase in ('before-profile7','after-profile9')
identity=core_identity();runs=[]
assert identity['profile']==('http-requests-7' if phase=='before-profile7' else 'http-requests-9'),'checkout_profile_mismatch'
for label in ('repos5-lines50k','repos10-lines100k'):
 manifest=load_benchmark_input(root/'work/batch04/corpora-v1'/label)
 inp=work/(label+'-input.json')
 if inp.exists():assert json.loads(inp.read_text())==manifest
 else:inp.write_text(json.dumps(manifest,indent=2)+'\n')
 target=work/(phase+'-'+label);log=work/(phase+'-'+label+'.log');assert not target.exists() and not log.exists()
 print(json.dumps({'phase':phase,'profile':label,'state':'START'}),flush=True)
 with log.open('x') as output:
  result=subprocess.run([sys.executable,'-m','tools.benchmark_impactmap','--manifest',str(inp),'--output',str(target),'--repeats','3'],stdout=output,stderr=subprocess.STDOUT,env=os.environ.copy(),cwd=root)
 runs.append({'profile':label,'returncode':result.returncode,'output':str(target.relative_to(root))})
 print(json.dumps(runs[-1]),flush=True)
 assert core_identity()==identity,'core_changed_during_stage_measurements'
 if result.returncode:raise SystemExit(result.returncode)
(work/(phase+'-campaign.json')).write_text(json.dumps({'core_identity':identity,'source_sha':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'runs':runs,'execution':'SEQUENTIAL_NOT_PARALLEL','os_caches_reset':False},indent=2)+'\n')
