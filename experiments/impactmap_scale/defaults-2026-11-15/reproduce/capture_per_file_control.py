"""Actual per-file omission on expanded defaults, both worktree and pinned Git."""
from pathlib import Path
from collections import Counter
import json,subprocess
from agent_graph import core_identity
from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from tests.graph.test_working_limits import WorkingLimitsTests
root=Path.cwd();target=root/'work/batch05-defaults/per-file-control.json';assert not target.exists()
x=WorkingLimitsTests();x.setUp();cases=[]
try:
 (x.root/'corpus/orders/oversize.md').write_text('x'*65_537)
 for mode in ('worktree','git'):
  if mode=='git':
   data=x.policy.model_dump()
   for repo in data['repositories']:
    def git(*args):return subprocess.check_output(['git','-C',repo['root'],*args],text=True,stderr=subprocess.DEVNULL).strip()
    git('init','-b','main');git('add','.')
    git('-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-m','per-file fixture')
    repo.update(snapshot='git',revision=git('rev-parse','HEAD'))
   x.policy=Policy.model_validate(data)
  context=Graph(x.policy,x.store).prepare_context()
  result=dict(mode=mode,coverage=context['coverage'],gap_counts=dict(Counter(g['code'] for g in context['graph']['gaps'])),gaps=context['graph']['gaps'],
   files_read=len(context['sources']),inventory_entries=len(context['inventory']),accepted_source_bytes=sum(len(s['text'].encode()) for s in context['sources'].values()),
   repositories_with_read_sources=len({s['repository'] for s in context['sources'].values()}),operations=len(context['graph']['operations']),dependencies=len(context['graph']['dependencies']),
   oversize_retained=any(s['repository']=='orders' and s['path']=='oversize.md' for s in context['sources'].values()),effective_limits=x.policy.limits.model_dump())
  assert result['coverage']=='PARTIAL' and result['gap_counts']=={'file_limit':1} and not result['oversize_retained'] and result['files_read']>0
  cases.append(result)
 target.write_text(json.dumps(dict(provenance='authored_resource_control_not_quality_case',source_sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),core_identity=core_identity(),oversize_bytes=65_537,cases=cases,passed=True),indent=2)+'\n')
 print(json.dumps(dict(status='PASS',modes=[c['mode'] for c in cases],coverage=[c['coverage'] for c in cases])))
finally:x.doCleanups()
