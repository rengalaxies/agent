"""Verify the secondary analysis from saved E3/E6 artifacts; no product execution."""
import argparse,csv,hashlib,json
from pathlib import Path
from fractions import Fraction

def read(p):return json.loads(Path(p).read_text())
def digest(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--e3',type=Path,required=True,help='E2 research/evaluation/development-2026-11-15 directory');a.add_argument('--e6',type=Path,required=True,help='Published e6-2026-11-27 directory');a.add_argument('--analysis',type=Path,default=Path(__file__).resolve().parent);o=a.parse_args();expected=read(o.analysis/'analysis.json')
 for key,file in [('E3_summary',o.e3/'summary.json'),('E3_index',o.e3/'raw-index.json'),('E6_summary',o.e6/'attempts/summary.json'),('E6_plan',o.e6/'corpus/plan-before-run.json')]:assert digest(file)==expected['input_hashes'][key],key
 summaries={'E3':read(o.e3/'summary.json'),'E6':read(o.e6/'attempts/summary.json')};plan={s['case_id']:s for s in read(o.e6/'corpus/plan-before-run.json')['cases']}
 rows=list(csv.DictReader((o.analysis/'case-analysis.csv').open()));assert len(rows)==50
 for series,s in summaries.items():
  for m,st in s['methods'].items():
   actual={k:sum((r.get('strict') or {}).get(k,0) for r in st['per_case']) for k in ('tp','fp','fn')};assert actual==st['strict']==expected['series'][series][m]['strict']
   prefix='impactmap' if m=='impactmap_static' else 'ls1'
   for case in st['per_case']:
    row=next(r for r in rows if r['series']==series and r['case_id']==case['case_id']);assert row[prefix+'_status']==case['status']
    for k in ('tp','fp','fn'):assert row[prefix+'_'+k]==('' if case['strict'] is None else str(case['strict'][k]))
 for r in read(o.e3/'raw-index.json'):assert digest(o.e3/r['normalized_file'])==r['normalized_sha256'],r['normalized_file']
 raw_count=0;normal_count=0
 for cid in plan:
  for method in ['impactmap_static','lexical_search_ls1']:
   d=o.e6/'attempts/attempts'/cid/method;r=read(d/'receipt.json');assert r['attempt']=={'id':1,'kind':'primary'};assert r['development'] and not r['gold_received'];assert digest(d/'normalized.json')==r['normalized_sha256'];normal_count+=1
   if (d/'raw.json').exists():assert digest(d/'raw.json')==r['raw_artifact_sha256'];raw_count+=1
 for c in read(o.analysis/'worked-cases.json'):
  cid=c['case_id'];spec=plan[cid];assert c['input']=={'provider_base':spec['before'],'provider_head':spec['after'],'consumer':spec['client']};assert c['expectation']==spec['expected'];assert digest(o.e6/'corpus/author-oracles'/f'{cid}.json')==c['oracle_sha256']
  for method,record in c['outputs'].items():
   d=o.e6/'attempts/attempts'/cid/method;assert digest(d/'payload.json')==record['payload_sha256'];assert digest(d/'normalized.json')==record['normalized_sha256'];actual=next(r for r in summaries['E6']['methods'][method]['per_case'] if r['case_id']==cid);assert record['status']==actual['status'];assert record['strict']==actual['strict']
  payload=read(o.e6/'attempts/attempts'/cid/'impactmap_static/payload.json')
  for snap in payload['snapshots']:
   if snap['repository']=='provider':
    if snap['commit'] is None:
     assert cid=='AUD-0010' and snap['mode']=='WORKTREE' and payload['status']=='FAILED' and payload['reason_code']=='commit_unavailable'
    else:assert c['commits']['provider'][snap['role']]==snap['commit']
   else:assert c['commits']['consumer']['head']==snap['commit']
 sensitivity=list(csv.DictReader((o.analysis/'threshold-sensitivity.csv').open()));assert len(sensitivity)==19
 for row in sensitivity:
  threshold=Fraction(row['threshold'])
  if row['metric']=='recall':n=int(row['expected_findings']);assert int(row['max_fn'])==max(fn for fn in range(n+1) if Fraction(n-fn,n)>=threshold)
  elif row['metric']=='precision':tp=int(row['tp']);assert int(row['max_fp'])==max(fp for fp in range(101) if Fraction(tp,tp+fp)>=threshold)
  else:n=int(row['negative_cases']);assert int(row['max_false_alert_cases'])==max(k for k in range(n+1) if Fraction(k,n)<=threshold)
 print(json.dumps({'status':'PASS','case_rows':50,'E3_normalized_hashes':80,'E6_normalized_receipts':normal_count,'E6_raw_receipts_available_and_verified':raw_count,'worked_cases':5,'sensitivity_rows':19,'new_product_runs':0}))
if __name__=='__main__':main()
