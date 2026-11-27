from pathlib import Path
import subprocess,json,hashlib,copy
from examples.orders_reporting.stand import _git,_tree,git_env
from tools.impactmap_eval.packets import curator_manifest,write_packet
from tools.impactmap_eval.common import EVAL,Registry,canonical,digest,read,sha,validate,write
output=Path('/private/tmp/impactmap-auditfix/corpus');output.mkdir(exist_ok=False)
home=output/'git-home';home.mkdir();(home/'gitconfig').write_text('');env=git_env(home)
def api(route,n):return f'from fastapi import FastAPI\napp = FastAPI()\n@app.get("{route}")\ndef entries(page_size: int = {n}, page: int = 1):\n    return list(range(60))[(page-1)*page_size:page*page_size]\n'
def client(route):return f'import requests\ndef consume():\n    return requests.get("https://dev-provider.test{route}").json()\n'
specs=[]
for i in range(10):
 route=f'/audit/{i+1}/records';before={'api.py':api(route,60)};after={'api.py':api(route,15)};c=client(route)
 if i==0:group='removed';after={'api.py':'from fastapi import FastAPI\napp = FastAPI()\n'};stratum='BREAKING_IN_PROFILE'
 elif i in (1,2):group='default_decrease';stratum='BREAKING_IN_PROFILE';c=c if i==1 else c.replace('.json()','.json()[:45]')
 elif i==3:group='explicit_limit';stratum='COMPATIBLE_IN_PROFILE';c=c.replace(').json()',', params={"page_size": 60}).json()')
 elif i==4:group='documentation_only';stratum='COMPATIBLE_IN_PROFILE';after={**before,'README.md':'Address '+route+' has new documentation.\n'}
 elif i==5:group='no_consumer';stratum='NO_CONSUMERS_IN_PROFILE';c='def local_rows():\n    return []\n'
 elif i==6:group='different_host';stratum='NO_CONSUMERS_IN_PROFILE';c=c.replace('dev-provider.test','another-provider.test')
 elif i==7:group='httpx';stratum='OUT_OF_PROFILE';c=c.replace('requests','httpx')
 elif i==8:group='dynamic_url';stratum='OUT_OF_PROFILE';c='import requests, os\ndef consume():\n    return requests.get(os.environ["REMOTE_URL"]).json()\n'
 else:group='missing_provider';stratum='OUT_OF_PROFILE'
 specs.append(dict(case_id=f'AUD-{i+1:04d}',route=route,group=group,stratum=stratum,before=before,after=after,client=c,expected='AFFECTED' if i<3 else 'UNAFFECTED' if i<7 else 'OUT_OF_PROFILE'))
