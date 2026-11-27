"""Queue and graph checks in isolated VM state. Only programs go in, metrics come out."""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
from experiments.impactmap_scale.run_pilot_vm_benchmark import REMOTE_MEASURE
ROOT=Path(__file__).resolve().parents[2]

REMOTE_LOAD=r'''
# Reuse the vetted in-place manifest builder, not the existing pilot queue.
source_identity=lambda:dict(loaded_runtime_commit=json.loads(Path('/var/lib/agent-bitbucket/run/loaded.json').read_text())['commit'],core=core_identity(),tool_sha256=TOOL_SHA)
import types
package=types.ModuleType('tools');package.__path__=[];sys.modules['tools']=package
bench=types.ModuleType('tools.benchmark_impactmap');bench.__dict__.update(globals());sys.modules['tools.benchmark_impactmap']=bench
prep=types.ModuleType('tools.prepare_impactmap_corpora');prep.load_benchmark_input=lambda *a,**k:None;sys.modules[prep.__name__]=prep
loadmod=types.ModuleType('tools.load_impactmap');loadmod.__file__='/tmp/load_impactmap_embedded.py';sys.modules[loadmod.__name__]=loadmod
exec(compile(LOAD_CODE,loadmod.__file__,'exec'),loadmod.__dict__)
from agent_graph.engine import Graph
from agent_graph.graph_store import GraphStore
from agent_graph.graph_store_sync import GraphMaintainer
from agent_graph.store import Store
rows=[]
with tempfile.TemporaryDirectory(prefix='impactmap-load-isolated-') as tmp:
 root=Path(tmp)
 meter=SpanRecorder();policy=Policy.model_validate(m['policy']);pairs=[]
 for name,revisions in [('base',m['base_revisions']),('head',m['head_revisions'])]:
  incremental=Store(root/'incremental');g=Graph(policy,incremental);gs=GraphStore(incremental)
  with meter.span('event_'+name):
   r=GraphMaintainer(g,gs).on_code_event(revisions);ctx=g.context(r['context_id']);facts=gs.canonical_facts(g.scope)
  fresh=Store(root/('full-'+name));fg=Graph(policy,fresh);fs=GraphStore(fresh)
  with meter.span('full_'+name):GraphMaintainer(fg,fs).reconcile(revisions)
  ff=fs.canonical_facts(fg.scope);counts=context_counts(ctx)
  pairs.append(dict(scenario=name,equal=facts==ff,facts_count=len(facts),full_sha256=digest(ff),incremental_sha256=digest(facts),counts=counts,
    passed=facts==ff and len(facts)==5 and counts['coverage']=='COMPLETE_WITHIN_PROFILE' and not counts['gap_counts']))
  fresh.close();incremental.close()
 rows.append(dict(kind='pilot_equivalence',passed=all(x['passed'] for x in pairs),cases=pairs,spans=meter.spans))
 for count in (1,5,10):
  events=[dict(pr_id=i,base_sha=m['base_revisions'][provider],head_sha=m['head_revisions'][provider],event_id=f'pilot-replay-{i}') for i in range(1,count+1)]
  r=loadmod.run_queue_input(m,events,root/('queue-'+str(count)),expected_status='ABSTAINED',expected_findings=0,expected_reason='no_supported_delta')
  r['provenance_detail']='controlled independent resource-ID replay of one frozen author-pilot PR4 change; not 16 real PRs'
  rows.append(r)
print(canonical(dict(rows=rows,passed=all(r['passed'] for r in rows),source=source_identity(),environment=environment(),pins=[dict(repository=k,base=m['base_revisions'][k],head=m['head_revisions'][k]) for k in sorted(m['base_revisions'])],source_transfer='NOT_PERFORMED',state='new TemporaryDirectory; removed; installed queue and service untouched')))
'''


def build_payload(pins):
    if set(pins)!={'schema_version','provider_repository','pr_id','base_revisions','head_revisions'} or pins['schema_version']!='impactmap-pilot-pins-1':
        raise ValueError('invalid_pinned_manifest')
    code=(ROOT/'tools/benchmark_impactmap.py').read_text();load=(ROOT/'tools/load_impactmap.py').read_text()
    setup="import sys\nsys.path[:0]=['/opt/agent-bitbucket/current/app/src','/opt/agent-bitbucket/current/app']\n"
    return (setup+"\nPIN_OVERRIDE="+repr(pins)+"\n__name__='benchmark_embedded'\n__file__='/tmp/benchmark_impactmap_embedded.py'\nTOOL_SHA="
            +repr(hashlib.sha256(code.encode()).hexdigest())+"\nLOAD_CODE="+repr(load)+"\nexec(compile("+repr(code)+",__file__,'exec'))\n"
            +REMOTE_MEASURE.split("with tempfile.TemporaryDirectory(prefix=")[0]+REMOTE_LOAD)


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--ssh-config',required=True)
    p.add_argument('--host',default='dm-p1-ui');p.add_argument('--remote-python',default='/opt/agent-bitbucket/current/venv/bin/python')
    p.add_argument('--pins-from',type=Path,required=True);p.add_argument('--output',type=Path,required=True);args=p.parse_args(argv)
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+',args.host) or args.host.startswith('-') or not re.fullmatch(r'/[A-Za-z0-9_/.-]+',args.remote_python):p.error('invalid remote target')
    args.output.mkdir(parents=True,exist_ok=False)
    try:
        payload=build_payload(json.loads(args.pins_from.read_text()));start=time.perf_counter()
        proc=subprocess.run(['ssh','-F',args.ssh_config,args.host,'sudo -n '+args.remote_python+' -'],input=payload,text=True,capture_output=True,timeout=1800)
        if proc.returncode:raise RuntimeError('remote failed')
        result=json.loads(proc.stdout)
        if not isinstance(result.get('passed'),bool) or not isinstance(result.get('rows'),list):raise ValueError('invalid remote output')
        result['ssh_roundtrip_wall_s']=time.perf_counter()-start
        result['load_tool_sha256']=hashlib.sha256((ROOT/'tools/load_impactmap.py').read_bytes()).hexdigest()
    except (subprocess.SubprocessError,OSError,ValueError,RuntimeError):
        result=dict(passed=False,error_code='remote_load_failed')
    (args.output/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(dict(passed=result['passed'],error_code=result.get('error_code'))));return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
