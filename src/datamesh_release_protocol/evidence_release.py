"""Opt-in evidence-aware coordinator using the existing single-file journal.

Confirmations and authorization events share KnowledgeStore atomic persistence,
failure fencing, run IDs, release IDs, target-version uniqueness and publication
acknowledgements. This records permission, not physical publication.
"""
import copy
from datetime import datetime
from pathlib import Path

from .evidence_snapshot import ConfirmationRegistry, SignedConfirmation, build_evidence_snapshot, fence_evidence_snapshot
from .knowledge import KnowledgeStore, digest, utc
from .knowledge_release import MappedRelease, build_release, change_key, target_key
from .models import Decision, Migration

POLICY = 'evidence-release-1'
CONFIRMATION = 'evidence_confirmation_v1'
DECISION = 'evidence_decision_v1'


def fingerprint(snapshot_id, migrations, fixtures, refs, bundle):
    return digest(dict(policy=POLICY, snapshot_id=snapshot_id,
                       migrations=[m.model_dump(mode='json') for m in migrations],
                       fixtures=fixtures, refs=refs, bundle=bundle))


def build_strict_release(store, snapshot, run_id, at, migrations, fixtures, refs, bundle):
    base = build_release(store, snapshot, run_id, at, migrations)
    fence = fence_evidence_snapshot(bundle, snapshot, migrations, fixtures, refs,
                                    store._confirmations, store, at)
    fresh = build_evidence_snapshot(snapshot, migrations, fixtures, refs, store._confirmations, at)
    reasons = set(base.reasons + fresh['issues'] + fence['reasons'])
    if not fence['current'] or base.terminal_state == 'ABORTED':
        state, decision = 'ABORTED', Decision.NEEDS_REVIEW
    else:
        decisions = {base.decision.value, fresh['decision']}
        decision = (Decision.REJECT if 'REJECT' in decisions else
                    Decision.NEEDS_REVIEW if 'NEEDS_REVIEW' in decisions else Decision.ACCEPT)
        state = ('QUARANTINED' if decision == Decision.REJECT else
                 'ESCALATED' if decision == Decision.NEEDS_REVIEW else base.terminal_state)
    result = base.model_dump(mode='json')
    result.update(decision=decision.value, terminal_state=state,
                  release_id=base.release_id if state in ('COMMITTED', 'ALREADY_COMMITTED') else None,
                  reasons=sorted(reasons),
                  state_trace=['RECEIVED', 'SNAPSHOT_LOCKED', 'EVIDENCE_RECHECKED', 'DECIDED', state],
                  evidence=base.evidence + [dict(kind=POLICY, evidence_snapshot_id=bundle['evidence_snapshot_id'],
                                               subject_hash=bundle['subject_hash'],
                                               receipt_hashes=[r['receipt_hash'] for r in fresh['receipts']])])
    return MappedRelease.model_validate(result)