write(output/'plan-before-run.json',dict(status='AUTHORED_TECHNICAL_DIAGNOSTIC',independent_cases=0,human_experts=0,source_snapshot='f50cdf255c5da36fcfc5882ffb1638c1348e190c',cases=specs,decision='Descriptive per-case assessment. Independent H1 and user-effect hypotheses remain open.',attempts='one first attempt per method, 60 seconds each; no product tuning'))
catalogue=[]
for spec in specs:
 cid=spec['case_id'];route=spec['route'];root=output/'inputs'/cid;root.mkdir(parents=True);commits={};paths={}
 for rid,basefiles,headfiles in [('provider',spec['before'],spec['after']),('consumer',{'client.py':spec['client']},{'client.py':spec['client']})]:
  repo=root/'repositories'/rid;repo.mkdir(parents=True);paths[rid]=repo
  subprocess.run(['git','init','-q','--initial-branch=main',str(repo)],env=env,check=True,capture_output=True)
  _git(repo,env,'config','core.autocrlf','false')
  base=_git(repo,env,'commit-tree',_tree(repo,env,basefiles),'-m',cid+' base');_git(repo,env,'update-ref','refs/heads/main',base)
  head=_git(repo,env,'commit-tree',_tree(repo,env,headfiles),'-p',base,'-m',cid+' head');_git(repo,env,'update-ref','refs/heads/head',head)
  commits[rid]=(base,head)
 repos=[dict(id=rid,service=rid,root=str((root/'unavailable'/rid if spec['group']=='missing_provider' and rid=='provider' else paths[rid]).resolve()),snapshot='git',revision=commits[rid][1],include=['*.py','*.md'],allowed_refs=['refs/heads/*']) for rid in paths]
 policy=dict(installation_id='audit-diagnostic',environment='offline',subject='author-evaluation',capabilities=['read_context','maintain','propose','report_check'],repositories=repos,addresses=[dict(service='provider',base_url='https://dev-provider.test')])
 write(root/'policy.json',policy);task=f'Review GET {route} change.'
 case=read(EVAL/'templates/case-input.template.json');case.update(lifecycle='ready',case_id=cid,task=task,repositories=[dict(repository_id=rid,service=rid,role=rid,source_ref=rid,base_sha=commits[rid][0],head_sha=commits[rid][1],tree_sha256='0'*64,read_authorized=True) for rid in paths],operation_hints=[dict(provider_service='provider',method='GET',route=route,basis_kind='task_text',basis_artifact_sha256=sha(task.encode()))],policy_sha256=sha((root/'policy.json').read_bytes()),budget=dict(wall_time_cap_seconds=60,freeze_manifest_ref='AUTHOR-AUDIT-NOT-REGISTERED'))
 registry=Registry(case,policy)
 for r in case['repositories']:
  rid=r['repository_id'];rows=curator_manifest(paths[rid].resolve(),[('base',commits[rid][0]),('head',commits[rid][1])] if rid=='provider' else [('head',commits[rid][1])]);r['tree_sha256']=sha(canonical(rows).encode())
 case['input_packet_sha256']=write_packet(root/'input-packet.tar',case,(root/'policy.json').read_bytes(),registry);validate('case-input',case);write(root/'case.json',case)
 label=read(EVAL/'templates/reference-label.template.json');label.update(case_id=cid,stage='adjudicated',profile=dict(membership='OUT_OF_PROFILE' if spec['stratum']=='OUT_OF_PROFILE' else 'IN_PROFILE',boundary='access' if spec['group']=='missing_provider' else 'grammar' if spec['stratum']=='OUT_OF_PROFILE' else 'none',rationale='Authored technical diagnostic declared before outputs'),scope_completeness=dict(search_complete=spec['stratum']!='OUT_OF_PROFILE',inventory_sha256=digest([r['tree_sha256'] for r in case['repositories']]),rationale='Controlled authored toy inventory'))
 contracts=output/'author-contracts';contracts.mkdir(exist_ok=True);contract=contracts/(cid+'.json');write(contract,dict(case_id=cid,required_rows=45 if cid=='AUD-0003' else 60,endpoint_required=True,provenance='authored_toy_requirement'))
 if spec['stratum']!='OUT_OF_PROFILE':
  witnesses=[]
  if 'requests.get' in spec['client']:
   line=next(i for i,l in enumerate(spec['client'].splitlines(),1) if 'requests.get' in l)
   witnesses=[registry.witness('consumer','head',commits['consumer'][1],'client.py',line,line)]
  label['keys']=[dict(key=dict(provider_service='provider',method='GET',route=route,consumer_service='consumer'),label=spec['expected'],rationale='Authored controlled requirement',expectation=dict(description='Endpoint must preserve required rows for this toy consumer',artifact_ref='../author-contracts/'+cid+'.json',artifact_sha256=sha(contract.read_bytes()),basis='owner_requirement') if spec['expected']=='AFFECTED' else None,witnesses=witnesses)]
 validate('reference-label',label);oracles=output/'author-oracles';oracles.mkdir(exist_ok=True);write(oracles/(cid+'.json'),label)
 catalogue.append(dict(case_id=cid,stratum=spec['stratum'],origin_group=spec['group'],provenance='controlled_author',split='development'))
write(output/'author-catalogue.json',catalogue)
print('Prepared',len(specs),'cases; expectations frozen before attempts')
