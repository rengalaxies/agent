"""Structural freeze gates. Human independence/custody must be attested externally."""
from __future__ import annotations
from datetime import datetime
from fractions import Fraction
from importlib.metadata import version
import os
from pathlib import Path
import platform
import re
import subprocess
import sqlite3
from agent_graph import core_identity
from .common import EVAL,digest,read,sha
from .normalizer import NORMALIZATION_VERSION


def components():
    folder=Path(__file__).parent
    return dict(protocol_sha256=sha((EVAL/'protocol-v2.md').read_bytes()),normalization_version=NORMALIZATION_VERSION,
        schema_bundle_sha256=digest({p.name:sha(p.read_bytes()) for p in sorted((EVAL/'schemas').glob('*.json'))}),
        evaluator_sha=digest({p.name:sha(p.read_bytes()) for p in sorted(folder.glob('*.py'))}),
        normalizer_sha=sha((folder/'normalizer.py').read_bytes()),scorer_sha=sha((folder/'scoring.py').read_bytes()))


def dependency_versions():
    return {p:version(p) for p in ('pydantic','pydantic-core','annotated-types','typing-extensions','typing-inspection','PyYAML','jsonschema','attrs','jsonschema-specifications','referencing','rpds-py')}


def candidate_freeze():
    f=read(EVAL/'templates/freeze-manifest.template.json');f.update(components())
    f['source_sha']=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    f['core_identity']=core_identity()
    f['environment']=dict(os=platform.platform(),python=platform.python_version(),hardware=f'{platform.machine()} / {os.cpu_count()} logical CPUs')
    f['baseline'].update(implementation_sha=sha((Path(__file__).parent/'runner.py').read_bytes()),
        rg_version=subprocess.check_output(['rg','--version'],text=True).splitlines()[0],
        argv_policy_sha256=digest(['rg','--fixed-strings','--line-number','--no-heading','--json','-e','TOKEN','--','FILES']))
    f['budgets']['wall_time_cap_seconds']=60
    f['budgets']['retry_policy_sha256']=digest(dict(primary='first assigned attempt',product_errors='never replace',infrastructure_retry='curator only; preserve original receipt'))
    f['dependency_versions']=dependency_versions()
    f['dependency_lock_sha256']=digest(f['dependency_versions'])
    f['public_case_sha256']={}
    f['attempt_ledger_ref']=None
    f['tooling_contract_version']='batch06-operational-1'
    return f


def readiness(f,*,case_path=None):
    missing=[]
    if f.get('status')!='REGISTERED':missing.append('status_REGISTERED')
    for key in ['loaded_runtime_sha','source_sha']:
        if not re.fullmatch('[0-9a-f]{40}',str(f.get(key))):missing.append(key)
    for key in ['input_bundle_sha256','closed_reference_bundle_sha256','closed_catalogue_sha256','source_inventory_sha256','access_policy_sha256']:
        if not re.fullmatch('[0-9a-f]{64}',str(f.get(key))):missing.append(key)
    for key,value in components().items():
        if f.get(key)!=value:missing.append(key)
    if f.get('core_identity')!=core_identity():missing.append('core_identity')
    dependencies=dependency_versions()
    if f.get('dependency_versions')!=dependencies or f.get('dependency_lock_sha256')!=digest(dependencies):missing.append('dependency_lock')
    head=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    if f.get('source_sha')!=head or f.get('loaded_runtime_sha')!=head:missing.append('loaded_source_commit')
    if subprocess.check_output(['git','status','--porcelain'],text=True).strip():missing.append('unclean_code_checkout')
    baseline=f.get('baseline',{})
    if baseline.get('implementation_sha')!=sha((Path(__file__).parent/'runner.py').read_bytes()) or baseline.get('rg_version')!=subprocess.check_output(['rg','--version'],text=True).splitlines()[0]:missing.append('baseline_identity')
    if f.get('model_mode')!='OFF':missing.append('model_mode')
    ids=f.get('case_ids',[]);cases=f.get('public_case_sha256',{})
    if len(ids)!=40 or len(set(ids))!=len(ids) or any(str(i).startswith('DEV-') for i in ids):missing.append('case_ids')
    if set(cases)!=set(ids) or not cases or any(not re.fullmatch('[0-9a-f]{64}',str(v)) for v in cases.values()):missing.append('public_case_hashes')
    if f.get('input_bundle_sha256')!=digest(sorted(cases.items())):missing.append('input_bundle_hash')
    order=f.get('method_case_order',[])
    expected={(cid,m) for cid in ids for m in ('impactmap_static','lexical_search_ls1')}
    if len(order)!=len(expected) or {(x.get('case_id'),x.get('method')) for x in order}!=expected or any(x.get('attempt_id')!=1 for x in order):missing.append('method_case_order')
    experts=f.get('experts',[])
    if len({x.get('id') for x in experts if isinstance(x,dict) and x.get('human_attested') is True and x.get('independent_before_outputs') is True})<2:missing.append('two_real_expert_attestations')
    curator=f.get('curator')
    if not isinstance(curator,dict) or not curator.get('id') or not curator.get('human_attested') or not curator.get('gold_separate_from_runner'):missing.append('curator_custody_attestation')
    if not f.get('disclosure_log_ref'):missing.append('disclosure_log_ref')
    try:
        if datetime.fromisoformat(f['gold_frozen_at'])>datetime.fromisoformat(f['registered_at']):raise ValueError()
    except (TypeError,KeyError,ValueError):missing.append('freeze_dates')
    t=f.get('thresholds',{})
    if t.get('status')!='APPROVED' or not all(t.get(k) for k in ('approved_by','approved_at','rationale_ref')):missing.append('threshold_approval')
    for key in ('strict_recall_min','strict_precision_min','negative_case_far_max'):
        if not isinstance(t.get(key),(int,float)) or not 0<=t[key]<=1:missing.append(key)
    expected_argv=digest(['rg','--fixed-strings','--line-number','--no-heading','--json','-e','TOKEN','--','FILES'])
    if f.get('baseline',{}).get('argv_policy_sha256')!=expected_argv:missing.append('baseline_argv_policy')
    retry=digest(dict(primary='first assigned attempt',product_errors='never replace',infrastructure_retry='curator only; preserve original receipt'))
    if f.get('budgets',{}).get('retry_policy_sha256')!=retry:missing.append('retry_policy')
    if f.get('primary_attempt_rule')!='first_assigned_attempt':missing.append('primary_attempt_rule')
    if type(f.get('random_seed')) is not int:missing.append('random_seed')
    environment=dict(os=platform.platform(),python=platform.python_version(),hardware=f'{platform.machine()} / {os.cpu_count()} logical CPUs')
    if f.get('environment')!=environment:missing.append('environment')
    ledger=f.get('attempt_ledger_ref')
    if not isinstance(ledger,str) or not Path(ledger).is_absolute():missing.append('attempt_ledger_ref')
    if not isinstance(curator,dict) or not curator.get('full_manifests_verified') or not curator.get('input_packets_reviewed_no_gold'):missing.append('curator_input_integrity_attestation')
    try:
        if datetime.fromisoformat(t['approved_at'])>datetime.fromisoformat(f['registered_at']):raise ValueError()
    except (TypeError,KeyError,ValueError):missing.append('threshold_approval_date')
    cap=f.get('budgets',{}).get('wall_time_cap_seconds')
    if not isinstance(cap,(int,float)) or not 0<cap<=1800:missing.append('wall_time_cap')
    if case_path is not None:
        case=read(case_path)
        if cases.get(case['case_id'])!=sha(Path(case_path).read_bytes()):missing.append('assigned_case_hash')
        if case['budget']['wall_time_cap_seconds']!=cap:missing.append('shared_budget')
    return dict(status='NOT_REGISTERED' if missing else 'REGISTERED_READY',missing=sorted(set(missing)),
        scope='structural integrity only; cannot authenticate people or prove physical custody/independence')


