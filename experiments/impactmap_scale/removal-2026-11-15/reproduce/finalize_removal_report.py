from pathlib import Path
import hashlib,json,shutil,subprocess,sys
root=Path.cwd();work=root/'work/batch05-removal';report=root/'experiments/impactmap_scale/removal-2026-11-15'
def read(p):return json.loads(p.read_text())
def write(p,x):p.write_text(json.dumps(x,indent=2,ensure_ascii=False)+'\n')
assert read(work/'acceptance/campaign.json')['passed']
assert (work/'quality/summary.json').exists()
subprocess.run([sys.executable,'/tmp/build_removal_report.py'],check=True)
quality=read(work/'quality/summary.json');core=quality['methods']['impactmap_static'];ls=quality['methods']['lexical_search_ls1']
metrics=f"ImpactMap TP{core['strict']['tp']}/FP{core['strict']['fp']}/FN{core['strict']['fn']}, O{core['outside_boundary_success']}/{core['outside_cases']}; LS1 TP{ls['strict']['tp']}/FP{ls['strict']['fp']}/FN{ls['strict']['fn']}, O{ls['outside_boundary_success']}/{ls['outside_cases']}."
values=read(report/'timing-comparison.json');table=['| Корпус | Профиль | Индексация | Первый анализ | Повтор |','|---|---|---:|---:|---:|']
for label in ('repos5-lines50k','repos10-lines100k'):
 for phase in ('before-profile7','after-profile9'):
  row={m['stage']:m['wall_median_s'] for m in values if m['corpus']==label and m['phase']==phase}
  table.append('| '+('5 / 50k' if label.startswith('repos5-') else '10 / 100k')+' | '+('7' if phase=='before-profile7' else '9')+' | '+' | '.join(f'{row[s]:.3f}' for s in ('initial_index','first_analysis','warm_repeat'))+' |')
text=Path('/tmp/removal_readme.md').read_text().replace('{{TIMING_TABLE}}','\n'.join(table)).replace('{{QUALITY_METRICS}}',metrics)
(report/'README.md').write_text(text);shutil.copyfile('/tmp/removal_review.md',report/'review.md')
execution=dict(tested_core_commit='2d13227a766ec7d8178143b005d077034e281897',before_commit='0582cd8798a7c4ce3b7a2f38e753f600bd65ef9a',core_identity=read(work/'after-profile9-campaign.json')['core_identity'],source_execution=False,model='OFF',external_publication='NONE',runtime_live_verification='NOT_RUN_THIS_PACKAGE',installed_runtime_changed=False,independent_research='NOT_REGISTERED / NOT_RUN',fresh_review='PARTIAL_FINDINGS_THEN_USAGE_LIMIT',final_report_review='AUTHOR_VERIFICATION',new_application_dependencies=False,private_originals='work/batch05-removal',performance_order='before7 then after9; each sequential; no tests/quality/acceptance overlap with stage timing',diagnostic_jobs='queue/equality acceptance and author quality run in parallel after stage timing; their wall times are not controlled performance comparisons')
write(report/'execution.json',execution)
write(report/'artifact-hashes.json',{p.relative_to(report).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(report.rglob('*')) if p.is_file() and p.name!='artifact-hashes.json' and '__pycache__' not in p.parts})
for src,dst in [('/tmp/removal_CHECKPOINT.md','/tmp/removal_CHECKPOINT_final.md'),('/tmp/removal_REMAINING.md','/tmp/removal_REMAINING_final.md')]:Path(dst).write_text(Path(src).read_text().replace('{{QUALITY_METRICS}}',metrics))
print(json.dumps(dict(status='REPORT_BUILT_PENDING_VERIFY',metrics=metrics,table=table)))
