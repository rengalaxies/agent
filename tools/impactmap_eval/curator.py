"""Closed-side verification only. Method workers never import this module.

Hash/role/date checks do not authenticate real people or create independence.
Run on the curator's separate machine/workspace, after both methods finish.
"""
from __future__ import annotations
from datetime import datetime
from pathlib import Path
from .common import read,sha,validate


def _artifact(root,reference,expected):
    root=Path(root).resolve();path=(root/reference).resolve()
    if not path.is_relative_to(root) or not path.is_file():raise ValueError('closed_artifact_outside_root')
    if sha(path.read_bytes())!=expected:raise ValueError('closed_artifact_hash_mismatch')
    return path


def verify_reference(root,gold_path,*,gold_frozen_at,first_output_at,registry):
    gold_path=Path(gold_path).resolve()
    if not gold_path.is_relative_to(Path(root).resolve()):raise ValueError('closed_gold_outside_root')
    gold=read(gold_path);validate('reference-label',gold)
    if gold['lifecycle']!='complete' or gold['stage']!='adjudicated':raise ValueError('complete_human_gold_required')
    if not all(gold['attestation'][k] for k in ('confirmed_by_human','independent_before_outputs')):raise ValueError('human_attestation_required')
    if hasattr(registry,'case') and gold['case_id']!=registry.case['case_id']:raise ValueError('gold_case_identity')
    adjudicated=datetime.fromisoformat(gold['completed_at']);frozen=datetime.fromisoformat(gold_frozen_at);first=datetime.fromisoformat(first_output_at)
    if not adjudicated<=frozen<=first:raise ValueError('gold_output_date_order')
    ids=[]
    for reference in gold['source_labels']:
        path=_artifact(root,reference['artifact_ref'],reference['artifact_sha256'])
        label=read(path);validate('reference-label',label)
        if label['lifecycle']!='complete' or label['stage']!='independent' or label['case_id']!=gold['case_id'] or label['expert_id']!=reference['expert_id']:
            raise ValueError('independent_label_identity')
        if datetime.fromisoformat(label['completed_at'])>adjudicated:raise ValueError('independent_label_date')
        if not all(label['attestation'][k] for k in ('confirmed_by_human','independent_before_outputs')):raise ValueError('independent_human_attestation')
        ids.append(label['expert_id'])
    if len(set(ids))<2 or len(set(ids))!=len(ids):raise ValueError('two_distinct_human_labels_required')
    for item in gold['keys']:
        if item['label']=='UNRESOLVED':raise ValueError('unresolved_gold')
        if any(not registry.valid(w) for w in item['witnesses']):raise ValueError('gold_source_witness_mismatch')
        if item['expectation']:
            _artifact(root,item['expectation']['artifact_ref'],item['expectation']['artifact_sha256'])
    return dict(case_id=gold['case_id'],closed_gold_artifacts_verified=True,expert_ids=ids,
                human_identity_authentication='external curator responsibility, not established by this program')


def verify_output_audit(audit_path,raw_path,*,case_id,method):
    audit=read(audit_path);raw=read(raw_path)
    required=('auditor_id','human_confirmed','source_scope_verified','prose_claims_verified','completed_at')
    if not all(audit.get(k) for k in required):raise ValueError('human_output_audit_incomplete')
    if audit.get('case_id')!=case_id or audit.get('method')!=method or audit.get('raw_artifact_sha256')!=sha(Path(raw_path).read_bytes()):
        raise ValueError('output_audit_identity')
    if raw.get('case_id')!=case_id or raw.get('method')!=method:raise ValueError('raw_attempt_identity')
    if datetime.fromisoformat(audit['completed_at'])<datetime.fromisoformat(raw['finished_at']):raise ValueError('output_audit_date')
    return dict(human_output_audits_verified=True,access_leak_found=bool(audit.get('access_leak_found')),
                false_certainty_found=bool(audit.get('false_certainty_found')))
