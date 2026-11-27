from pathlib import Path
import hashlib,json,re,shutil,statistics,subprocess
root=Path.cwd();work=root/'work/batch05-defaults';report=root/'experiments/impactmap_scale/defaults-2026-11-15'
report.mkdir(parents=True,exist_ok=True)
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,v):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,indent=2,ensure_ascii=False)+'\n')
def copy(a,b):b.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a,b)
campaign=read(work/'campaign.json');assert campaign['passed'];write(report/'campaign.json',campaign)
metrics=[]
for label in ('repos5-lines50k','repos10-lines100k'):
 src=work/('stages-'+label);dst=report/'stages'/label
 for name in ('manifest.json','measurements.jsonl','spans.csv','summary.json'):copy(src/name,dst/name)
 inp=read(work/(label+'-implicit-input.json'));assert 'limits' not in inp['policy']
 for repo in inp['policy']['repositories']:repo['root']='<local-repository:'+repo['id']+'>'
 write(dst/'input-without-roots.json',inp)
 rows=[json.loads(line) for line in (src/'measurements.jsonl').read_text().splitlines()]
 for stage in ('initial_index','first_analysis','warm_repeat','pipeline'):
  spans=[next(s for s in r['measured']['spans'] if s['stage']==stage) for r in rows]
  metrics.append(dict(corpus=label,stage=stage,n=len(rows),wall_median_s=statistics.median(s['wall_s'] for s in spans),wall_min_s=min(s['wall_s'] for s in spans),wall_max_s=max(s['wall_s'] for s in spans),
   self_cpu_median_s=statistics.median(s['self_user_s']+s['self_system_s'] for s in spans),children_cpu_median_s=statistics.median(s['child_user_s']+s['child_system_s'] for s in spans),
   max_self_lifetime_rss_bytes=max(s['self_peak_rss_bytes'] for s in spans),max_children_lifetime_rss_bytes=max(s['children_peak_rss_bytes'] for s in spans)))
write(report/'metrics.json',metrics)
for name in ('queue-repos5-lines50k-independent_prs','queue-repos10-lines100k-head_updates','legacy-explicit-probe'):copy(work/name/'result.json',report/'acceptance'/name/'result.json')
for name in ('partial-access.json','default-refusal.json'):copy(work/name,report/'acceptance'/name)
for p in work.glob('*.log'):copy(p,report/'logs'/p.name)
tests={}
for p in work.glob('*.log'):
 text=p.read_text();runs=re.findall(r'^Ran (\d+) tests? in ([\d.]+)s$',text,re.M)
 if not runs:continue
 tests[p.name]=dict(run=int(runs[-1][0]),seconds=float(runs[-1][1]),success=bool(re.search(r'^OK$',text,re.M)),failures_by_name=[dict(kind=k,name=n) for k,n in re.findall(r'^(FAIL|ERROR): (.+)$',text,re.M)],skips=[line for line in text.splitlines() if ' ... skipped ' in line])
write(report/'tests.json',tests)
paths=subprocess.check_output(['git','ls-files','research/evaluation','experiments/impactmap_scale'],text=True).splitlines()
write(report/'historical-hashes.json',{name:sha(root/name) for name in paths if not name.startswith('experiments/impactmap_scale/defaults-2026-11-15/')})
write(report/'corpus-hashes.json',{str((root/'work/batch04/corpora-v1'/label/name).relative_to(root)):sha(root/'work/batch04/corpora-v1'/label/name) for label in ('repos5-lines50k','repos10-lines100k') for name in ('corpus-manifest.json','oracle.json')})
source={p.relative_to(root).as_posix():sha(p) for folder in ('agent_graph','agent_service') for p in (root/'src'/folder).rglob('*.py')}
for name in ('tools/benchmark_impactmap.py','tools/load_impactmap.py','tools/prepare_impactmap_corpora.py','tests/graph/test_working_limits.py','tests/service/test_resource_limits.py'):source[name]=sha(root/name)
write(report/'source-hashes.json',source)
for name in ('run_default_limits_campaign.py','capture_default_refusal.py','build_default_limits_report.py'):copy(Path('/tmp')/name,report/'reproduce'/name)
print(json.dumps(dict(report=str(report),historical_files=len(paths),metrics=metrics)))
