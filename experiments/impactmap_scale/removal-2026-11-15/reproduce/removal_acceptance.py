from pathlib import Path
import json,subprocess,time
from agent_graph import core_identity
from tools.load_impactmap import probe_limits,run_graph_equivalence,run_queue
from tools.prepare_impactmap_corpora import verify_corpus
root=Path.cwd();work=root/'work/batch05-removal/acceptance';work.mkdir(exist_ok=False)
identity=core_identity();results=[]
def record(name,fn):
 print(json.dumps({'test':name,'state':'START'}),flush=True)
 start=time.perf_counter();r=fn();passed=r.get('passed',r.get('verification_passed'))
 if name.endswith('defaults-10'):
  passed=r['error_code']=='corpus_limit' and r['analyzed_fraction']==0
 results.append(dict(test=name,passed=bool(passed),diagnostic_elapsed_seconds=time.perf_counter()-start))
 print(json.dumps(results[-1]),flush=True)
 assert core_identity()==identity,'core_changed_during_acceptance'
for size,label in ((5,'repos5-lines50k'),(10,'repos10-lines100k')):
 corpus=root/'work/batch04/corpora-v1'/label
 record('defaults-'+str(size),lambda:probe_limits(corpus,work/('defaults-'+str(size))))
 record('corpus-'+str(size),lambda:verify_corpus(corpus,work/('corpus-'+str(size))))
 record('equivalence-'+str(size),lambda:run_graph_equivalence(corpus,work/('equivalence-'+str(size))))
# Existing queue/local sink and duplicate replay, not network delivery or capacity/SLO.
record('queue-5-head10-burst',lambda:run_queue(root/'work/batch04/corpora-v1/repos5-lines50k',work/'queue-5-head10-burst',size=10,family='head_updates',delivery='burst'))
record('queue-10-pr1',lambda:run_queue(root/'work/batch04/corpora-v1/repos10-lines100k',work/'queue-10-pr1',size=1,family='independent_prs',delivery='sequential'))
(work/'campaign.json').write_text(json.dumps(dict(core_identity=identity,source_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),results=results,passed=all(r['passed'] for r in results),execution='sequential; diagnostic wall times only; no capacity comparison'),indent=2)+'\n')
if not all(r['passed'] for r in results):raise SystemExit(1)
