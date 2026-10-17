"""Trusted evaluator entrypoint. Never consume a patch author's self-report."""
from __future__ import annotations
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def candidate_digest(path):
    root = Path(path).resolve()
    h = hashlib.sha256()
    for p in sorted(root.rglob('*')):
        if p.is_symlink():
            raise ValueError('candidate symlinks forbidden')
        if p.is_file() and '__pycache__' not in p.parts:
            h.update(p.relative_to(root).as_posix().encode() + b'\0')
            h.update(hashlib.sha256(p.read_bytes()).digest())
    return h.hexdigest()


def suite_digest():
    h = hashlib.sha256()
    for p in sorted(HERE.glob('*')):
        if p.is_file():
            h.update(p.name.encode() + b'\0' + p.read_bytes())
    tests = HERE.parent / 'tests'
    for p in sorted(tests.glob('*.py')):
        h.update(p.name.encode() + b'\0' + p.read_bytes())
    return h.hexdigest()


def frozen_expectations():
    expected = (HERE / 'FREEZE.sha256').read_text().split()[0]
    raw = (HERE / 'expectations.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('frozen evaluator expectations modified')
    return json.loads(raw)


def verify(candidate_dir, scenario_id='T03'):
    """Configuration controls + live independent business tests when explicitly enabled.

    Runtime may not promote this scoped verdict into full R1-R8 transition acceptance.
    Full transition tests run by `python -m lab.tests.integration` on a fresh project.
    """
    result = {'candidate_digest': candidate_digest(candidate_dir),
              'suite_digest': suite_digest(), 'scenario_id': scenario_id,
              'outcome': 'INCOMPLETE', 'checks': [],
              'coverage': 'candidate checks only; live business validation requires isolated suite',
              'uncovered': ['full S0-S5 execution', 'R6 grants', 'R7 discovery completeness',
                            'R8 freshness', 'component recovery']}
    frozen_expectations()
    root = Path(candidate_dir)
    forbidden = [str(p.relative_to(root)) for p in root.rglob('*')
                 if p.is_file() and any(x in p.parts for x in ('evaluator', 'tests'))]
    if forbidden:
        result['checks'].append({'id': 'T04', 'status': 'FAIL', 'evidence':
                                 {'reason': 'candidate contains evaluator-owned files', 'paths': forbidden}})
        result['outcome'] = 'FAIL'
        return result
    migrations = list(root.rglob('sql/expand.sql'))
    if len(migrations) != 1:
        result['checks'].append({'id':'candidate_input','status':'FAIL','evidence':'Exactly one sql/expand.sql required'})
        result['outcome']='FAIL';return result
    trusted_root=HERE.parents[1]
    for item in root.rglob('*'):
        if not item.is_file() or '__pycache__' in item.parts:continue
        relative=item.relative_to(root)
        if relative.as_posix()=='lab/sql/expand.sql':continue
        original=trusted_root/relative
        if not original.is_file() or original.read_bytes()!=item.read_bytes():
            result['checks'].append({'id':'T04','status':'FAIL','evidence':'Unverified out-of-scope candidate change: '+relative.as_posix()})
            result['outcome']='FAIL';return result
    import os, shutil, subprocess, tempfile, secrets
    if os.environ.get('LAB_ENABLE_ISOLATED_VERIFIER') != '1' or not shutil.which('docker'):
        result['checks'].append({'id':'live_candidate_verification','status':'BLOCKED','evidence':'Trusted Docker host controller unavailable or LAB_ENABLE_ISOLATED_VERIFIER not enabled; no model report accepted'})
        return result
    trusted_root=HERE.parents[1]
    project='dm-eval-'+secrets.token_hex(6)
    env=dict(os.environ)
    for key in ('ORDERS_PASSWORD','BILLING_PASSWORD','VERIFIER_PASSWORD','PG_ADMIN_PASSWORD','RABBIT_PASSWORD'):
        env[key]=secrets.token_hex(20)
    env['LAB_APP_IMAGE']=project+':trusted'
    with tempfile.TemporaryDirectory(prefix='dm-independent-') as tmp:
        evidence=Path(tmp)/'evidence';evidence.mkdir();evidence.chmod(0o777)
        migration=Path(tmp)/'expand.sql';migration.write_bytes(migrations[0].read_bytes());migration.chmod(0o444)
        base=['docker','compose','-p',project,'-f',str(trusted_root/'lab/compose.yaml')]
        def execute(args, timeout=300):
            completed=subprocess.run(base+args,env=env,cwd=trusted_root,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout)
            if completed.returncode:raise RuntimeError('ISOLATED_CONTROLLER_STEP_FAILED')
        try:
            execute(['build','app'],600)
            execute(['up','-d','--wait','postgres','rabbitmq'])
            execute(['run','--rm','bootstrap'])
            execute(['run','--rm','--entrypoint','python','-e','LAB_EXPAND_SQL=/candidate/expand.sql',
                     '-v',str(migration)+':/candidate/expand.sql:ro','-v',str(evidence)+':/evidence',
                     'app','-m','lab.tests.integration','--candidate-only','--output','/evidence/candidate.json'])
            actual=json.loads((evidence/'candidate.json').read_text())
            result['checks']=actual['checks']
            result['outcome']=actual['outcome']
            result['coverage']=actual['coverage']
            result['environment_manifest_digest']=hashlib.sha256((trusted_root/'lab/compose.yaml').read_bytes()).hexdigest()
            result['input_snapshot_digest']=hashlib.sha256((HERE/'expectations.json').read_bytes()).hexdigest()
            result['scope']='INDEPENDENT_ISOLATED_FINANCIAL_CANDIDATE; not full T03 acceptance'
        except (RuntimeError,subprocess.TimeoutExpired,OSError,ValueError) as exc:
            output=evidence/'candidate.json'
            if output.exists():
                actual=json.loads(output.read_text());result['checks']=actual['checks'];result['outcome']=actual['outcome']
            else:
                result['checks'].append({'id':'live_candidate_verification','status':'BLOCKED','evidence':type(exc).__name__})
        finally:
            try:execute(['down','--volumes','--remove-orphans'],120)
            except Exception:result['cleanup']='BLOCKED; isolated project '+project+' requires operator cleanup'
    return result