def decision(report,registration,thresholds):
    if any(x['development'] for x in report['per_case']) or registration['status']!='REGISTERED_READY':return 'NOT_REGISTERED'
    if report.get('protocol_issues'):return 'INVALID_PROTOCOL'
    if not registration.get('closed_gold_artifacts_verified') or not registration.get('human_output_audits_verified'):return 'INDETERMINATE'
    if report.get('manual_audits') or report['gold_audits'] or report['precision'] is None or report['recall'] is None or report['false_alert_case_rate'] is None:return 'INDETERMINATE'
    c=report['strict']
    gates=(Fraction(c['tp'],c['tp']+c['fn'])>=Fraction(str(thresholds['strict_recall_min']))
           and Fraction(c['tp'],c['tp']+c['fp'])>=Fraction(str(thresholds['strict_precision_min']))
           and Fraction(report['false_alert_cases'],report['negative_cases'])<=Fraction(str(thresholds['negative_case_far_max'])))
    passed=gates and report['technical_errors_supported']==0 and report['outside_boundary_success']==report['outside_cases'] and not report['access_leaks'] and not report['false_certainty']
    return 'CRITERIA_MET_ON_CATALOGUE' if passed else 'CRITERIA_NOT_MET'


def claim_attempt(f,case_id,method):
    """One ledger path is frozen in permit, independent of result directories."""
    path=Path(f['attempt_ledger_ref'])
    if path.is_symlink():raise ValueError('ledger_symlink')
    path.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(path,timeout=10)
    try:
        db.executescript("CREATE TABLE IF NOT EXISTS meta(hash TEXT); CREATE TABLE IF NOT EXISTS assignments(seq INTEGER PRIMARY KEY,case_id TEXT,method TEXT,claimed INTEGER DEFAULT 0,UNIQUE(case_id,method)); CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY,case_id TEXT,method TEXT); CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'append only'); END; CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'append only'); END;")
        db.execute('BEGIN IMMEDIATE')
        frozen=digest(f);row=db.execute('SELECT hash FROM meta').fetchone()
        if row is None:
            db.execute('INSERT INTO meta VALUES (?)',(frozen,))
            db.executemany('INSERT INTO assignments(seq,case_id,method) VALUES (?,?,?)',[(i,x['case_id'],x['method']) for i,x in enumerate(f['method_case_order'])])
        elif row[0]!=frozen:raise ValueError('freeze_mutated')
        current=db.execute('SELECT claimed FROM assignments WHERE case_id=? AND method=?',(case_id,method)).fetchone()
        if current is None:raise ValueError('unassigned_method_case')
        if current[0]:raise ValueError('primary_already_assigned')
        nextrow=db.execute('SELECT case_id,method FROM assignments WHERE claimed=0 ORDER BY seq LIMIT 1').fetchone()
        if nextrow!=(case_id,method):raise ValueError('frozen_order_violation')
        db.execute('UPDATE assignments SET claimed=1 WHERE case_id=? AND method=?',(case_id,method))
        db.execute('INSERT INTO audit(case_id,method) VALUES (?,?)',(case_id,method));db.commit()
    finally:db.close()
