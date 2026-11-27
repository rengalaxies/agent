"""Forty correlated AUTHOR DEVELOPMENT fixtures, never independent human cases."""
from __future__ import annotations
import argparse
import copy
from pathlib import Path
import subprocess
from examples.orders_reporting.stand import _git,_tree,git_env
from .packets import curator_manifest,write_packet
from .common import EVAL,Registry,canonical,digest,read,sha,validate,write


def _api(route,default=20,body=None):
    return f'from fastapi import FastAPI\napp = FastAPI()\n\n@app.get("{route}")\ndef items(page_size: int = {default}, page: int = 1):\n    '+(body or 'return list(range(20))[(page-1)*page_size:page*page_size]')+'\n'


def build_cases(output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False);catalogue=[]
    home=output/'git-home';home.mkdir();(home/'gitconfig').write_text('');env=git_env(home)
    for i in range(40):
        cid=f'DEV-{i+1:04d}';root=output/'inputs'/cid;root.mkdir(parents=True)
        route=f'/v{i+1}/items';task=f'Review GET {route} change.';hints=True
        before={'api.py':_api(route)};after={'api.py':_api(route,10)}
        client=f'import requests\n\ndef consume():\n    return requests.get("https://dev-provider.test{route}").json()\n'
        if i<10:
            group='delete_operation';stratum='BREAKING_IN_PROFILE';after={'api.py':'from fastapi import FastAPI\napp = FastAPI()\n'}
        elif i<20:group='decrease_default';stratum='BREAKING_IN_PROFILE'
        elif i<24:
            group='irrelevant_change';stratum='COMPATIBLE_IN_PROFILE';after={**before,'README.md':'Editorial wording.\n'}
            if i>=22:hints=False;task='Review README wording.'
        elif i<27:
            group='explicit_page_size';stratum='COMPATIBLE_IN_PROFILE';client=client.replace(').json()',', params={"page_size": 40}).json()')
        elif i<30:
            group='paginated_explicit_size';stratum='COMPATIBLE_IN_PROFILE'
            client=f'import requests\n\ndef consume():\n    rows = []\n    for page in range(1, 5):\n        rows.extend(requests.get("https://dev-provider.test{route}", params={{"page": page, "page_size": 10}}).json())\n    return rows\n'
        elif i<34:
            group='no_consumer_delete' if i<32 else 'no_consumer_default';stratum='NO_CONSUMERS_IN_PROFILE'
            client='def unrelated(value):\n    return value + 1\n'
            if i<32:after={'api.py':'from fastapi import FastAPI\napp = FastAPI()\n'}
        else:
            stratum='OUT_OF_PROFILE';group=['external_helper','httpx','dynamic_url','openapi_ref','unavailable_provider','unavailable_consumer'][i-34]
            if i==34:
                before={'api.py':'from helper import build_page\n'+_api(route,body='return build_page()'),'helper.py':'def build_page():\n    return list(range(20))\n'}
                after={**before,'helper.py':'def build_page():\n    return list(range(10))\n'}
            elif i==35:client=client.replace('requests','httpx')
            elif i==36:client='import requests\nimport os\n\ndef consume():\n    return requests.get(os.environ["REMOTE_URL"]).json()\n'
            elif i==37:
                spec=dict(openapi='3.0.0',paths={route:{'$ref':'#/components/pathItems/items'}},components=dict(pathItems=dict(items=dict(get=dict(responses={'200':{'description':'ok'}})))))
                before={'api.json':canonical(spec)};changed=copy.deepcopy(spec);changed['components']['pathItems']['items']['get']['responses']['200']['description']='changed';after={'api.json':canonical(changed)}
        commits={};paths={}
        for rid,basefiles,headfiles in [('provider',before,after),('consumer',{'client.py':client},{'client.py':client})]:
            repo=root/'repositories'/rid;repo.mkdir(parents=True);paths[rid]=repo
            subprocess.run(['git','init','-q','--initial-branch=main',str(repo)],env=env,check=True,capture_output=True)
            _git(repo,env,'config','core.autocrlf','false')
            tree=_tree(repo,env,basefiles);base=_git(repo,env,'commit-tree',tree,'-m',cid+' '+rid+' base');_git(repo,env,'update-ref','refs/heads/main',base)
            tree=_tree(repo,env,headfiles);head=_git(repo,env,'commit-tree',tree,'-p',base,'-m',cid+' '+rid+' head');_git(repo,env,'update-ref','refs/heads/head',head)
            commits[rid]=(base,head)
        repos=[]
        for rid in paths:
            path=paths[rid]
            if i==38 and rid=='provider' or i==39 and rid=='consumer':path=root/'unavailable'/rid
            repos.append(dict(id=rid,service=rid,root=str(path.resolve()),snapshot='git',revision=commits[rid][1],include=['*.py','*.json','*.md'],allowed_refs=['refs/heads/*']))
        policy=dict(installation_id='author-development',environment='offline',subject='author-evaluation',capabilities=['read_context','maintain','propose','report_check'],
                    repositories=repos,addresses=[dict(service='provider',base_url='https://dev-provider.test')])
        write(root/'policy.json',policy)
        case=read(EVAL/'templates/case-input.template.json');case.update(lifecycle='ready',case_id=cid,task=task,
            repositories=[dict(repository_id=rid,service=rid,role=rid,source_ref=rid,base_sha=commits[rid][0],head_sha=commits[rid][1],tree_sha256='0'*64,read_authorized=True) for rid in paths],
            operation_hints=[dict(provider_service='provider',method='GET',route=route,basis_kind='task_text',basis_artifact_sha256=sha(task.encode()))] if hints else [],
            policy_sha256=sha((root/'policy.json').read_bytes()),budget=dict(wall_time_cap_seconds=60,freeze_manifest_ref='AUTHOR-DEVELOPMENT-NOT-REGISTERED'))
        registry=Registry(case,policy)
        manifests=output/'author-manifests'/cid;manifests.mkdir(parents=True)
        for r in case['repositories']:
            rid=r['repository_id'];snapshots=[('base',commits[rid][0]),('head',commits[rid][1])] if rid=='provider' else [('head',commits[rid][1])]
            rows=curator_manifest(paths[rid].resolve(),snapshots)
            raw=canonical(rows).encode();(manifests/(rid+'.json')).write_bytes(raw);r['tree_sha256']=sha(raw)
        case['input_packet_sha256']=write_packet(root/'input-packet.tar',case,(root/'policy.json').read_bytes(),registry);validate('case-input',case);write(root/'case.json',case)
        label=read(EVAL/'templates/reference-label.template.json');label.update(case_id=cid,stage='adjudicated',
            profile=dict(membership='OUT_OF_PROFILE' if i>=34 else 'IN_PROFILE',boundary=('access' if i>=38 else 'semantics' if i==34 else 'grammar') if i>=34 else 'none',rationale='Authored synthetic development fixture, not expert judgment'),
            scope_completeness=dict(search_complete=i<34,inventory_sha256=digest([r['tree_sha256'] for r in case['repositories']]),rationale='Known generated toy inventory; not an independent search'))
        key=dict(provider_service='provider',method='GET',route=route,consumer_service='consumer')
        contracts=output/'author-contracts';contracts.mkdir(exist_ok=True)
        contract_path=contracts/(cid+'.json');write(contract_path,dict(case_id=cid,provenance='controlled_author_requirement',required_rows=20,base_default=20,head_default=10,endpoint_required=True,real_expert_attestation=False))
        if i<34:
            witness=[]
            if i<30:
                line=next(n for n,l in enumerate(client.splitlines(),1) if 'requests.get(' in l)
                witness=[registry.witness('consumer','head',commits['consumer'][1],'client.py',line,line)]
            label['keys']=[dict(key=key,label='AFFECTED' if i<20 else 'UNAFFECTED',rationale='Authored contract expectation; not independent evidence',
                expectation=dict(description='Toy consumer requires endpoint and complete twenty-item response under specified parameters',artifact_ref='../author-contracts/'+cid+'.json',artifact_sha256=sha(contract_path.read_bytes()),basis='owner_requirement') if i<20 else None,witnesses=witness)]
        # Never fill human identity, timestamp or attestation. Draft is mandatory.
        validate('reference-label',label);oracle=output/'author-oracles';oracle.mkdir(exist_ok=True);write(oracle/(cid+'.json'),label)
        catalogue.append(dict(case_id=cid,stratum=stratum,origin_group=group,provenance='controlled_author',split='development'))
    write(output/'author-catalogue.json',catalogue);return catalogue


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);a=p.parse_args();build_cases(a.output)


if __name__=='__main__':main()
