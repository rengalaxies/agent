"""Versioned advisory evidence snapshots with signed domain confirmations.

No publication capability is issued. The in-memory approval registry must be
backed by durable authenticated storage before production use.
"""
from __future__ import annotations

import base64
import copy
from datetime import datetime
from threading import RLock

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field, model_validator

from .knowledge import KnowledgeSnapshot, canonical, digest, utc
from .knowledge_release import evaluate_snapshot
from .migration_evidence import verify_migration
from .models import StrictModel, Migration

VERSION = 'migration-evidence-snapshot-1'


class SignedConfirmation(StrictModel):
    actor: str = Field(min_length=1)
    domain: str = Field(min_length=1)
    subject_hash: str = Field(pattern=r'^[0-9a-f]{64}$')
    version: int = Field(ge=1)
    status: str = Field(pattern=r'^(confirmed|revoked)$')
    evidence_ref: str = Field(min_length=1)
    valid_from: datetime
    valid_until: datetime
    signature: str

    @model_validator(mode='after')
    def interval(self):
        if utc(self.valid_until) <= utc(self.valid_from):
            raise ValueError('invalid confirmation interval')
        return self

    def payload(self):
        return self.model_dump(mode='json', exclude={'signature'})


class ConfirmationRegistry:
    """Trusted configuration maps actor -> (domain, raw Ed25519 public key).

    Submitted records cannot grant authority to themselves. Versions/revocations
    are monotonic within an actor and subject. No fallback to an older approval.
    """
    def __init__(self, trusted_keys: dict[str, tuple[str, bytes]]):
        self._keys = copy.deepcopy(trusted_keys)
        self._latest = {}
        self.lock = RLock()
        for _, key in self._keys.values():
            Ed25519PublicKey.from_public_bytes(key)

    @property
    def trust_hash(self):
        return digest({actor: [domain, key.hex()] for actor, (domain, key) in self._keys.items()})

    def append(self, confirmation: SignedConfirmation):
        record = confirmation.model_copy(deep=True)
        grant = self._keys.get(record.actor)
        if not grant or grant[0] != record.domain:
            raise ValueError('actor has no confirmation authority in this domain')
        try:
            signature = base64.b64decode(record.signature, validate=True)
            Ed25519PublicKey.from_public_bytes(grant[1]).verify(signature, canonical(record.payload()).encode())
        except (ValueError, InvalidSignature) as exc:
            raise ValueError('invalid confirmation signature') from exc
        with self.lock:
            key = (record.actor, record.subject_hash)
            prior = self._latest.get(key)
            if record.version != (prior.version + 1 if prior else 1):
                raise ValueError('non-monotonic confirmation version')
            if prior and record.valid_from < prior.valid_from:
                raise ValueError('confirmation chronology regression')
            self._latest[key] = record

    def view(self, subject):
        with self.lock:
            return [r.model_copy(deep=True) for _, r in sorted(self._latest.items())
                    if r.subject_hash == subject]


def evidence_subject(snapshot: KnowledgeSnapshot, migrations: list[Migration], fixture_sets: list,
                     fixture_refs: list[str]) -> dict:
    snapshot.verify()
    if len(migrations) != len(fixture_sets) or len(migrations) != len(fixture_refs):
        raise ValueError('each migration needs exactly one fixture set and provenance reference')
    if any(not isinstance(ref, str) or not ref.strip() for ref in fixture_refs):
        raise ValueError('fixture provenance references must be nonempty')
    receipts = [verify_migration(m, copy.deepcopy(f)) for m, f in zip(migrations, fixture_sets)]
    payload = dict(format=VERSION, knowledge_snapshot_id=snapshot.snapshot_id,
                   receipts=receipts, fixture_refs=list(fixture_refs))
    return {**payload, 'subject_hash': digest(payload)}


