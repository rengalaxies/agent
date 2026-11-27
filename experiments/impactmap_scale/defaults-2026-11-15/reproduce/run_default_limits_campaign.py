"""Default Policy path on unchanged private corpora; sequential timing before queue."""
from pathlib import Path
import hashlib,json,os,subprocess,sys
from agent_graph import core_identity
from agent_graph.contracts import Policy,Limits
from agent_graph.sources import collect
from agent_service.core_analyzer import CoreAnalyzer
from tools.prepare_impactmap_corpora import load_benchmark_input
from tools.load_impactmap import probe_limits,run_queue_input
root=Path.cwd();work=root/'work/batch05-defaults';work.mkdir(parents=True,exist_ok=True)
reserved=['campaign.json','campaign-progress.json','partial-access.json','legacy-explicit-probe']
for label in ('repos5-lines50k','repos10-lines100k'):
 reserved.extend([label+'-implicit-input.json','stages-'+label,'stages-'+label+'.log'])
reserved.extend(['queue-repos5-lines50k-independent_prs','queue-repos10-lines100k-head_updates'])
assert not any((work/name).exists() for name in reserved),'use_new_output_root'
identity=core_identity();source=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
assert not subprocess.check_output(['git','status','--porcelain'],text=True).strip(),'commit_before_timing'
assert (Limits().max_corpus_bytes,Limits().max_files,Limits().scan_seconds)==(8_000_000,2048,60.0)
campaign=dict(core_identity=identity,source_sha=source,model='OFF',source_execution=False,network='NOT_RUN',cache_protocol='fresh worker/state; OS caches uncontrolled',stage_runs=[],acceptance=[])
def write(path,value):path.write_text(json.dumps(value,indent=2)+'\n')
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def implicit(label,scenario='baseline'):
 original=load_benchmark_input(root/'work/batch04/corpora-v1'/label,scenario)
 before=Policy.model_validate(original['policy']).limits.model_dump()
 original['policy'].pop('limits',None)
 assert 'limits' not in original['policy']
 assert Policy.model_validate(original['policy']).limits.model_dump()==Limits().model_dump()==before
 return original
for label,repeats in [('repos5-lines50k',1),('repos10-lines100k',3)]:
 corpus=root/'work/batch04/corpora-v1'/label
 manifest=implicit(label);inp=work/(label+'-implicit-input.json');write(inp,manifest);inp.chmod(0o600)
 probe=CoreAnalyzer(manifest['policy'],work/('private-policy-'+label),code_version='default-policy-probe')
 try:effective=probe.policy.limits.model_dump()
 finally:probe.close()
 target=work/('stages-'+label);log=work/('stages-'+label+'.log')
 print(json.dumps(dict(phase='timing',corpus=label,repeats=repeats)),flush=True)
 with log.open('x') as stream:r=subprocess.run([sys.executable,'-m','tools.benchmark_impactmap','--manifest',str(inp),'--output',str(target),'--repeats',str(repeats)],stdout=stream,stderr=subprocess.STDOUT,env=os.environ.copy(),cwd=root)
 assert r.returncode==0,'benchmark_failed'
 rows=[json.loads(line) for line in (target/'measurements.jsonl').read_text().splitlines()]
 assert len(rows)==repeats and all(row['semantics_equal'] for row in rows)
 prior=[json.loads(line) for line in (root/'experiments/impactmap_scale/removal-2026-11-15/stages'/('after-profile9-'+label)/'measurements.jsonl').read_text().splitlines()]
 campaign['stage_runs'].append(dict(corpus=label,repeats=repeats,input_limits_omitted=True,effective_limits=effective,
  historical_manifest_sha256=digest(corpus/'corpus-manifest.json'),input_sha256=digest(inp),
  semantics_equal=True,previous_named_policy_facts_equal=all(x['measured']['graph_facts_sha256']==prior[0]['measured']['graph_facts_sha256'] for x in rows),
  previous_named_policy_results_equal=all([s['result'] for s in x['measured']['samples']]==[s['result'] for s in prior[0]['measured']['samples']] for x in rows)))
 assert core_identity()==identity,'source_changed_during_timing'
 write(work/'campaign-progress.json',campaign)
 print(json.dumps(campaign['stage_runs'][-1]),flush=True)
# No timing worker runs concurrently with the following diagnostic queue/collector cases.
for label,size,family in [('repos5-lines50k',5,'independent_prs'),('repos10-lines100k',10,'head_updates')]:
 inp=implicit(label);recipe=json.loads((root/'work/batch04/corpora-v1'/label/'corpus-manifest.json').read_text());events=recipe['streams'][family][str(size)]
 name='queue-'+label+'-'+family
 print(json.dumps(dict(phase=name,state='START')),flush=True)
 out=run_queue_input(inp,events,work/name,family=family,delivery='burst')
 campaign['acceptance'].append(dict(case=name,passed=out['passed']))
 write(work/'campaign-progress.json',campaign)
 print(json.dumps(campaign['acceptance'][-1]),flush=True)
legacy=probe_limits(root/'work/batch04/corpora-v1/repos10-lines100k',work/'legacy-explicit-probe',limits=dict(max_corpus_bytes=2_000_000,max_files=256,scan_seconds=15.0))
campaign['acceptance'].append(dict(case='explicit_legacy_2mb',passed=legacy['error_code']=='corpus_limit' and legacy['analyzed_fraction']==0))
partial=implicit('repos10-lines100k','partial_access');context=collect(Policy.model_validate(partial['policy']),partial['head_revisions'])
partial_safe=dict(coverage='PARTIAL' if context['gaps'] else 'COMPLETE_WITHIN_PROFILE',gap_codes=sorted({g['code'] for g in context['gaps']}),repositories_available=sum(s['tree'] is not None for s in context['snapshots']),repositories_configured=len(partial['policy']['repositories']))
write(work/'partial-access.json',partial_safe)
campaign['acceptance'].append(dict(case='partial_access_on_defaults',passed=partial_safe['coverage']=='PARTIAL' and 'commit_unavailable' in partial_safe['gap_codes'] and partial_safe['repositories_available']==9))
assert core_identity()==identity,'source_changed_during_acceptance'
campaign['passed']=all(x['semantics_equal'] and x['previous_named_policy_facts_equal'] and x['previous_named_policy_results_equal'] for x in campaign['stage_runs']) and all(x['passed'] for x in campaign['acceptance'])
write(work/'campaign.json',campaign)
print(json.dumps(dict(passed=campaign['passed'],phase='COMPLETE')),flush=True)
if not campaign['passed']:raise SystemExit(1)
