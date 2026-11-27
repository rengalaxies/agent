"""Verify saved batch10 evidence without network, credentials or third-party Python."""
from pathlib import Path
import argparse,hashlib,json,re
REPORT=Path(__file__).resolve().parents[1]
ROOT=REPORT.parents[2]
def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def require(ok,reason):
    if not ok:raise ValueError(reason)

def verify(*,archive=None):
    hashes=read(REPORT/'artifact-hashes.json')
    files={str(p.relative_to(REPORT)) for p in REPORT.rglob('*') if p.is_file() and p.name!='artifact-hashes.json' and '__pycache__' not in p.parts}
    require(files==set(hashes),'artifact_set_mismatch')
    for p,h in hashes.items():require(sha(REPORT/p)==h,'artifact_hash:'+p)
    identity=read(REPORT/'identity.json');manifest=read(REPORT/'candidate-manifest.json')
    require(manifest['code']['commit']==identity['candidate_commit'],'candidate_commit')
    require(manifest['contracts']['core']==identity['core_identity'],'manifest_core')
    for p,h in identity['historical_artifacts'].items():require(sha(ROOT/p)==h,'historical_changed:'+p)
    for p,h in identity['current_source_hashes'].items():require(sha(ROOT/p)==h,'current_source_changed:'+p)
    runtime={p[4:]:h for p,h in manifest['files'].items() if p.startswith('app/')}
    require(len(runtime)==85,'runtime_file_count')
    for p,h in runtime.items():require(sha(ROOT/p)==h,'runtime_differs_from_candidate:'+p)
    a,b=read(REPORT/'build.json'),read(REPORT/'rebuild.json')
    for key in ('commit','release_id','archive_sha256','manifest_sha256'):require(a[key]==b[key],'non_reproducible_build:'+key)
    require(a['commit']==identity['candidate_commit'] and sha(REPORT/'candidate-manifest.json')==a['manifest_sha256'],'build_manifest_hash')
    if archive:require(sha(Path(archive))==a['archive_sha256'],'archive_hash')
    linux=REPORT/'linux';status=read(linux/'status.json')
    require(status['status']=='PASS' and status['complete'] and status['source_commit']==identity['candidate_commit'],'linux_status')
    require(status['uid']!=0,'linux_user')
    stages={s['name']:s for s in status['stages']}
    require({'verify-package-release','full-tests-release','box-tests-release','artifact-smoke-release','artifact-core-release','install-acceptance-release'}<=set(stages),'stage_set')
    require(all(s['returncode']==0 for s in stages.values()),'failed_final_stage')
    log=(linux/'full-tests-release.log').read_text();match=re.search(r'Ran (\d+) tests',log)
    require(match is not None and int(match[1])==1291==stages['full-tests-release']['tests'],'full_test_count')
    require('\nOK\n' in log and 'skipped ' not in log and '\nFAILED ' not in log,'full_test_outcome')
    box=(linux/'box-tests-release.log').read_text();require('Ran 78 tests' in box and '\nOK\n' in box,'box_tests')
    smoke=read(linux/'artifact-smoke-release.log');require(smoke['ok'] and len(smoke['checks'])>=15 and all(c['ok'] for c in smoke['checks']),'artifact_smoke')
    require(read(linux/'artifact-core-release.log')==manifest['contracts']['core'],'artifact_loaded_core')
    package=read(linux/'verify-package-release.log');require(package['status']=='VERIFIED' and package['commit']==identity['candidate_commit'],'linux_package_verification')
    old=read(linux/'status-infra-v1.json');require(old['status']=='FAILED','initial_failure_not_preserved')
    install=read(linux/'install-status-v3.json');acceptance=read(linux/'install-acceptance-v3.json')
    expected={'fresh_install','end_to_end_on_installed_release','reinstall_is_idempotent','service_killed_comes_back','backup_restore'}
    require(install['status']=='PASS' and install['isolated_service_stopped'] and install['external_live'] is False,'isolated_install_status')
    require(install['source_commit']==identity['candidate_commit'],'installed_source_commit')
    api=read(linux/'installed-api-release.json');require(api['status']=='PASS' and api['unauthorized']==401 and api['no_store'] and len(api['results'])>=2,'installed_operator_api')
    require(acceptance['passed'] and acceptance['supervisor']=='process','acceptance_mode')
    rows=acceptance['scenarios'];require(len(rows)==5 and {r['scenario'] for r in rows}==expected and all(r['result']=='PASS' for r in rows),'acceptance_scenario_set')
    before=read(REPORT/'preflight/runtime.json');after=read(REPORT/'preflight/runtime-postflight.json')
    key=lambda x:(x['commit'],x['pid'],x.get('config_sha256',x.get('service_config_sha256')))
    require(key(before)==key(after) and after['active']=='active','installed_runtime_changed')
    matrix=read(REPORT/'acceptance-matrix.json');require(matrix['batch10_status']=='PARTIAL' and matrix['independent06']=='NOT_REGISTERED / NOT_RUN','overstated_completion')
    require(matrix['fresh_live_cycles']=={'jira':0,'kaiten':0,'yandex_tracker':0},'emulation_claimed_live')
    require('All checks passed!' in (REPORT/'tests/lint-green.log').read_text(),'lint')
    return dict(status='PASS',artifacts=len(hashes),historical_files=len(identity['historical_artifacts']),runtime_files=len(runtime),
        linux_tests=1291,box_tests=78,installed_scenarios=5,batch10_status='PARTIAL',archive_checked=bool(archive))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--archive',type=Path);a=p.parse_args()
    print(json.dumps(verify(archive=a.archive),sort_keys=True))
