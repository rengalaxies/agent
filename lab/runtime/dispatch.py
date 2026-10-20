"""Operator-only dispatcher, not a model tool or network endpoint.

Grants are local operator files; their integrity relies on filesystem permissions.
This is not a cryptographically authenticated multi-tenant authorization service.
"""
from __future__ import annotations
import json
import os
from pathlib import Path
from .core import Audit, Stop, digest, discover, enforce_grant, tree_digest


def execute(root, candidate, change, grant, journal_dir, target, revoked=(), authority_loader=None):
    """Reverify exact candidate and context before ONE explicit transition step.

    No shell, merge, broker administration or legacy retirement entrypoint exists.
    Unknown outcomes require reconciliation, never blind automatic retry.
    """
    from lab.evaluator.verify import verify, suite_digest
    from lab.app import service
    if not callable(authority_loader):
        raise Stop('Live authority loader required to recheck revocation immediately before execution.')
    if target not in ('S1', 'S2', 'S3', 'S4', 'S5'):
        raise Stop('Only explicit S1-S5 transition actions supported.')
    candidate = Path(candidate).resolve()
    source = discover(root)
    context = digest({'source': source['snapshot_digest'], 'change': change})
    artifact = tree_digest(candidate)
    authorization_context = digest({'change_context': context, 'artifact_digest': artifact,
                                    'suite_digest': suite_digest()})
    enforce_grant(grant, 'transition', target, change.get('environment_id', 'lab'), authorization_context, revoked)
    # A caller cannot substitute an author's report; evaluator is called here.
    verification = verify(candidate, 'T03')
    if verification.get('outcome') != 'PASS':
        raise Stop('Independent live candidate verification is incomplete or failed.')
    if not set('R'+str(i) for i in range(1,9)).issubset(verification.get('accepted_properties', [])):
        raise Stop('Financial-only PASS cannot authorize execution; independent R1-R8 acceptance required.')
    if tree_digest(candidate) != artifact:
        raise Stop('Artifact changed while checking.')
    def recheck():
        current_source = discover(root)
        current_context = digest({'source': current_source['snapshot_digest'], 'change': change})
        fresh = digest({'change_context': current_context, 'artifact_digest': tree_digest(candidate),
                        'suite_digest': suite_digest()})
        try:
            authority = authority_loader()
            current_grant = authority['grant']
        except Exception:
            raise Stop('Current authority unavailable; execution denied.') from None
        if fresh != authorization_context:
            raise Stop('Source, candidate or suite changed during verification.')
        enforce_grant(current_grant, 'transition', target, change.get('environment_id', 'lab'),
                      fresh, authority.get('revoked', ()))
    recheck()
    return _perform_transition(candidate, journal_dir, target, artifact, authorization_context, recheck)


def _perform_transition(candidate, journal_dir, target, artifact, authorization_context, before_effect, after_commit=None):
    """Trusted effect boundary; fault callback is only used by the isolated CI controller."""
    from lab.app import service
    audit = Audit(journal_dir)
    key = digest({'candidate': artifact, 'target': target, 'context': authorization_context})
    prior = [json.loads(line) for line in audit.path.read_text().splitlines()] if audit.path.exists() else []
    attempts = [row for row in prior if row.get('idempotency_key') == key]
    if attempts:
        last = attempts[-1]
        if last.get('state') == 'CONFIRMED':
            return {'state': 'ALREADY_CONFIRMED', 'evidence': last}
        raise Stop('Prior outcome unresolved; inspect actual snapshot and reconcile before a new grant.')
    before = service.snapshot()
    # Sequential transition function additionally checks durable current_state.
    audit.record('transition', state='INTENDED', idempotency_key=key, target=target,
                 artifact_digest=artifact, context_digest=authorization_context, before=before)
    previous_sql = service.SQL
    previous_override = os.environ.pop("LAB_EXPAND_SQL", None)
    try:
        try:
            before_effect()
        except Stop:
            audit.record('transition', state='DENIED', idempotency_key=key, target=target,
                         reason='Authority or verification context invalid immediately before effect')
            raise
        # Trusted service implementation, candidate SQL only; never import candidate Python.
        service.SQL = candidate / 'lab/sql'
        result = service.transition(target)
        if after_commit is not None:
            after_commit()
        after = service.snapshot()
        audit.record('transition', state='CONFIRMED', idempotency_key=key, target=target,
                     result=result, observed_effect=after)
        return {'state': 'CONFIRMED', 'target': target, 'snapshot': after}
    except Stop:
        raise
    except Exception as exc:
        audit.record('transition', state='UNKNOWN', idempotency_key=key, target=target,
                     error_type=type(exc).__name__, recovery='Read durable source, billing and queue state; never blindly retry.')
        raise Stop('Transition outcome UNKNOWN; evidence retained for reconciliation.') from None
    finally:
        service.SQL = previous_sql
        if previous_override is not None:
            os.environ["LAB_EXPAND_SQL"] = previous_override


def reconcile_unknown(journal_dir, expected_artifact):
    """Read durable state, record a safe stop. Never executes or retries a transition."""
    from lab.app import service
    audit = Audit(journal_dir)
    if not audit.path.exists():
        raise Stop('No persisted intent to reconcile.')
    rows = [json.loads(line) for line in audit.path.read_text().splitlines()]
    previous = '0' * 64
    for row in rows:
        unsigned = {k:v for k,v in row.items() if k != 'record_digest'}
        if row.get('previous_digest') != previous or digest(unsigned) != row.get('record_digest'):
            raise Stop('Journal integrity failure; no retry permitted.')
        previous = row['record_digest']
    intent = rows[-1]
    if intent.get('state') == 'UNKNOWN':
        intent = next((r for r in reversed(rows) if r.get('idempotency_key') == intent.get('idempotency_key') and r.get('state') == 'INTENDED'), {})
    if intent.get('state') != 'INTENDED' or intent.get('artifact_digest') != expected_artifact:
        raise Stop('No matching unresolved intent; operator reconciliation required.')
    actual = service.snapshot()
    state = actual['source']['lab_state']
    logs = actual['source']['transition_log']
    before = intent['before']['source']['lab_state']
    matches = (intent.get('target') == 'S1' and len(before) == len(state) == 1
               and before[0]['current_state'] == 'S0' and state[0]['current_state'] == 'S1'
               and len(logs) == 1 and logs[0]['target'] == 'S1'
               and logs[0]['detail'].get('previous') == 'S0'
               and all(r.get('amount_minor') == r['amount_rub'] * 100 for r in actual['source']['orders']))
    if not matches:
        audit.record('reconciliation', state='RECONCILIATION_BLOCKED', idempotency_key=intent['idempotency_key'],
                     reason='DURABLE_STATE_DOES_NOT_MATCH_S1_INTENT', observed_effect=actual)
        raise Stop('Durable state does not match S1 intent; no retry permitted.')
    reason = 'S1_COMMITTED_WITHOUT_CONTROLLER_CONFIRMATION_REQUIRES_FRESH_OPERATOR_DECISION'
    record = audit.record('reconciliation', state='RECONCILED_COMMITTED_STOP',
                         idempotency_key=intent['idempotency_key'], target='S1',
                         intended_record_digest=intent['record_digest'], artifact_digest=expected_artifact,
                         reason=reason, observed_effect=actual, executed_actions=[])
    return {'state':record['state'], 'reason':reason, 'observed_state':'S1', 'executed_actions':[]}