def build_evidence_snapshot(snapshot, migrations, fixture_sets, fixture_refs, registry, at):
    """Require producer and mandatory consumer/rule domains for any migration.

    This is a conservative opt-in policy, not the existing V2 protocol policy.
    A confirmation signs the entire subject, including expected fixture values.
    """
    at = utc(at)
    if at < snapshot.as_of:
        raise ValueError('evidence cannot be evaluated before knowledge snapshot')
    subject = evidence_subject(snapshot, migrations, fixture_sets, fixture_refs)
    required = ({snapshot.old_contract.owner_domain} | {
        r.owner_domain for r in snapshot.records
        if r.kind == 'global_rule' or (r.kind == 'obligation' and r.data['mandatory'])
    }) if migrations else set()
    confirmations = registry.view(subject['subject_hash'])
    confirmed = {r.domain for r in confirmations if r.status == 'confirmed'
                 and r.valid_from <= at < r.valid_until}
    issues = [f'unconfirmed_domain:{domain}' for domain in sorted(required - confirmed)]
    # Knowledge validity must also be fenced against the live store by the caller.
    if any(r.valid_until and r.valid_until <= at for r in snapshot.records):
        issues.append('knowledge_expired')
    base, _ = evaluate_snapshot(snapshot, migrations)
    decisions = {base.value, *(r['decision'] for r in subject['receipts'])}
    if issues:
        decisions.add('NEEDS_REVIEW')
    decision = ('REJECT' if 'REJECT' in decisions else
                'NEEDS_REVIEW' if 'NEEDS_REVIEW' in decisions else 'ACCEPT')
    payload = dict(**subject, trust_hash=registry.trust_hash, required_domains=sorted(required),
                   confirmations=[r.model_dump(mode='json') for r in confirmations],
                   decision=decision, issues=issues, release_authorization=False)
    return {**payload, 'evidence_snapshot_id': digest(payload)}


def fence_evidence_snapshot(bundle, knowledge_snapshot, migrations, fixture_sets, fixture_refs,
                            registry, store, at):
    """Recompute under both locks; result is advisory and not an atomic publish.

    `current` refers to the instant of this check only. A later publication needs
    this fence inside its own authorization transaction.
    """
    with registry.lock, store.lock:
        if digest({k: v for k, v in bundle.items() if k != 'evidence_snapshot_id'}) != bundle.get('evidence_snapshot_id'):
            raise ValueError('evidence snapshot integrity failure')
        current = build_evidence_snapshot(knowledge_snapshot, migrations, fixture_sets, fixture_refs, registry, at)
        reasons = []
        if not store.is_current(knowledge_snapshot, at):
            reasons.append('knowledge_changed')
        if current['evidence_snapshot_id'] != bundle['evidence_snapshot_id']:
            reasons.append('evidence_or_confirmation_changed')
        return dict(current=not reasons, decision=current['decision'] if not reasons else 'NEEDS_REVIEW',
                    reasons=reasons, release_authorization=False)


def evidence_links(bundle):
    """Graph extension with explicit links to fixture sources and confirmations."""
    if digest({k: v for k, v in bundle.items() if k != 'evidence_snapshot_id'}) != bundle.get('evidence_snapshot_id'):
        raise ValueError('evidence snapshot integrity failure')
    nodes = [{'id': 'snapshot:' + bundle['evidence_snapshot_id'], 'kind': 'evidence_snapshot'}]
    edges = []
    root = nodes[0]['id']
    for index, receipt in enumerate(bundle['receipts']):
        migration = 'migration:' + digest(receipt['migration'])
        check = 'receipt:' + receipt['receipt_hash']
        source = 'fixture:' + digest({'input': receipt['input_hash'], 'ref': bundle['fixture_refs'][index]})
        nodes.extend([dict(id=migration, kind='migration'), dict(id=check, kind='verification_receipt'),
                      dict(id=source, kind='fixture_evidence', evidence_ref=bundle['fixture_refs'][index])])
        edges.extend([dict(source=root, target=migration, relation='contains'),
                      dict(source=migration, target=check, relation='verified_by'),
                      dict(source=check, target=source, relation='tested_on')])
    for confirmation in bundle['confirmations']:
        identifier = 'confirmation:' + digest(confirmation)
        nodes.append(dict(id=identifier, kind='domain_confirmation', **confirmation))
        edges.append(dict(source=identifier, target=root, relation='attests_subject'))
    return dict(format=VERSION, knowledge_snapshot_id=bundle['knowledge_snapshot_id'],
                nodes=sorted({n['id']: n for n in nodes}.values(), key=lambda n: n['id']),
                edges=sorted({canonical(e): e for e in edges}.values(), key=canonical),
                guarantee='signed expectations and listed executable fixtures only')
