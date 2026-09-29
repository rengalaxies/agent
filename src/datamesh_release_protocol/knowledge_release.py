"""V2 release over authoritative snapshots, with commit-time fencing."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import Field

from .engine import finalize
from .interpreter import TypedObligationInterpreter
from .validators import _schema_checks
from .knowledge import KnowledgeSnapshot, KnowledgeStore, digest, utc
from .models import Decision, Migration, StrictModel


class MappedRelease(StrictModel):
    proposal_id: str
    run_id: str
    snapshot_id: str
    decision: Decision
    terminal_state: str
    release_id: str | None = None
    reasons: list[str]
    evidence: list[dict[str, Any]]
    state_trace: list[str]

    def producer_view(self):
        return {'proposal_id': self.proposal_id, 'decision': self.decision.value,
                'state': self.terminal_state, 'release_id': self.release_id,
                'snapshot_id': self.snapshot_id, 'reasons': self.reasons, 'affected': self.evidence}

    def consumer_view(self, consumer_id):
        return {**self.producer_view(), 'affected': [e for e in self.evidence if e.get('consumer_id') == consumer_id]}


class KnowledgeReleaseEngine:
    """Research release ledger; durable map, single-process release coordinator.

    Idempotency lasts for this engine lifetime. Production exactly-once publication
    requires a durable transactional outbox, which is outside this component.
    """
    def __init__(self, store: KnowledgeStore):
        self.store = store
        self._runs: dict[str, tuple[str, MappedRelease]] = {}

    def run(self, snapshot_id: str, run_id: str, at: datetime, migrations: list[Migration] | None = None):
        with self.store.lock:
            snapshot = self.store.resolve_snapshot(snapshot_id)
            at = utc(at)
            if at < snapshot.as_of:
                raise ValueError('commit precedes snapshot')
            migrations = migrations or []
            fingerprint = digest({'snapshot': snapshot_id, 'migrations': [m.model_dump(mode='json') for m in migrations]})
            if run_id in self._runs:
                prior_hash, prior = self._runs[run_id]
                if prior_hash != fingerprint: raise ValueError('run_id reused with conflicting payload')
                return prior.model_copy(deep=True)
            decisions, evidence = [], []
            from .models import ConsumerObligation
            for r in snapshot.records:
                if r.status != 'confirmed' or (r.valid_until and r.valid_until <= snapshot.as_of):
                    continue
                if r.kind == 'obligation' and r.data['mandatory']:
                    requirement = ConsumerObligation.model_validate(r.data['requirement'])
                elif r.kind == 'global_rule':
                    requirement = ConsumerObligation.model_validate(r.data['predicate'])
                else:
                    continue
                # Invalid link/authority cannot supply a semantic proof.
                linked_ids = {r.record_id}
                if r.kind == 'obligation':
                    usage_record = next((u for u in snapshot.records if u.record_id == r.data['usage_ref'] and u.kind == 'usage'), None)
                    if not usage_record or not usage_record.data['active']: continue
                    linked_ids.update([usage_record.record_id, usage_record.data['consumer_team_ref'], requirement.consumer_id])
                if any(any(issue.endswith(':' + rid) for rid in linked_ids) for issue in snapshot.issues) or (r.kind == 'global_rule' and 'global_rule_conflict' in snapshot.issues) or (r.kind == 'obligation' and 'obligation_identity_conflict' in snapshot.issues):
                    continue
                checks = _schema_checks(snapshot.old_contract, snapshot.new_contract) + TypedObligationInterpreter().evaluate(snapshot.new_contract, requirement, migrations)
                outcome = Decision.REJECT if any(c.outcome == 'FALSE' for c in checks) else (
                    Decision.NEEDS_REVIEW if any(c.outcome == 'UNKNOWN' for c in checks) else Decision.ACCEPT)
                decisions.append(outcome)
                usages = {u.record_id: u for u in snapshot.records if u.kind == 'usage'}
                usage = usages.get(r.data.get('usage_ref'))
                evidence.append({'consumer_id': requirement.consumer_id, 'domain_id': requirement.consumer_domain,
                    'obligation_id': requirement.obligation_id, 'obligation_version': requirement.obligation_version,
                    'record_ref': f'{r.record_id}@{r.version}', 'evidence_ref': r.evidence_ref,
                    'field_paths': usage.data['field_paths'] if usage else [], 'decision': outcome.value,
                    'checks': [c.model_dump(mode='json') for c in checks]})
            if snapshot.completeness != 'complete': decisions.append(Decision.NEEDS_REVIEW)
            # Explicitly confirmed zero-consumer boundary is legitimate, unlike missing coverage.
            if not decisions and snapshot.completeness == 'complete' and not snapshot.required_consumer_ids:
                schema = _schema_checks(snapshot.old_contract, snapshot.new_contract)
                decisions.append(Decision.REJECT if any(c.outcome == 'FALSE' for c in schema) else Decision.ACCEPT)
            decision = finalize(decisions)
            current = self.store.is_current(snapshot, at)
            state = 'ABORTED' if not current else {Decision.ACCEPT: 'COMMITTED', Decision.REJECT: 'QUARANTINED', Decision.NEEDS_REVIEW: 'ESCALATED'}[decision]
            reasons = sorted(set(snapshot.issues + [c['reason_code'] for e in evidence for c in e['checks'] if c['outcome'] != 'TRUE'] + ([] if current else ['snapshot_changed_before_commit'])))
            result = MappedRelease(proposal_id=snapshot.proposal_id, run_id=run_id, snapshot_id=snapshot_id,
                decision=decision, terminal_state=state,
                release_id=digest({'proposal_id': snapshot.proposal_id, 'snapshot_id': snapshot_id}) if state == 'COMMITTED' else None,
                reasons=reasons, evidence=sorted(evidence, key=lambda e: e['record_ref']),
                state_trace=['RECEIVED', 'SNAPSHOT_LOCKED', 'LOCALLY_VALIDATED', 'DECIDED', state])
            self._runs[run_id] = (fingerprint, result)
            return result.model_copy(deep=True)
