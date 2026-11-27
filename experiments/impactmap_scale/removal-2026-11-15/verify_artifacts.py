"""Portable integrity/protocol checks; --private re-scores the same author inputs."""
from pathlib import Path
import argparse,hashlib,json
ROOT=Path(__file__).resolve().parents[3]
REPORT=Path(__file__).resolve().parent
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(private=False,current_core=False):
 hashes=read(REPORT/'artifact-hashes.json')
 for name,value in hashes.items():assert sha(REPORT/name)==value,name
 for name,value in read(REPORT/'historical-hashes.json').items():assert sha(ROOT/name)==value,name
 if current_core:
  for name,value in read(REPORT/'source-hashes.json').items():assert sha(ROOT/name)==value,name
 for label in ('repos5-lines50k','repos10-lines100k'):
  manifests=[]
  for phase in ('before-profile7','after-profile9'):
   folder=REPORT/'stages'/(phase+'-'+label);manifests.append(read(folder/'manifest.json'))
   rows=[json.loads(x) for x in (folder/'measurements.jsonl').read_text().splitlines()]
   assert len(rows)==3 and all(r['semantics_equal'] for r in rows)
   for r in rows:
    assert all(s['result']['status']=='USEFUL' and s['result']['findings']==3 for s in r['measured']['samples'])
    assert r['measured']['graph_relationships']=={'calls':3,'declares':8}
    assert all(c['coverage']=='COMPLETE_WITHIN_PROFILE' and c['dependencies']==3 and c['operations']==8 and not c['gap_counts'] for c in r['measured']['contexts'])
  for key in ('pins','limits','policy_without_roots_sha256','environment','model','cache_protocol'):assert manifests[0][key]==manifests[1][key],key
  assert not manifests[1]['source']['working_tree_dirty']
  baseline=read(REPORT/'baseline-code-receipt.json')
  assert manifests[0]['source']['core']['core_digest']==baseline['recomputed_git_core_digest']
  assert manifests[0]['source']['tool_sha256']==baseline['benchmark_sha256']
  assert manifests[0]['source']['core']['profile']=='http-requests-7' and manifests[1]['source']['core']['profile']=='http-requests-9'
 acceptance=REPORT/'acceptance';assert read(acceptance/'campaign.json')['passed']
 for n in (5,10):
  corpus=read(acceptance/('corpus-'+str(n))/'verification.json');assert corpus['verification_passed']
  assert corpus['removed_comparative_coverage']=='COMPLETE_WITHIN_PROFILE' and corpus['removed_head_coverage']=='PARTIAL'
  assert len(corpus['resolved_removed_calls'])==3
  eq=read(acceptance/('equivalence-'+str(n))/'result.json');assert eq['passed']
  deletion=next(c for c in eq['cases'] if c['scenario']=='operation_removed')
  assert deletion['coverage']=='PARTIAL' and deletion['counts']['gap_counts']=={'unmapped_call':3}
 assert read(acceptance/'defaults-5/result.json')['passed']
 blocked=read(acceptance/'defaults-10/result.json');assert blocked['error_code']=='corpus_limit' and blocked['analyzed_fraction']==0 and not blocked['passed']
 for case in ('queue-5-head10-burst','queue-10-pr1'):
  r=read(acceptance/case/'result.json');assert r['passed'] and r['restart_checked'] and r['all_results_expected'] and r['analyzed_jobs']==1
 q=REPORT/'quality';index=read(q/'raw-index.json');receipts={(r['case_id'],r['method']):r for r in read(q/'receipts.json')};assert len(index)==len(receipts)==80
 for item in index:
  receipt=receipts[item['case_id'],item['method']];norm=q.parent/item['normalized_file']
  assert sha(norm)==item['normalized_sha256']==receipt['normalized_sha256']
  assert read(norm)['raw_artifact_sha256']==item['raw_envelope_sha256']==receipt['raw_artifact_sha256']
  if item['exact_raw_file']:assert sha(REPORT/item['exact_raw_file'])==item['raw_envelope_sha256']
  if private:assert sha(ROOT/item['private_original'])==item['raw_envelope_sha256']
 old=read(ROOT/'research/evaluation/batch06/campaign-manifest.json');new=read(q/'campaign-manifest.json')
 for key in ('inputs_sha256','method_case_order','seed','wall_time_cap_seconds'):assert new[key]==old[key],key
 assert new['components']==read(ROOT/'research/evaluation/development-2026-11-15/campaign-manifest.json')['components']
 assert new['post_tuning'] and new['independent_cases']==new['human_experts']==0
 summary=read(q/'summary.json');assert summary['independent_research_status']=='NOT_REGISTERED / NOT_RUN' and summary['authored_cases']==40 and summary['real_experts']==0
 assert read(q/'readiness.json')['status']!='REGISTERED_READY'
 assert read(REPORT/'replacement-diagnostic/diagnostic.json')['status']=='KNOWN_NORMALIZATION_LIMITATION_REPRODUCED'
 if private:
  from tools.impactmap_eval.common import load_input
  from tools.impactmap_eval.scoring import score_case,aggregate
  corpus=ROOT/'work/batch06/development-v2';records={m:[] for m in summary['methods']}
  for cid in sorted(new['inputs_sha256']):
   source=corpus/'inputs'/cid;_,_,registry=load_input(source/'case.json',source/'policy.json')
   assert sha(source/'case.json')==new['inputs_sha256'][cid]
   oracle=corpus/'author-oracles'/(cid+'.json');assert oracle.read_bytes()==(ROOT/'research/evaluation/batch06/author-oracles'/(cid+'.json')).read_bytes()
   for method in records:records[method].append(score_case(read(q/'normalized'/cid/(method+'.json')),read(oracle),registry,development=True))
  catalogue=read(corpus/'author-catalogue.json')
  for method,values in records.items():assert aggregate(values,catalogue)==summary['methods'][method],method
 return dict(status='PASS',artifact_files=len(hashes),historical_files=len(read(REPORT/'historical-hashes.json')),workers=12,quality_receipts=80,private_rescoring=private,current_core_checked=current_core,review='PARTIAL_FRESH_THEN_AUTHOR_VERIFICATION',independent_research='NOT_RUN')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--private',action='store_true');p.add_argument('--current-core',action='store_true');a=p.parse_args();print(json.dumps(verify(a.private,a.current_core)))
