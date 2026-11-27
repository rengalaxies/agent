"""Integrity of default-path acceptance; no new analysis or network."""
from pathlib import Path
import argparse,hashlib,json
REPORT=Path(__file__).resolve().parent;ROOT=Path(__file__).resolve().parents[3]
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def verify(current=False,private=False):
 hashes=read(REPORT/'artifact-hashes.json')
 for name,value in hashes.items():assert sha(REPORT/name)==value,name
 for name,value in read(REPORT/'historical-hashes.json').items():assert sha(ROOT/name)==value,name
 if current:
  for name,value in read(REPORT/'source-hashes.json').items():assert sha(ROOT/name)==value,name
 campaign=read(REPORT/'campaign.json');assert campaign['passed']
 expected=dict(max_corpus_bytes=8_000_000,max_files=2048,max_file_bytes=65536,scan_seconds=60.0)
 assert len(campaign['stage_runs'])==2
 for run in campaign['stage_runs']:
  label=run['corpus'];folder=REPORT/'stages'/label
  assert run['input_limits_omitted'] and run['semantics_equal'] and run['previous_named_policy_facts_equal'] and run['previous_named_policy_results_equal']
  assert all(run['effective_limits'][k]==v for k,v in expected.items())
  public=read(folder/'input-without-roots.json');assert 'limits' not in public['policy']
  manifest=read(folder/'manifest.json');assert not manifest['source']['working_tree_dirty']
  assert manifest['source']['commit']==campaign['source_sha'] and manifest['source']['core']==campaign['core_identity']
  assert all(manifest['limits'][k]==v for k,v in expected.items())
  rows=[json.loads(x) for x in (folder/'measurements.jsonl').read_text().splitlines()]
  assert len(rows)==run['repeats']==(1 if label=='repos5-lines50k' else 3)
  prior=json.loads((ROOT/'experiments/impactmap_scale/removal-2026-11-15/stages'/('after-profile9-'+label)/'measurements.jsonl').read_text().splitlines()[0])
  for row in rows:
   assert [x['semantic_sha256'] for x in row['measured']['samples']]==[x['semantic_sha256'] for x in row['reference']['samples']]
   assert row['measured']['graph_facts_sha256']==row['reference']['graph_facts_sha256']
   assert [x['semantic_sha256'] for x in row['measured']['samples']]==[x['semantic_sha256'] for x in prior['measured']['samples']]
   assert row['measured']['graph_facts_sha256']==prior['measured']['graph_facts_sha256']
   assert row['semantics_equal'] and row['measured']['graph_relationships']=={'calls':3,'declares':8}
   assert all(c['coverage']=='COMPLETE_WITHIN_PROFILE' and not c['gap_counts'] and c['operations']==8 and c['dependencies']==3 and c['repositories_available']==c['repositories_configured'] for c in row['measured']['contexts'])
   assert all(s['result']['status']=='USEFUL' and s['result']['findings']==3 for s in row['measured']['samples'])
  if private:
   path=ROOT/'work/batch05-defaults'/(label+'-implicit-input.json')
   assert sha(path)==run['input_sha256'] and 'limits' not in read(path)['policy']
   assert sha(ROOT/'work/batch04/corpora-v1'/label/'corpus-manifest.json')==run['historical_manifest_sha256']
 if private:
  for name,value in read(REPORT/'corpus-hashes.json').items():assert sha(ROOT/name)==value,name
 for name,jobs in [('queue-repos5-lines50k-independent_prs',5),('queue-repos10-lines100k-head_updates',1)]:
  result=read(REPORT/'acceptance'/name/'result.json')
  assert result['passed'] and result['all_results_expected'] and result['restart_checked'] and result['analyzed_jobs']==jobs and result['processed_fraction']==1
  verdicts=result['result_verdicts']
  assert len(verdicts)==result['analyzed_jobs']==jobs
  assert len({(row['resource_id'],row['generation']) for row in verdicts})==jobs
  assert all(row['expected'] and row['status']=='USEFUL' and row['findings']==3 and row['reason_code']=='impact_found_within_profile' and not row['gap_counts'] for row in result['result_verdicts'])
 legacy=read(REPORT/'acceptance/legacy-explicit-probe/result.json');assert not legacy['passed'] and legacy['error_code']=='corpus_limit' and legacy['analyzed_fraction']==0
 partial=read(REPORT/'acceptance/partial-access.json');assert partial['coverage']=='PARTIAL' and partial['repositories_available']==9 and 'commit_unavailable' in partial['gap_codes']
 refusal=read(REPORT/'acceptance/default-refusal.json');assert refusal['result']['status']=='FAILED' and refusal['result']['reason_code']=='budget_exhausted'
 assert not refusal['result']['findings'] and not refusal['partial_context_saved'] and refusal['added_bytes']==8_400_000
 assert '8 000 000 байт' in refusal['result']['summary'] and '8 000 000 байт' in refusal['short_comment']['status_line']
 per_file=read(REPORT/'acceptance/per-file-control.json');assert per_file['passed'] and per_file['oversize_bytes']==65_537
 assert {case['mode'] for case in per_file['cases']}=={'worktree','git'}
 for case in per_file['cases']:
  assert case['coverage']=='PARTIAL' and case['gap_counts']=={'file_limit':1} and not case['oversize_retained'] and case['files_read']>0
  assert case['effective_limits']['max_corpus_bytes']==8_000_000 and case['effective_limits']['max_file_bytes']==65_536
 comparison=read(REPORT/'prior-version-comparison.json');assert comparison['all_happy_semantic_hashes_equal'] and comparison['all_canonical_facts_equal']
 tests=read(REPORT/'tests.json')
 for name in ('graph.log','performance.log','service.log','focused-final.log'):assert tests[name]['success']
 return dict(status='PASS',artifacts=len(hashes),historical_files=len(read(REPORT/'historical-hashes.json')),stage_workers=4,queue_jobs=6,current_sources=current,private_inputs=private,independent_quality='NOT_RUN')
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--current-core',action='store_true');p.add_argument('--private',action='store_true');a=p.parse_args();print(json.dumps(verify(a.current_core,a.private)))
