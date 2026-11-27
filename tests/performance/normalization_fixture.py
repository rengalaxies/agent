"""Small authored pinned Graph/result fixture; no gold or real participant."""
from pathlib import Path
import subprocess,tempfile
from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.output_contracts import parse_document,dump_document
from agent_graph.results import change_result
from agent_graph.store import Store
from tools.impactmap_eval.common import Registry

class BindingFixture:
    def __init__(self,routes=('/orders',),*,replacement=True,same_line=False,self_service=False):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        for name in ('p','c'):(self.root/name).mkdir()
        setup='from fastapi import FastAPI\napp = FastAPI()\n'
        api=setup+''.join(f'@app.get("{route}")\ndef handler_{i}():\n    return []\n' for i,route in enumerate(routes))
        (self.root/'p/api.py').write_text(api)
        calls=[f'requests.get("https://provider.test{route}")' for route in routes]
        (self.root/'c/client.py').write_text('import requests\n'+(' ; '.join(calls) if same_line else '\n'.join(calls))+'\n')
        def git(name,*args):return subprocess.check_output(['git','-C',str(self.root/name),*args],text=True,stderr=subprocess.DEVNULL).strip()
        base={}
        for name in ('p','c'):
            git(name,'init','-b','main');git(name,'add','.')
            git(name,'-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-m','base')
            base[name]=git(name,'rev-parse','HEAD')
        (self.root/'p/api.py').write_text(setup+('@app.get("/{resource}")\ndef generic():\n    return []\n' if replacement else ''))
        git('p','add','.');git('p','-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-m','head')
        head={**base,'p':git('p','rev-parse','HEAD')}
        policy=Policy.model_validate(dict(installation_id='binding-test',environment='test',subject='operator',capabilities=['maintain','read_context'],
            repositories=[dict(id=n,service='p' if self_service else n,root=str(self.root/n),revision=head[n],snapshot='git') for n in ('p','c')],
            addresses=[dict(service='p',base_url='https://provider.test')]))
        self.case=dict(case_id='DEV-BINDING',repositories=[dict(repository_id=n,role='provider' if n=='p' else 'consumer',service='p' if self_service else n,source_ref=n,read_authorized=True,base_sha=base[n],head_sha=head[n]) for n in ('p','c')])
        self.registry=Registry(self.case,policy.model_dump())
        self.store=Store(self.root/'state');graph=Graph(policy,self.store)
        context=graph.prepare_context(revisions=base);analysis=graph.analyze_change(context['id'],revisions=head)
        request=parse_document(dict(schema='agent-graph-output',schema_version='2.0',kind='analysis_request',installation_id='binding-test',environment='test',request_id='binding',trigger_kind='pr',
            source_event=dict(event_id='binding',resource_version='v1'),repository_revisions=head,graph_version='graph-1',constitution_version='agent-service-v1.0:binding-test',model_configuration_id=None,
            deadline='2099-01-01T00:00:00Z',access_scope=dict(view_id=graph.view,repositories=['p','c']),pr=dict(provider='github',repository='p',pr_id=1,base_sha=base['p'],head_sha=head['p'])))
        self.raw=dump_document(change_result(graph,request,analysis,code_version='binding-fixture',constitution_version=request.constitution_version,correlation_id='binding'))
    def close(self):self.store.close();self.tmp.cleanup()
