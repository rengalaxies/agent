"""Run author development inputs first, then open authored oracles for scoring."""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import random
from agent_graph import core_identity
from .common import canonical,load_input,read,sha,write
from .registration import candidate_freeze,components,readiness
from .runner import run_method
from .scoring import aggregate,paired,score_case


def calibrate(corpus,output,*,post_tuning=False):
    corpus=Path(corpus);output=Path(output);output.mkdir(parents=True,exist_ok=False)
    # IDs only. Neither catalogue strata nor reference files are read before runs.
    inputs=sorted((corpus/'inputs').glob('*/case.json'))
    ids=[read(p)['case_id'] for p in inputs]
    order=[dict(case_id=cid,method=m,attempt_id=1) for cid in ids for m in ('impactmap_static','lexical_search_ls1')]
    random.Random(20261114).shuffle(order)
    snapshot=components();core_snapshot=core_identity()
    manifest=dict(status='AUTHOR_DEVELOPMENT_NOT_REGISTERED',seed=20261114,method_case_order=order,components=snapshot,
        post_tuning=post_tuning,normalization_version=snapshot['normalization_version'],protocol_ref='research/evaluation/protocol-v2.md',
        core_identity=core_snapshot,
        inputs_sha256={read(p)['case_id']:sha(p.read_bytes()) for p in inputs},wall_time_cap_seconds=60,
        human_experts=0,independent_cases=0,source_execution=False)
    write(output/'campaign-manifest.json',manifest)
    receipts=[]
    for assignment in order:
        cid,m=assignment['case_id'],assignment['method'];root=corpus/'inputs'/cid;target=output/'attempts'/cid/m
        receipt=run_method(root/'case.json',root/'policy.json',m,target,development=True)
        receipts.append(receipt)
        print(canonical(dict(case_id=cid,method=m,error_code=receipt['error_code'])),flush=True)
    if components()!=snapshot or core_identity()!=core_snapshot:raise ValueError('tooling_changed_during_campaign')
    # First access to authored labels is after all primary attempts exist.
    catalogue=read(corpus/'author-catalogue.json');records={m:[] for m in ('impactmap_static','lexical_search_ls1')}
    for cid in ids:
        root=corpus/'inputs'/cid;case,policy,registry=load_input(root/'case.json',root/'policy.json')
        reference=read(corpus/'author-oracles'/(cid+'.json'))
        if reference['lifecycle']!='draft' or reference['attestation']['confirmed_by_human'] or reference['attestation']['independent_before_outputs']:
            raise ValueError('author_fixture_cannot_claim_human_gold')
        for m in records:
            run=output/'attempts'/cid/m;p=read(run/'normalized.json');receipt=read(run/'receipt.json')
            if sha((run/'raw.json').read_bytes())!=p['raw_artifact_sha256'] or sha((run/'normalized.json').read_bytes())!=receipt['normalized_sha256']:
                raise ValueError('result_artifact_hash_mismatch')
            records[m].append(score_case(p,reference,registry,development=True))
    reports={m:aggregate(r,catalogue) for m,r in records.items()}
    freeze=candidate_freeze();write(output/'candidate-freeze.json',freeze);write(output/'readiness.json',readiness(freeze))
    summary=dict(status='AUTHOR_DIAGNOSTIC_ONLY',independent_research_status='NOT_REGISTERED / NOT_RUN',
        authored_cases=len(ids),real_experts=0,origin_groups=len({c['origin_group'] for c in catalogue}),
        strata=dict(Counter(c['stratum'] for c in catalogue)),methods=reports,comparison=paired(reports['impactmap_static'],reports['lexical_search_ls1']),
        disclosures=['Author created cases, expectations and tools; family copies correlated; not independent evidence.',
                     'No real project/expert/buyer represented. Human attestations remain false.',
                     ('Fixed 60s common cap and first assigned attempts; post-tuning development on already seen author cases.'
                      if post_tuning else 'Fixed 60s common cap and first assigned attempts; no post-hoc tuning of core.')])
    write(output/'summary.json',summary);write(output/'receipts.json',receipts)
    return summary


def main():
    p=argparse.ArgumentParser();p.add_argument('--corpus',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--post-tuning',action='store_true',help='Disclose reuse of author cases after development changes')
    a=p.parse_args();calibrate(a.corpus,a.output,post_tuning=a.post_tuning)


if __name__=='__main__':main()
