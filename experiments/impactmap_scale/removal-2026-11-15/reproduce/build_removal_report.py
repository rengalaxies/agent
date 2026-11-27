from pathlib import Path
import hashlib,json,re,shutil,statistics,subprocess
root=Path.cwd();work=root/'work/batch05-removal';report=root/'experiments/impactmap_scale/removal-2026-11-15'
report.mkdir(parents=True,exist_ok=True)
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,x):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
def copy(src,dst):dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
metrics=[]
for label in ('repos5-lines50k','repos10-lines100k'):
 manifests=[]
 for phase in ('before-profile7','after-profile9'):
  src=work/(phase+'-'+label);dst=report/'stages'/(phase+'-'+label)
  for name in ('manifest.json','measurements.jsonl','spans.csv','summary.json'):copy(src/name,dst/name)
  manifest=read(src/'manifest.json');manifests.append(manifest)
  rows=[json.loads(line) for line in (src/'measurements.jsonl').read_text().splitlines()]
  assert len(rows)==3 and all(r['semantics_equal'] for r in rows)
  for stage in ('initial_index','first_analysis','warm_repeat','pipeline'):
   spans=[next(s for s in r['measured']['spans'] if s['stage']==stage) for r in rows]
   metrics.append(dict(corpus=label,phase=phase,stage=stage,n=3,
    wall_median_s=statistics.median(s['wall_s'] for s in spans),wall_min_s=min(s['wall_s'] for s in spans),wall_max_s=max(s['wall_s'] for s in spans),
    cpu_self_median_s=statistics.median(s['self_user_s']+s['self_system_s'] for s in spans),
    cpu_children_median_s=statistics.median(s['child_user_s']+s['child_system_s'] for s in spans),
    max_self_lifetime_rss_bytes=max(s['self_peak_rss_bytes'] for s in spans),max_children_lifetime_rss_bytes=max(s['children_peak_rss_bytes'] for s in spans)))
 for key in ('pins','limits','policy_without_roots_sha256','environment','model','cache_protocol'):
  assert manifests[0][key]==manifests[1][key],key
for phase in ('before-profile7','after-profile9'):copy(work/(phase+'-campaign.json'),report/(phase+'-campaign.json'))
write(report/'timing-comparison.json',metrics)
for path in sorted((work/'acceptance').glob('*/*.json')):
 if path.name in ('result.json','verification.json'):copy(path,report/'acceptance'/path.parent.name/path.name)
copy(work/'acceptance/campaign.json',report/'acceptance/campaign.json')
quality=work/'quality'
for name in ('campaign-manifest.json','summary.json','receipts.json','readiness.json','candidate-freeze.json'):
 copy(quality/name,report/'quality'/name)
index=[]
for receipt in read(quality/'receipts.json'):
 cid,method=receipt['case_id'],receipt['method'];src=quality/'attempts'/cid/method
 norm=report/'quality/normalized'/cid/(method+'.json');copy(src/'normalized.json',norm)
 raw=src/'raw.json';exact=None
 if method=='impactmap_static':
  target=report/'quality/raw-core'/(cid+'.json');copy(raw,target);exact=target.relative_to(report).as_posix()
 index.append(dict(case_id=cid,method=method,normalized_file=norm.relative_to(report).as_posix(),normalized_sha256=sha(norm),raw_envelope_sha256=sha(raw),exact_raw_file=exact,private_original=raw.relative_to(root).as_posix()))
write(report/'quality/raw-index.json',index)
old=read(root/'research/evaluation/development-2026-11-15/summary.json');new=read(quality/'summary.json')
keys=('strict','supported_cases','outside_cases','outside_boundary_success','false_alert_cases','negative_cases','technical_errors_all')
comparison={method:{k:dict(before=old['methods'][method][k],after=new['methods'][method][k]) for k in keys} for method in new['methods']}
write(report/'quality/comparison.json',comparison)
for path in work.glob('*.log'):copy(path,report/'logs'/path.name)
tests={}
for path in sorted(work.glob('*.log')):
 text=path.read_text();matches=re.findall(r'^Ran (\d+) tests? in ([\d.]+)s$',text,re.M)
 if not matches and 'test_' not in text:continue
 failures=[dict(kind=k,name=n) for k,n in re.findall(r'^(FAIL|ERROR): (.+)$',text,re.M)]
 if not matches:
  failures.extend(dict(kind=k,name=n) for n,k in re.findall(r'^(test_.+?) \.\.\. (ERROR|FAIL)$',text,re.M))
 tests[path.name]=dict(complete=bool(matches),run=int(matches[-1][0]) if matches else None,seconds=float(matches[-1][1]) if matches else None,
 success=bool(re.search(r'^OK$',text,re.M)),interrupted='KeyboardInterrupt' in text,
 failures_by_name=failures,skipped=[line for line in text.splitlines() if ' ... skipped ' in line])
write(report/'tests.json',tests)
historical=read(root/'research/evaluation/development-2026-11-15/historical-hashes.json')
for name in subprocess.check_output(['git','ls-files','research/evaluation/development-2026-11-15'],text=True).splitlines():historical[name]=sha(root/name)
for name,value in historical.items():assert sha(root/name)==value,name
write(report/'historical-hashes.json',historical)
source={p.relative_to(root).as_posix():sha(p) for folder in ('agent_graph','agent_service') for p in sorted((root/'src'/folder).rglob('*.py'))}
for name in ('tools/benchmark_impactmap.py','tools/prepare_impactmap_corpora.py','tools/load_impactmap.py','tools/impactmap_eval/scoring.py','tools/impactmap_eval/normalizer.py','tools/impactmap_eval/calibrate.py'):source[name]=sha(root/name)
write(report/'source-hashes.json',source)
for name in ('run_removal_stages_final.py','removal_acceptance.py','run_removal_campaign_final.py','build_removal_report.py'):copy(Path('/tmp')/name,report/'reproduce'/name)
print(json.dumps(dict(report=str(report),historical_files=len(historical),metrics=len(metrics),quality_receipts=len(index))))

for name in ('output.json','normalized.json','diagnostic.json'):copy(work/'replacement-diagnostic'/name,report/'replacement-diagnostic'/name)
copy(Path('/tmp/removal_replacement_diagnostic.py'),report/'reproduce/removal_replacement_diagnostic.py')
copy(Path('/tmp/verify_removal_artifacts.py'),report/'verify_artifacts.py')
# Preliminary profile8 has no final role: retain every available raw row and interruption log.
copy(work/'superseded-profile8.json',report/'superseded/profile8.json')
for label in ('repos5-lines50k','repos10-lines100k'):
 src=work/('after-profile8-'+label)
 for name in ('manifest.json','measurements.jsonl','spans.csv','summary.json'):
  if (src/name).exists():copy(src/name,report/'superseded'/label/name)

copy(Path('/tmp/finalize_removal_report.py'),report/'reproduce/finalize_removal_report.py')
for name in ('removal_readme.md','removal_review.md'):copy(Path('/tmp')/name,report/'reproduce'/name)
