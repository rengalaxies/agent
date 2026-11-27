"""Portable hash/ledger checks; optional current-code and private-label rescoring."""
from pathlib import Path
import argparse,json,sys
import hashlib

REPORT=Path(__file__).resolve().parents[1]
ROOT=REPORT.parents[2]
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def require(ok,label):
    if not ok:raise ValueError(label)

def verify(*,private=False,current=False):
    index=read(REPORT/'artifact-hashes.json')
    actual={str(p.relative_to(REPORT)) for p in REPORT.rglob('*') if p.is_file() and p.name!='artifact-hashes.json' and '__pycache__' not in p.parts}
    require(actual==set(index),'artifact_set_mismatch')
    for path,h in index.items():require(sha(REPORT/path)==h,'artifact_hash:'+path)
    identity=read(REPORT/'replay/source-identity.json')
    for path,h in identity['protected_sha256'].items():require(sha(ROOT/path)==h,'historical_or_core_changed:'+path)
    q=REPORT/'author-v2';manifest=read(q/'campaign-manifest.json');receipts=read(q/'receipts.json')
    ids={f'DEV-{i:04d}' for i in range(1,41)};methods={'impactmap_static','lexical_search_ls1'}
    expected={(cid,m) for cid in ids for m in methods}
    require(len(receipts)==80 and {(r['case_id'],r['method']) for r in receipts}==expected,'assigned_receipt_set')
    order=manifest['method_case_order'];require(len(order)==80 and {(r['case_id'],r['method']) for r in order}==expected and all(r['attempt_id']==1 for r in order),'assigned_order')
    old=read(ROOT/'experiments/impactmap_scale/removal-2026-11-15/quality/campaign-manifest.json')
    for key in ('seed','method_case_order','inputs_sha256','wall_time_cap_seconds'):require(manifest[key]==old[key],'changed_assignment:'+key)
    require(manifest['components']==identity['components'] and manifest['core_identity']==identity['core_identity'],'campaign_snapshot')
    require(manifest['post_tuning'] and manifest['human_experts']==manifest['independent_cases']==0,'development_status')
    require(len(list((q/'raw-core').glob('DEV-*.json')))==40,'raw_core_count')
    rawindex=read(q/'raw-index.json');require(len(rawindex)==80 and {(r['case_id'],r['method']) for r in rawindex}==expected,'raw_index_set')
    for r in receipts:
        cid,m=r['case_id'],r['method'];norm=q/'normalized'/cid/(m+'.json');p=read(norm)
        require(read(q/'receipts'/cid/(m+'.json'))==r,'receipt_copy')
        require(sha(norm)==r['normalized_sha256'] and p['raw_artifact_sha256']==r['raw_artifact_sha256'],'receipt_hash')
        require(r['attempt']=={'id':1,'kind':'primary'} and r['development'] and not r['gold_received'],'attempt_semantics')
        if m=='impactmap_static':
            raw=q/'raw-core'/(cid+'.json');envelope=read(raw)
            require(sha(raw)==r['raw_artifact_sha256'],'raw_core_hash')
            require(hashlib.sha256(envelope['payload_utf8'].encode()).hexdigest()==envelope['payload_sha256'],'payload_hash')
    for summary in (read(q/'summary.json'),):
        require(summary['independent_research_status']=='NOT_REGISTERED / NOT_RUN' and summary['real_experts']==0 and summary['authored_cases']==40,'summary_status')
    rows=read(REPORT/'replay/comparison.json')['cases'];require(len(rows)==40 and {r['case_id'] for r in rows}==ids,'replay_set')
    for row in rows:require(sha(ROOT/row['raw_ref'])==row['raw_sha256'],'old_raw_hash')
    disclosure=read(REPORT/'replay/historical-diagnostic/disclosure.json')
    require(sha(ROOT/disclosure['original_ref'])==disclosure['original_sha256'],'old_diagnostic_hash')
    for v in ('v1','v2'):
        p=read(REPORT/'replay/historical-diagnostic'/(v+'.json'));require(not p['output_valid'] and p['error_code']=='invalid_analysis_document','invalid_diagnostic_not_credited')
    if current or private:
        sys.path[:0]=[str(ROOT/'src'),str(ROOT)]
        from agent_graph import core_identity
        from tools.impactmap_eval.registration import components
        require(components()==identity['components'] and core_identity()==identity['core_identity'],'current_tools_changed')
        from tools.impactmap_eval.common import Registry
        from tools.impactmap_eval.normalizer import normalize_core
        fixture_index=read(REPORT/'replay/fixtures/index.json')
        require({r['name'] for r in fixture_index}=={'single','merged','self-service','no-proof','bad-blob'},'fixture_set')
        for row in fixture_index:
            folder=REPORT/'replay/fixtures'/row['name'];data=read(folder/'input.json');registry=Registry.__new__(Registry)
            registry.repos={r['repository_id']:r for r in data['case']['repositories']};registry.sources={}
            for source in data['sources']:
                text=source['text'].encode();require(hashlib.sha256(text).hexdigest()==source['sha256'],'fixture_source_hash')
                blob=hashlib.sha1(b'blob '+str(len(text)).encode()+b'\0'+text).hexdigest()
                key=(source['repository'],source['phase'],source['commit'],source['path']);registry.sources[key]={**source,'blob':blob}
            p=read(folder/'v2.json');again=normalize_core(read(folder/'raw.json'),data['case'],registry,configuration=p['configuration_sha256'],raw_sha=p['raw_artifact_sha256'])
            require(again==p,'fixture_renormalization:'+row['name'])
    if private:
        from tools.impactmap_eval.common import load_input,read as jsonread
        from tools.impactmap_eval.scoring import aggregate,score_case
        from tools.impactmap_eval.normalizer import normalize_core
        corpus=ROOT/'work/batch06/development-v2';records={m:[] for m in methods};replay_records={v:[] for v in ('v1','v2')}
        for cid in sorted(ids):
            folder=corpus/'inputs'/cid;case,policy,registry=load_input(folder/'case.json',folder/'policy.json');reference=jsonread(corpus/'author-oracles'/(cid+'.json'))
            require(sha(folder/'case.json')==manifest['inputs_sha256'][cid],'private_input_hash')
            require(sha(corpus/'author-oracles'/(cid+'.json'))==sha(ROOT/'research/evaluation/batch06/author-oracles'/(cid+'.json')),'author_oracle_changed')
            require(not reference['attestation']['confirmed_by_human'] and not reference['attestation']['independent_before_outputs'],'author_labels_only')
            for method in methods:
                p=read(q/'normalized'/cid/(method+'.json'));records[method].append(score_case(p,reference,registry,development=True))
                row=next(r for r in rawindex if (r['case_id'],r['method'])==(cid,method));require(sha(ROOT/row['private_raw_ref'])==row['raw_sha256'],'private_raw_hash')
                if method=='impactmap_static':
                    envelope=read(q/'raw-core'/(cid+'.json'));again=normalize_core(json.loads(envelope['payload_utf8']),case,registry,configuration=p['configuration_sha256'],raw_sha=p['raw_artifact_sha256'])
                    if envelope['error_code']:again.update(output_valid=False,status='FAILED',error_code=envelope['error_code'])
                    require(again==p,'fresh_normalization_replay:'+cid)
            for v in replay_records:
                p=read(REPORT/'replay/normalized'/cid/(v+'.json'));replay_records[v].append(score_case(p,reference,registry,development=True))
            original=read(ROOT/'experiments/impactmap_scale/removal-2026-11-15/quality/raw-core'/(cid+'.json'))
            p=read(REPORT/'replay/normalized'/cid/'v2.json');again=normalize_core(json.loads(original['payload_utf8']),case,registry,configuration=p['configuration_sha256'],raw_sha=p['raw_artifact_sha256'])
            if original['error_code']:again.update(output_valid=False,status='FAILED',error_code=original['error_code'])
            require(again==p,'old_raw_v2_normalization:'+cid)
        catalogue=jsonread(corpus/'author-catalogue.json');summary=read(q/'summary.json')
        for m,rs in records.items():require(aggregate(rs,catalogue)==summary['methods'][m],'fresh_rescore:'+m)
        replay=read(REPORT/'replay/comparison.json')
        for v,rs in replay_records.items():require(aggregate(rs,catalogue)==replay['methods'][v],'replay_rescore:'+v)
    return dict(status='PASS',hashed_artifacts=len(index),historical_and_core_files=len(identity['protected_sha256']),assigned_attempts=80,replayed_core_outputs=40,private_rescoring=private,current_tools=current or private)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--private',action='store_true');p.add_argument('--current-tools',action='store_true');a=p.parse_args()
    print(json.dumps(verify(private=a.private,current=a.current_tools),sort_keys=True))
