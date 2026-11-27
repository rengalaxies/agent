"""Authored diagnostic only: actual new call target vs old changed operation."""
from pathlib import Path
import json,os,subprocess
from agent_graph import core_identity
from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store
from agent_graph.results import change_result
from agent_graph.output_contracts import parse_document
from examples.agent_graph.fixture import create_fixture
from tools.impactmap_eval.common import Registry
from tools.impactmap_eval.normalizer import normalize_core
from tests.graph.test_removal_mapping import API,CALL
root=Path.cwd()/'work/batch05-removal/replacement-diagnostic';root.mkdir(exist_ok=False)
p=create_fixture(root)
(root/'corpus/orders/api.py').write_text(API)
(root/'corpus/reporting/client.py').write_text(CALL)
for name in ('health','export'):(root/'corpus'/name/'client.py').write_text('value = 1\n')
env={**os.environ,'GIT_AUTHOR_NAME':'ImpactMap authored diagnostic','GIT_AUTHOR_EMAIL':'fixture@example.invalid','GIT_COMMITTER_NAME':'ImpactMap authored diagnostic','GIT_COMMITTER_EMAIL':'fixture@example.invalid'}
def git(repo,*args):return subprocess.check_output(['git','-C',str(repo),*args],env=env,stderr=subprocess.DEVNULL,text=True).strip()
base={}
for r in p.repositories:
 git(r.root,'init','-b','main');git(r.root,'add','.');git(r.root,'commit','-m','authored base');base[r.id]=git(r.root,'rev-parse','HEAD')
(root/'corpus/orders/api.py').write_text(API.replace('/orders"','/{resource}"'))
git(root/'corpus/orders','add','.');git(root/'corpus/orders','commit','-m','authored replacement')
head={**base,'orders':git(root/'corpus/orders','rev-parse','HEAD')}
data=p.model_dump()
for r in data['repositories']:r['snapshot']='git';r['revision']=head[r['id']]
p=Policy.model_validate(data)
case=dict(case_id='DEV-REPLACEMENT',repositories=[dict(repository_id=r.id,role='provider' if r.id=='orders' else 'consumer',service=r.service,source_ref=r.id,read_authorized=True,base_sha=base[r.id],head_sha=head[r.id]) for r in p.repositories])
registry=Registry(case,p.model_dump())
store=Store(root/'private/state')
try:
 graph=Graph(p,store);b=graph.prepare_context(revisions=base);analysis=graph.analyze_change(b['id'],revisions=head)
 request=parse_document(dict(schema='agent-graph-output',schema_version='2.0',kind='analysis_request',installation_id=p.installation_id,environment=p.environment,request_id='replacement',trigger_kind='pr',source_event=dict(event_id='replacement',resource_version='v1'),repository_revisions=head,graph_version='graph-1',constitution_version='agent-service-v1.0:test',model_configuration_id=None,deadline='2026-11-16T12:00:00Z',access_scope=dict(view_id=graph.view,repositories=[r.id for r in p.repositories]),pr=dict(provider='github',repository='orders',pr_id=1,base_sha=base['orders'],head_sha=head['orders'])))
 result=change_result(graph,request,analysis,code_version='development-diagnostic',constitution_version='agent-service-v1.0:test',correlation_id='replacement').model_dump(mode='json')
 prediction=normalize_core(result,case,registry,configuration='1'*64)
 outcome=dict(status='KNOWN_NORMALIZATION_LIMITATION_REPRODUCED',provenance='authored_diagnostic_not_additional_independent_case',core_identity=core_identity(),old_delta_routes=[d['operation']['route'] for d in result['deltas']],current_call_routes=[r['target']['route'] for r in result['relationships']],risk_subject_routes=[c.get('subject',{}).get('route') for c in result['claims'] if c['kind']=='hypothesis'],normalized_routes=[c['key']['route'] for c in prediction['candidates']],unchanged_normalizer=True,not_in_author40=True)
 assert outcome['old_delta_routes']==['/orders'] and outcome['current_call_routes']==['/{resource}'] and outcome['risk_subject_routes']==['/orders'] and outcome['normalized_routes']==['/{resource}'],outcome
 for name,value in [('output.json',result),('normalized.json',prediction),('diagnostic.json',outcome)]: (root/name).write_text(json.dumps(value,indent=2)+'\n')
 print(json.dumps(outcome))
finally:store.close()
