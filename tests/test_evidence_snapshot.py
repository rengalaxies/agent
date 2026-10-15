import base64
from datetime import timedelta
import unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from test_knowledge import fixture, T
from datamesh_release_protocol.knowledge import canonical, digest
from datamesh_release_protocol.models import Migration
from datamesh_release_protocol.evidence_snapshot import (
    SignedConfirmation, ConfirmationRegistry, evidence_subject, build_evidence_snapshot,
    fence_evidence_snapshot, evidence_links,
)


class EvidenceSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.store, old, new = fixture()
        self.snapshot = self.store.build_snapshot('evidence', old, new, T + timedelta(seconds=2))
        # Publicly reproducible TEST ONLY keys, never deployment credentials.
        self.keys = {actor: Ed25519PrivateKey.from_private_bytes(bytes([seed]) * 32)
                     for actor, seed in [('producer', 1), ('consumer', 2)]}
        self.domains = {'producer': 'sales', 'consumer': 'risk'}
        self.registry = ConfirmationRegistry({actor: (self.domains[actor], key.public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw)) for actor, key in self.keys.items()})
        self.migrations = [Migration(dimension='unit_scale', source='kopeck:0', target='RUB:2',
                                    expression='value / 100', validated_examples=1)]
        self.fixtures = [[{'input': '123', 'expected': '1.23'}]]
        self.refs = ['git:test-fixtures@commit-1']
        self.now = T + timedelta(seconds=4)

    def subject(self):
        return evidence_subject(self.snapshot, self.migrations, self.fixtures, self.refs)['subject_hash']

    def confirmation(self, actor, **changes):
        payload = dict(actor=actor, domain=self.domains[actor], subject_hash=self.subject(), version=1,
                       status='confirmed', evidence_ref='review:test-owner', valid_from=T + timedelta(seconds=3),
                       valid_until=T + timedelta(seconds=30))
        record = SignedConfirmation(**(payload | changes), signature='')
        record.signature = base64.b64encode(self.keys[actor].sign(canonical(record.payload()).encode())).decode()
        return record

    def approve(self):
        for actor in self.keys:
            self.registry.append(self.confirmation(actor))

    def build(self, at=None):
        return build_evidence_snapshot(self.snapshot, self.migrations, self.fixtures, self.refs,
                                       self.registry, at or self.now)

    def fence(self, bundle, at=None):
        return fence_evidence_snapshot(bundle, self.snapshot, self.migrations, self.fixtures, self.refs,
                                       self.registry, self.store, at or self.now)

    def test_missing_owner_confirmation_is_review(self):
        result = self.build()
        self.assertEqual(result['decision'], 'NEEDS_REVIEW')
        self.assertEqual(result['required_domains'], ['risk', 'sales'])

    def test_both_domains_confirm_exact_subject(self):
        self.approve()
        result = self.build()
        self.assertEqual(result['decision'], 'ACCEPT')
        self.assertTrue(self.fence(result)['current'])
        self.assertFalse(self.fence(result)['release_authorization'])

    def test_wrong_signer_and_self_declared_domain_are_rejected(self):
        record = self.confirmation('producer')
        record.domain = 'risk'
        with self.assertRaises(ValueError):
            self.registry.append(record)
        record = self.confirmation('producer')
        record.signature = self.confirmation('consumer').signature
        with self.assertRaises(ValueError):
            self.registry.append(record)

    def test_revocation_invalidates_old_snapshot_and_no_version_replay(self):
        self.approve()
        bundle = self.build()
        self.registry.append(self.confirmation('consumer', version=2, status='revoked',
                                               valid_from=self.now))
        result = self.fence(bundle)
        self.assertFalse(result['current'])
        self.assertEqual(result['decision'], 'NEEDS_REVIEW')
        with self.assertRaises(ValueError):
            self.registry.append(self.confirmation('consumer'))

    def test_expiry_invalidates_old_snapshot(self):
        self.approve()
        self.assertFalse(self.fence(self.build(), T + timedelta(seconds=31))['current'])

    def test_changed_migration_fixtures_and_sources_invalidate(self):
        for kind in ['migration', 'fixtures', 'source']:
            with self.subTest(kind=kind):
                self.setUp()
                self.approve()
                bundle = self.build()
                if kind == 'migration':
                    self.migrations[0].expression = 'value * 100'
                elif kind == 'fixtures':
                    self.fixtures[0][0]['expected'] = '999'
                else:
                    self.refs[0] = 'git:changed-source'
                self.assertFalse(self.fence(bundle)['current'])

    def test_new_knowledge_record_invalidates_fence(self):
        self.approve()
        bundle = self.build()
        self.store.revoke_record('coverage', 'registry', 'revoked', self.now)
        self.assertIn('knowledge_changed', self.fence(bundle)['reasons'])

    def test_tamper_rejected_even_when_attacker_rehashes(self):
        bundle = self.build()
        bundle['decision'] = 'ACCEPT'
        with self.assertRaises(ValueError):
            self.fence(bundle)
        bundle['evidence_snapshot_id'] = digest({k: v for k, v in bundle.items()
                                                if k != 'evidence_snapshot_id'})
        self.assertFalse(self.fence(bundle)['current'])

    def test_confirmation_for_another_subject_does_not_count(self):
        self.registry.append(self.confirmation('producer', subject_hash='0' * 64))
        self.registry.append(self.confirmation('consumer'))
        self.assertIn('unconfirmed_domain:sales', self.build()['issues'])

    def test_future_confirmation_not_active(self):
        self.registry.append(self.confirmation('producer', valid_from=T + timedelta(seconds=20)))
        self.registry.append(self.confirmation('consumer'))
        self.assertEqual(self.build()['decision'], 'NEEDS_REVIEW')

    def test_no_migration_does_not_add_new_approval_requirement(self):
        self.migrations, self.fixtures, self.refs = [], [], []
        self.assertEqual(self.build()['decision'], 'ACCEPT')

    def test_links_expose_fixture_and_confirmation_paths(self):
        self.approve()
        bundle = self.build()
        graph = evidence_links(bundle)
        self.assertEqual(graph, evidence_links(bundle))
        self.assertEqual({e['relation'] for e in graph['edges']},
                         {'contains', 'verified_by', 'tested_on', 'attests_subject'})
        self.assertEqual(len([n for n in graph['nodes'] if n['kind'] == 'domain_confirmation']), 2)
        self.assertEqual([n['evidence_ref'] for n in graph['nodes'] if n['kind'] == 'fixture_evidence'],
                         self.refs)

    def test_registry_does_not_alias_caller_records(self):
        record = self.confirmation('producer')
        self.registry.append(record)
        record.status = 'revoked'
        returned = self.registry.view(self.subject())
        returned[0].status = 'revoked'
        self.assertEqual(self.registry.view(self.subject())[0].status, 'confirmed')

    def test_invalid_provenance_and_pre_snapshot_time_fail(self):
        self.refs = ['']
        with self.assertRaises(ValueError):
            self.build()
        self.refs = ['fixture:1']
        with self.assertRaises(ValueError):
            self.build(T)
