from pathlib import Path
import hashlib,json,subprocess,shutil
ROOT=Path('/Users/user/.codex/worktrees/impactmap-batch-00/agent-bitbucket-read')
RUN=ROOT/'work/batch06-quality/post-tuning-v2'
OUT=ROOT/'research/evaluation/development-2026-11-15'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,sort_keys=True,indent=2)+'\n')
old=read(ROOT/'research/evaluation/batch06/summary.json');new=read(RUN/'summary.json')
manifest=read(RUN/'campaign-manifest.json');prior=read(ROOT/'research/evaluation/batch06/campaign-manifest.json')
assert manifest['post_tuning'] is True
for key in ('inputs_sha256','method_case_order','seed','wall_time_cap_seconds'):assert manifest[key]==prior[key],key
historical=read(ROOT/'work/batch06-quality/historical-hashes.json')
for name,digest in historical.items():assert sha(ROOT/name)==digest,name
OUT.mkdir(parents=True,exist_ok=False)
for name in ('summary.json','campaign-manifest.json','candidate-freeze.json','readiness.json','receipts.json'):shutil.copyfile(RUN/name,OUT/name)
write(OUT/'before-summary.json',old);write(OUT/'historical-hashes.json',historical)
write(OUT/'superseded-v1-summary.json',read(ROOT/'work/batch06-quality/post-tuning-v1/summary.json'))
write(OUT/'superseded.json',{'status':'FINAL_V2_AFTER_ONE_REVIEW_FIX_PASS','v1':'Intermediate candidate04fcbec. Seven independently reproduced regressions not exercised by author40 required fixes. All raw attempts preserved privately; do not select v1 as final merely from its toy scores.','original06':'research/evaluation/batch06/ is historical and byte-for-byte unchanged; neither v1 nor v2 replaces its primary observations.','v2':str(RUN.relative_to(ROOT)),'independent_cases':0,'real_experts':0})
raw_index=[];records=[]
for item in manifest['method_case_order']:
 cid,method=item['case_id'],item['method'];attempt=RUN/'attempts'/cid/method
 receipt=read(attempt/'receipt.json');norm=read(attempt/'normalized.json')
 assert receipt['raw_artifact_sha256']==sha(attempt/'raw.json')==norm['raw_artifact_sha256']
 assert receipt['normalized_sha256']==sha(attempt/'normalized.json')
 target=OUT/'normalized'/cid/(method+'.json');target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(attempt/'normalized.json',target)
 exported=None
 if method=='impactmap_static':
  raw=OUT/'raw-core'/(cid+'.json');raw.parent.mkdir(exist_ok=True);shutil.copyfile(attempt/'raw.json',raw);exported=str(raw.relative_to(OUT))
 raw_index.append({'case_id':cid,'method':method,'raw_envelope_sha256':receipt['raw_artifact_sha256'],'normalized_sha256':receipt['normalized_sha256'],'normalized_file':str(target.relative_to(OUT)),'exact_raw_file':exported,'private_original':str((attempt/'raw.json').relative_to(ROOT))})
 records.append(norm)
write(OUT/'raw-index.json',raw_index)
(OUT/'normalized.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'))+'\n' for x in records))
comparison={'status':'POST_TUNING_AUTHOR_DEVELOPMENT_ONLY','same_case_bytes':True,'same_order_seed_budget':True,'scorer_and_normalizer_unchanged':True,'before':{},'after':{},'changed_cases':{}}
for method in new['methods']:
 a,b=old['methods'][method],new['methods'][method]
 for section,value in [('before',a),('after',b)]:comparison[section][method]={k:value[k] for k in ('precision','recall','false_alert_case_rate','outside_boundary_success','outside_cases','technical_errors') if k in value}|{'counts':value['identity']['counts']}
 old_cases={c['case_id']:c for c in a['per_case']};fields=('strict','status','limited_result_success','technical_error','access_leak','false_certainty')
 changed=[]
 for c in b['per_case']:
  before=old_cases[c['case_id']]
  if any(before[k]!=c[k] for k in fields):changed.append({'case_id':c['case_id'],'before':{k:before[k] for k in fields},'after':{k:c[k] for k in fields}})
 comparison['changed_cases'][method]=changed
assert comparison['changed_cases']['lexical_search_ls1']==[]
assert new['methods']['impactmap_static']['identity']['counts']=={'tp':20,'fp':0,'fn':0}
assert new['methods']['impactmap_static']['outside_boundary_success']==5
write(OUT/'comparison.json',comparison)
freeze=read(RUN/'candidate-freeze.json')
write(OUT/'execution.json',{'tested_core_commit':subprocess.check_output(['git','rev-parse','6bc5ca2'],cwd=ROOT,text=True).strip(),'campaign_freeze_source_sha':freeze['source_sha'],'campaign_core_identity':manifest['core_identity'],'candidate_freeze_core_identity':freeze['core_identity'],'historical_source_anchor':read(ROOT/'research/evaluation/batch06/candidate-freeze.json')['source_sha'],'publication':'NONE_OFFLINE_ONLY','model':'OFF','new_application_dependencies':False,'restored_tool_dependencies':'Existing exact jsonschema4.26 dependency set restored into ignored work/batch06-quality/validator; application venv unchanged','argv':'python -m tools.impactmap_eval.calibrate --corpus work/batch06/development-v2 --output work/batch06-quality/post-tuning-v2 --post-tuning','python':'/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python','PYTHONPATH':'src:.:work/batch06-quality/validator','private_originals':str(RUN.relative_to(ROOT)),'independent_research':'NOT_REGISTERED / NOT_RUN'})
shutil.copyfile(ROOT/'work/batch06-quality/post-tuning-v1/campaign-manifest.json',OUT/'superseded-v1-campaign-manifest.json')
print(json.dumps({'exported':str(OUT),'raw_index':len(raw_index),'normalized':len(records),'core_commit':freeze['source_sha'],'changed_core_cases':len(comparison['changed_cases']['impactmap_static'])}))
