"""Synthetic-only local pilot controller, with a durable single-file ledger.

The public deterministic signing keys below are TEST fixtures, not credentials.
Never use this controller as a production owner-confirmation service.
"""
import base64
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .evidence_release import EvidenceKnowledgeStore, EvidenceReleaseEngine
from .evidence_snapshot import SignedConfirmation, evidence_subject
from .knowledge import Authority, KnowledgeRecord, canonical
from .models import DataContract, Migration

START = datetime(2026, 10, 15, tzinfo=timezone.utc)
PRODUCT = 'pilot-spending'


class SyntheticPilot:
    def __init__(self, directory):
        self.path = Path(directory) / 'pilot-ledger.json'
        self.keys = {actor: Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
                     for actor, seed in [('pilot-producer', 11), ('pilot-consumer', 12)]}
        self.domains = {'pilot-producer': 'fintech', 'pilot-consumer': 'retail'}
        self.trust = {actor: (self.domains[actor], key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
                      for actor, key in self.keys.items()}
        self.authorities = [Authority(actor=a, domain=d, kinds=k, authority_ref='test-grant:' + a)
                            for a, d, k in [('pilot-producer', 'fintech', ['team', 'product', 'attribute']),
                                            ('pilot-consumer', 'retail', ['team', 'usage', 'obligation']),
                                            ('pilot-registry', 'federation', ['coverage', 'constitution'])]]
        self.migrations = [Migration(dimension='unit_scale', source='kopeck:0', target='RUB:2',
                                    expression='value / 100', validated_examples=3)]
        self.fixtures = [[{'input': '10050', 'expected': '100.5'},
                          {'input': '-4225', 'expected': '-42.25'}, {'input': '0', 'expected': '0'}]]
        self.refs = ['synthetic:consumer-rub-expectations-v1']
        self.reload()
        if not self.store._snapshots:
            self._seed()
        self.snapshot = next(self.store.resolve_snapshot(sid) for sid in self.store._snapshots
                             if self.store._snapshots[sid].proposal_id == 'pilot-change-v1')

    def reload(self):
        self.store = EvidenceKnowledgeStore(self.authorities, self.path, confirmation_keys=self.trust,
                                            required_products=[PRODUCT])

    def _seed(self):
        old = DataContract(product_id=PRODUCT, contract_version='1', owner_domain='fintech',
                           schema_fields={'amount': 'decimal'}, semantic=dict(meaning='Total spend',
                           formula='sum(amount)', unit='RUB', scale=2, identity_scope='user',
                           allowed_sources=['transactions'], purposes=['retail']))
        new = old.model_copy(deep=True)
        new.contract_version, new.semantic.unit, new.semantic.scale = '2', 'kopeck', 0
        records = [
            ('producer-team', 'team', 'fintech', 'pilot-producer', dict(team_id='producer', domain_id='fintech', authority_ref='test-grant:pilot-producer')),
            ('consumer-team', 'team', 'retail', 'pilot-consumer', dict(team_id='consumer', domain_id='retail', authority_ref='test-grant:pilot-consumer')),
            ('product', 'product', 'fintech', 'pilot-producer', dict(product_id=PRODUCT, producer_team_ref='producer-team', contract=old.model_dump(mode='json'))),
            ('amount', 'attribute', 'fintech', 'pilot-producer', dict(product_id=PRODUCT, field_path='amount', semantic_profile_ref='synthetic:spend', contract_version='1')),
            ('retail-use', 'usage', 'retail', 'pilot-consumer', dict(product_id=PRODUCT, consumer_id='retail-report', consumer_team_ref='consumer-team', field_paths=['amount'], purpose='retail', calculation_ref='synthetic:sum', registration_ref='synthetic:registry')),
            ('retail-requirement', 'obligation', 'retail', 'pilot-consumer', dict(usage_ref='retail-use', requirement=dict(obligation_id='rub-total', obligation_version='1', consumer_id='retail-report', consumer_domain='retail', product_id=PRODUCT, accepted_units=['RUB'], accepted_scales=[2], required_formula='sum(amount)'))),
            ('coverage', 'coverage', 'federation', 'pilot-registry', dict(product_id=PRODUCT, membership_epoch=1, registered_consumer_ids=['retail-report'], registry_evidence_ref='synthetic:registry', registration_boundary='synthetic registered consumer only', authority_ref='test-grant:pilot-registry')),
            ('constitution', 'constitution', 'federation', 'pilot-registry', dict(product_id=PRODUCT, constitution_ref='synthetic:constitution', constitution_version='1', content_hash='synthetic'))]
        for index, (rid, kind, domain, actor, data) in enumerate(records):
            at = START + timedelta(seconds=index * 2)
            self.store.propose_record(KnowledgeRecord(record_id=rid, version=1, kind=kind, owner_domain=domain,
                                                     valid_from=at, evidence_ref='synthetic:source', data=data), actor, at)
            self.store.confirm_record(rid, actor, 'synthetic:record-confirmation', at + timedelta(seconds=1))
        self.store.build_snapshot('pilot-change-v1', old, new, START + timedelta(minutes=1))

    def now(self):
        events = self.store.release_journal()
        return max(START + timedelta(minutes=5),
                   datetime.fromisoformat(events[-1]['at']) + timedelta(seconds=1) if events else START)

    def subject(self):
        return evidence_subject(self.snapshot, self.migrations, self.fixtures, self.refs)['subject_hash']

    def _confirm(self, actor, status):
        previous = next((r for r in self.store.confirmation_view(self.subject()) if r.actor == actor), None)
        at = self.now()
        statement = SignedConfirmation(actor=actor, domain=self.domains[actor], subject_hash=self.subject(),
                        version=previous.version + 1 if previous else 1, status=status,
                        evidence_ref='synthetic:explicit-owner-action', valid_from=at,
                        valid_until=at + timedelta(days=1), signature='')
        statement.signature = base64.b64encode(self.keys[actor].sign(canonical(statement.payload()).encode())).decode()
        self.store.append_confirmation(statement, at)

    def action(self, action):
        if action == 'approve':
            for actor in self.keys: self._confirm(actor, 'confirmed')
        elif action == 'revoke':
            self._confirm('pilot-consumer', 'revoked')
        elif action == 'restart':
            self.reload()
        elif action == 'authorize':
            at = self.now()
            bundle = self.store.evidence_snapshot(self.snapshot.snapshot_id, self.migrations, self.fixtures, self.refs, at)
            EvidenceReleaseEngine(self.store).run(self.snapshot.snapshot_id, 'pilot-run-' + str(len(self.store.release_journal())),
                                                   at, self.migrations, self.fixtures, self.refs, bundle)
        else:
            raise ValueError('unknown synthetic pilot action')
        return self.state()

    def state(self):
        bundle = self.store.evidence_snapshot(self.snapshot.snapshot_id, self.migrations, self.fixtures, self.refs, self.now())
        decisions = [e['result'] for e in self.store.release_journal() if e['kind'] == 'evidence_decision_v1']
        return dict(dataset='SYNTHETIC ONLY', clock='logical demo clock, not wall-clock time',
                    current_evidence_decision=bundle['decision'], issues=bundle['issues'],
                    confirmations=[dict(actor=r.actor, domain=r.domain, status=r.status, version=r.version)
                                   for r in self.store.confirmation_view(self.subject())],
                    last_decision=decisions[-1] if decisions else None,
                    historical_authorizations=len(self.store._release_commits),
                    journal_events=len(self.store.release_journal()),
                    publication_executed=False)