class EvidenceKnowledgeStore(KnowledgeStore):
    """Single-process writer per POSIX ledger; competing copies fail closed.

    Caller supplies trusted keys and products requiring evidence. Existing files
    can be loaded; new event kinds fail closed in an old KnowledgeStore reader.
    Trusted configuration must be maintained outside the writable ledger.
    """
    def __init__(self, authorities, path: Path, *, confirmation_keys, required_products):
        if path is None:
            raise ValueError('evidence coordinator requires a persistent ledger path')
        self._confirmations = ConfirmationRegistry(confirmation_keys)
        self.required_products = frozenset(required_products)
        if not self.required_products:
            raise ValueError('explicit evidence-required product configuration is required')
        super().__init__(authorities, Path(path))
        # One ordering/lock protects confirmation updates and authorization.
        self._confirmations.lock = self.lock

    def append_confirmation(self, record: SignedConfirmation, at: datetime):
        record = SignedConfirmation.model_validate(record.model_dump(mode='json'))
        at = utc(at)
        if record.valid_from != at:
            raise ValueError('confirmation effective time must equal journal event time')
        with self.lock:
            self._save_release_event(dict(kind=CONFIRMATION, policy=POLICY,
                                          trust_hash=self._confirmations.trust_hash,
                                          record=record.model_dump(mode='json'), at=at.isoformat()))

    def evidence_snapshot(self, snapshot_id, migrations, fixtures, refs, at):
        with self.lock:
            self._ensure_healthy()
            snapshot = self.resolve_snapshot(snapshot_id)
            return build_evidence_snapshot(snapshot, migrations, fixtures, refs, self._confirmations, at)

    def confirmation_view(self, subject_hash):
        with self.lock:
            self._ensure_healthy()
            return self._confirmations.view(subject_hash)

    def _save_release_event(self, event):
        if event['kind'] in ('decision', 'distributed_decision'):
            snapshot = self.resolve_snapshot(event['result']['snapshot_id'])
            if snapshot.product_id in self.required_products:
                raise ValueError('evidence-required product must use EvidenceReleaseEngine')
        return super()._save_release_event(event)

    def _index_release_event(self, event):
        if event['kind'] == CONFIRMATION:
            if event.get('policy') != POLICY or event['trust_hash'] != self._confirmations.trust_hash:
                raise ValueError('confirmation trust configuration mismatch')
            record = SignedConfirmation.model_validate(event['record'])
            if record.valid_from != utc(datetime.fromisoformat(event['at'])):
                raise ValueError('confirmation journal chronology mismatch')
            self._confirmations.append(record)
            return
        if event['kind'] != DECISION:
            return super()._index_release_event(event)
        if event.get('policy') != POLICY:
            raise ValueError('unsupported evidence release policy')
        result = MappedRelease.model_validate(event['result'])
        snapshot = self.resolve_snapshot(result.snapshot_id)
        if snapshot.product_id not in self.required_products:
            raise ValueError('evidence policy missing for journal product')
        at = utc(datetime.fromisoformat(event['at']))
        migrations = [Migration.model_validate(m) for m in event['migrations']]
        expected = build_strict_release(self, snapshot, result.run_id, at, migrations,
                                        event['fixtures'], event['refs'], event['bundle'])
        if result != expected:
            raise ValueError('evidence journal decision does not reproduce')
        expected_fingerprint = fingerprint(snapshot.snapshot_id, migrations, event['fixtures'], event['refs'], event['bundle'])
        if event['fingerprint'] != expected_fingerprint or result.run_id in self._release_runs:
            raise ValueError('invalid evidence run fingerprint or duplicate run')
        if result.terminal_state == 'COMMITTED':
            key, target = change_key(snapshot), target_key(snapshot)
            if key in self._release_commits or target in self._release_targets or result.release_id != key:
                raise ValueError('duplicate evidence release authorization')
            self._release_commits[key] = event
            self._release_targets[target] = key
        elif result.terminal_state == 'ALREADY_COMMITTED':
            if result.release_id != change_key(snapshot) or result.release_id not in self._release_commits:
                raise ValueError('missing original authorization')
        self._release_runs[result.run_id] = event


class EvidenceReleaseEngine:
    def __init__(self, store: EvidenceKnowledgeStore):
        self.store = store

    def run(self, snapshot_id, run_id, at, migrations, fixtures, refs, bundle):
        # Copy all caller-owned data before checking and persisting it.
        migrations = [Migration.model_validate(m.model_dump(mode='json')) for m in migrations]
        fixtures, refs, bundle = copy.deepcopy((fixtures, refs, bundle))
        at = utc(at)
        with self.store.lock:
            self.store._ensure_healthy()
            snapshot = self.store.resolve_snapshot(snapshot_id)
            if snapshot.product_id not in self.store.required_products:
                raise ValueError('product is not configured for the evidence release policy')
            if at < snapshot.as_of:
                raise ValueError('authorization precedes knowledge snapshot')
            request = fingerprint(snapshot_id, migrations, fixtures, refs, bundle)
            if run_id in self.store._release_runs:
                prior = self.store._release_runs[run_id]
                if prior['fingerprint'] != request:
                    raise ValueError('run_id reused with conflicting evidence')
                # Historical receipt, not a new check of approval validity.
                return MappedRelease.model_validate(prior['result'])
            result = build_strict_release(self.store, snapshot, run_id, at, migrations, fixtures, refs, bundle)
            self.store._save_release_event(dict(kind=DECISION, policy=POLICY, fingerprint=request,
                                               at=at.isoformat(), migrations=[m.model_dump(mode='json') for m in migrations],
                                               fixtures=fixtures, refs=refs, bundle=bundle,
                                               result=result.model_dump(mode='json')))
            return result.model_copy(deep=True)
