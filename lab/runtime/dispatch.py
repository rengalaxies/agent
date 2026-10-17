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
            recheck()
        except Stop:
            audit.record('transition', state='DENIED', idempotency_key=key, target=target,
                         reason='Authority or verification context invalid immediately before effect')
            raise
        # Trusted service implementation, candidate SQL only; never import candidate Python.
        service.SQL = candidate / 'lab/sql'
        result = service.transition(target)
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
