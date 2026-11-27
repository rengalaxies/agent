from pathlib import Path
import hashlib,json,subprocess
root=Path.cwd();report=root/'experiments/impactmap_scale/removal-2026-11-15';commit='0582cd8798a7c4ce3b7a2f38e753f600bd65ef9a'
def git(*args):return subprocess.check_output(['git',*args],cwd=root)
def sha(data):return hashlib.sha256(data).hexdigest()
paths=git('ls-tree','-r','--name-only',commit,'src/agent_graph').decode().splitlines()
files=sorted((p.removeprefix('src/agent_graph/'),sha(git('show',commit+':'+p).replace(b'\r\n',b'\n'))) for p in paths if p.endswith('.py'))
core_digest=sha(repr(files).encode());tool_sha=sha(git('show',commit+':tools/benchmark_impactmap.py'))
for label in ('repos5-lines50k','repos10-lines100k'):
 manifest=json.loads((report/'stages'/('before-profile7-'+label)/'manifest.json').read_text())
 assert manifest['source']['core']['core_digest']==core_digest
 assert manifest['source']['tool_sha256']==tool_sha
for path in (root/'src/agent_service').rglob('*.py'):
 assert path.read_bytes()==git('show',commit+':'+path.relative_to(root).as_posix()),path
result=dict(baseline_commit=commit,recomputed_git_core_digest=core_digest,benchmark_sha256=tool_sha,core_matches_both_baseline_manifests=True,current_service_sources_equal_baseline_git=True,
 dirty_manifest='before-profile7-repos10-lines100k',explanation='Untracked tests/spec/plan were created while baseline ran; production core and benchmark remained unchanged, controller checked core identity after each profile. No whole-tree-clean claim.',evidence_strength='author execution record plus loaded core/benchmark fingerprints; not a signed historical whole-process snapshot')
(report/'baseline-code-receipt.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
