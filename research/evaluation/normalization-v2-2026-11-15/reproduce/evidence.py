"""Author diagnostics only. Run from repository root; never edits historical data."""
from pathlib import Path
import argparse,ast,copy,json,shutil,subprocess,types
from agent_graph import core_identity
from tools.impactmap_eval.common import Registry,canonical,digest,load_input,read,sha,write
from tools.impactmap_eval.normalizer import normalize_core
from tools.impactmap_eval.registration import components
from tools.impactmap_eval.scoring import aggregate,score_case

BASE='0841a90de3be4860bdb92d9ff9531ac2776f4409'
OLD=Path('experiments/impactmap_scale/removal-2026-11-15/quality')
CORPUS=Path('work/batch06/development-v2')
REPORT=Path('research/evaluation/normalization-v2-2026-11-15')
METHODS=('impactmap_static','lexical_search_ls1')

def old_bytes(path):return subprocess.check_output(['git','show',f'{BASE}:{path}'])
def v1():
    module=types.ModuleType('tools.impactmap_eval._frozen_v1');module.__package__='tools.impactmap_eval'
    exec(compile(old_bytes('tools/impactmap_eval/normalizer.py'),'frozen-normalizer-v1','exec'),module.__dict__)
    return module.normalize_core

def source_identity():
    files=subprocess.check_output(['git','ls-tree','-r','--name-only',BASE],text=True).splitlines()
    protected=[p for p in files if p.startswith(('src/','research/evaluation/','experiments/impactmap_scale/')) or p=='tools/impactmap_eval/scoring.py']
    hashes={p:sha(old_bytes(p)) for p in protected}
    assert all(sha(Path(p).read_bytes())==h for p,h in hashes.items()),'historical_or_core_bytes_changed'
    def lexical(raw):
        node=next(n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='lexical')
        return ast.dump(node,include_attributes=False)
    assert lexical(old_bytes('tools/impactmap_eval/runner.py'))==lexical(Path('tools/impactmap_eval/runner.py').read_bytes())
    return dict(base=BASE,source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
                components=components(),core_identity=core_identity(),protected_sha256=hashes,ls1_function_ast_unchanged=True)

def replay(target):
    target.mkdir(parents=True,exist_ok=False)
    write(target/'source-identity.json',source_identity())
    first=v1();records={'v1':[],'v2':[]};rows=[];catalogue=read(CORPUS/'author-catalogue.json')
    # Only input/registry is opened during normalization. Authored labels opened afterwards.
    for rawpath in sorted((OLD/'raw-core').glob('DEV-*.json')):
        cid=rawpath.stem;root=CORPUS/'inputs'/cid;case,policy,registry=load_input(root/'case.json',root/'policy.json')
        envelope=read(rawpath);raw=json.loads(envelope['payload_utf8']);raw_sha=sha(rawpath.read_bytes())
        saved=read(OLD/'normalized'/cid/'impactmap_static.json')
        out=target/'normalized'/cid;out.mkdir(parents=True)
        left=first(raw,case,registry,configuration=saved['configuration_sha256'],raw_sha=raw_sha)
        if envelope['error_code']:left.update(output_valid=False,status='FAILED',error_code=envelope['error_code'])
        assert left==saved,('v1_replay_differs_from_saved',cid)
        right=normalize_core(raw,case,registry,configuration=digest(dict(components=components(),kind='same_raw_replay',case_id=cid)),raw_sha=raw_sha)
        if envelope['error_code']:right.update(output_valid=False,status='FAILED',error_code=envelope['error_code'])
        write(out/'v1.json',left);write(out/'v2.json',right)
        semantic=lambda p:{k:v for k,v in p.items() if k!='configuration_sha256'}
        rows.append(dict(case_id=cid,raw_ref=str(rawpath),raw_sha256=raw_sha,payload_sha256=sha(envelope['payload_utf8'].encode()),
                         v1_matches_saved=True,semantic_changed=semantic(left)!=semantic(right)))
    assert len(rows)==40 and len({r['case_id'] for r in rows})==40
    for row in rows:
        cid=row['case_id'];root=CORPUS/'inputs'/cid;_,_,registry=load_input(root/'case.json',root/'policy.json')
        gold=read(CORPUS/'author-oracles'/(cid+'.json'))
        for version in records:records[version].append(score_case(read(target/'normalized'/cid/(version+'.json')),gold,registry,development=True))
    write(target/'comparison.json',dict(kind='SAME_FROZEN_RAW_RENORMALIZATION_NOT_NEW_ATTEMPTS',cases=rows,
          methods={v:aggregate(r,catalogue) for v,r in records.items()}))
    fixtures(target/'fixtures',first)
    historical_diagnostic(target/'historical-diagnostic',first)

def fixtures(target,first):
    from tests.performance.normalization_fixture import BindingFixture
    target.mkdir();index=[]
    variants=[('single',('/orders',),{}),('merged',('/orders','/invoices'),{}),('self-service',('/orders',),{'self_service':True}),('no-proof',('/orders',),{}),('bad-blob',('/orders',),{})]
    for name,routes,kwargs in variants:
        fixture=BindingFixture(routes,**kwargs)
        try:
            raw=copy.deepcopy(fixture.raw)
            if name=='no-proof':raw.update(checks=[],claims=[])
            if name=='bad-blob':
                for e in raw['evidence']:
                    if e['repository']=='c':e['blob']='0'*40
            folder=target/name;folder.mkdir();write(folder/'raw.json',raw)
            left=first(raw,fixture.case,fixture.registry,configuration='1'*64,raw_sha=sha((folder/'raw.json').read_bytes()))
            right=normalize_core(raw,fixture.case,fixture.registry,configuration='2'*64,raw_sha=sha((folder/'raw.json').read_bytes()))
            assert left['output_valid'] and right['output_valid'],name
            expected=sorted(routes) if name not in ('no-proof',) else []
            if name=='bad-blob':assert not any(c['witnesses'] for c in right['candidates'])
            else:assert sorted(c['key']['route'] for c in right['candidates'])==expected
            if name=='no-proof':assert len(right['invalid_candidates'])==1
            write(folder/'v1.json',left);write(folder/'v2.json',right)
            write(folder/'input.json',dict(case=fixture.case,policy=fixture.registry.policy.model_dump(),
                sources=[dict(repository=k[0],phase=k[1],commit=k[2],path=k[3],text=s['text'],sha256=s['sha256']) for k,s in fixture.registry.sources.items()]))
            index.append(dict(name=name,provenance='AUTHORED_REGRESSION_NOT_ADDITIONAL_EVALUATION_CASE',
                v1_routes=[c['key']['route'] for c in left['candidates']],v2_routes=[c['key']['route'] for c in right['candidates']],
                v2_unbound=len(right['invalid_candidates']),v2_witnesses=sum(len(c['witnesses']) for c in right['candidates'])))
        finally:fixture.close()
    write(target/'index.json',index)

def historical_diagnostic(target,first):
    path=Path('experiments/impactmap_scale/removal-2026-11-15/replacement-diagnostic/output.json')
    raw=read(path);assert 'schema_id' in raw and 'schema' not in raw
    slots={}
    for s in raw['snapshots']:slots.setdefault(s['repository'],{})[s['role']]=s['commit']
    repos=[]
    for rid,phases in slots.items():
        head=phases.get('head',phases.get('consumer'));repos.append(dict(repository_id=rid,role='provider' if rid=='orders' else 'consumer',service=rid,source_ref=rid,read_authorized=True,base_sha=phases.get('base',head),head_sha=head))
    case=dict(case_id='DEV-REPLACEMENT',repositories=repos)
    policy=dict(installation_id=raw['installation_id'],environment=raw['environment'],subject='operator',capabilities=['maintain','read_context'],
        repositories=[dict(id=r['repository_id'],service=r['service'],root=str(Path('work/batch05-removal/replacement-diagnostic/corpus').resolve()/r['repository_id']),snapshot='git',revision=r['head_sha']) for r in repos],
        addresses=[dict(service='orders',base_url='https://orders.test')])
    registry=Registry(case,policy);target.mkdir()
    for version,fn in [('v1',first),('v2',normalize_core)]:
        p=fn(raw,case,registry,configuration='1'*64,raw_sha=sha(path.read_bytes()))
        assert not p['output_valid'] and p['error_code']=='invalid_analysis_document'
        write(target/(version+'.json'),p)
    write(target/'disclosure.json',dict(original_ref=str(path),original_sha256=sha(path.read_bytes()),
        serialization_defect='schema_id instead of schema; original remains immutable',both_versions_output_invalid=True,
        counts_as_evaluation_case=False,quality_credit=False))

def publish(campaign,target):
    target.mkdir(parents=True,exist_ok=False)
    for name in ('campaign-manifest.json','candidate-freeze.json','readiness.json','summary.json','receipts.json'):shutil.copy2(campaign/name,target/name)
    old=read(OLD/'campaign-manifest.json');new=read(campaign/'campaign-manifest.json')
    for key in ('seed','method_case_order','inputs_sha256','wall_time_cap_seconds'):assert old[key]==new[key],key
    assert new['components']==components() and new['core_identity']==core_identity()
    refs=[]
    for row in new['method_case_order']:
        cid,method=row['case_id'],row['method'];origin=campaign/'attempts'/cid/method
        out=target/'normalized'/cid;out.mkdir(parents=True,exist_ok=True)
        shutil.copy2(origin/'normalized.json',out/(method+'.json'))
        dest=target/'receipts'/cid;dest.mkdir(parents=True,exist_ok=True);shutil.copy2(origin/'receipt.json',dest/(method+'.json'))
        receipt=read(origin/'receipt.json');assert sha((origin/'raw.json').read_bytes())==receipt['raw_artifact_sha256']
        if method=='impactmap_static':
            folder=target/'raw-core';folder.mkdir(exist_ok=True);shutil.copy2(origin/'raw.json',folder/(cid+'.json'))
        refs.append(dict(case_id=cid,method=method,private_raw_ref=str(origin/'raw.json'),raw_sha256=receipt['raw_artifact_sha256']))
    assert len(refs)==80 and len({(r['case_id'],r['method']) for r in refs})==80
    write(target/'raw-index.json',refs)
    write(target/'comparison.json',dict(same_seed_order_inputs_cap=True,post_tuning=True,
        previous_summary_ref=str(OLD/'summary.json'),previous=read(OLD/'summary.json')['methods'],current=read(campaign/'summary.json')['methods']))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('mode',choices=['replay','publish','historical']);parser.add_argument('--target',type=Path,required=True);parser.add_argument('--campaign',type=Path)
    args=parser.parse_args()
    if args.mode=='replay':replay(args.target)
    elif args.mode=='historical':historical_diagnostic(args.target,v1())
    else:publish(args.campaign,args.target)
