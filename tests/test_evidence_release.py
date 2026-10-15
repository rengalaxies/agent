import copy
from datetime import timedelta
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread, Barrier
import unittest
from unittest.mock import patch

from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
import test_evidence_snapshot as memory_fixture
from test_knowledge import fixture, T
from datamesh_release_protocol.evidence_release import EvidenceKnowledgeStore, EvidenceReleaseEngine
from datamesh_release_protocol.evidence_snapshot import build_evidence_snapshot
from datamesh_release_protocol.knowledge import KnowledgeStore, digest
from datamesh_release_protocol.knowledge_release import KnowledgeReleaseEngine


class DurableEvidenceTests(unittest.TestCase):
    subject = memory_fixture.EvidenceSnapshotTests.subject
    confirmation = memory_fixture.EvidenceSnapshotTests.confirmation

    def setUp(self):
        memory_fixture.EvidenceSnapshotTests.setUp(self)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / 'ledger.json'
        original, old, new = fixture(self.path)
        self.authorities = list(original.authorities)
        self.trust = {actor: (self.domains[actor], key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
                      for actor, key in self.keys.items()}
        self.store = self.reload()
        self.snapshot = self.store.build_snapshot('durable-evidence', old, new, T + timedelta(seconds=2))

    def reload(self):
        return EvidenceKnowledgeStore(self.authorities, self.path, confirmation_keys=self.trust,
                                      required_products=['active-users'])

    def persist_approvals(self):
        for actor in self.keys:
            self.store.append_confirmation(self.confirmation(actor), T + timedelta(seconds=3))

    def strict_bundle(self, at=None):
        return self.store.evidence_snapshot(self.snapshot.snapshot_id, self.migrations, self.fixtures,
                                            self.refs, at or self.now)

    def authorize(self, run_id='strict-run', bundle=None, at=None, store=None):
        return EvidenceReleaseEngine(store or self.store).run(self.snapshot.snapshot_id, run_id,
                    at or self.now, self.migrations, self.fixtures, self.refs,
                    bundle if bundle is not None else self.strict_bundle())

    def test_durable_restart_reproduces_authorization_and_exact_retry(self):
        self.persist_approvals()
        bundle = self.strict_bundle()
        result = self.authorize(bundle=bundle)
        self.assertEqual(result.terminal_state, 'COMMITTED')
        restored = self.reload()
        self.assertEqual(self.authorize(bundle=bundle, store=restored), result)
        self.assertEqual(len(restored.pending_publications()), 1)
        self.assertEqual(len(restored.confirmation_view(self.subject())), 2)

    def test_revocation_survives_restart_and_blocks_new_authorization(self):
        self.persist_approvals()
        old_bundle = self.strict_bundle()
        self.store.append_confirmation(self.confirmation('consumer', version=2, status='revoked',
                                      valid_from=self.now), self.now)
        restored = self.reload()
        result = self.authorize(bundle=old_bundle, store=restored, at=self.now + timedelta(seconds=1))
        self.assertEqual(result.terminal_state, 'ABORTED')
        self.assertIsNone(result.release_id)
        self.assertEqual(restored.confirmation_view(self.subject())[0].status, 'revoked')

    def test_fresh_bundle_without_confirmations_is_not_authorized(self):
        result = self.authorize()
        self.assertEqual(result.terminal_state, 'ESCALATED')
        self.assertIsNone(result.release_id)
        self.reload()

    def test_expiry_between_snapshot_and_commit_aborts(self):
        self.persist_approvals()
        result = self.authorize(bundle=self.strict_bundle(), at=T + timedelta(seconds=31))
        self.assertEqual(result.terminal_state, 'ABORTED')
        self.assertIsNone(result.release_id)

    def test_legacy_coordinator_cannot_bypass_required_policy(self):
        with self.assertRaises(ValueError):
            KnowledgeReleaseEngine(self.store).run(self.snapshot.snapshot_id, 'bypass', self.now, self.migrations)
        self.assertFalse(self.store.pending_publications())

    def test_conflicting_run_payload_is_rejected(self):
        self.persist_approvals()
        self.authorize()
        self.refs = ['another-fixture-source']
        with self.assertRaises(ValueError):
            self.authorize()

    def test_concurrent_same_run_produces_one_journal_authorization(self):
        self.persist_approvals()
        bundle = self.strict_bundle()
        barrier = Barrier(2)
        results, errors = [], []
        def run():
            try:
                barrier.wait()
                results.append(self.authorize(bundle=bundle))
            except Exception as exc:
                errors.append(exc)
        threads = [Thread(target=run) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join(timeout=10)
        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertFalse(errors)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0], results[1])
        self.assertEqual(len(self.store.pending_publications()), 1)
        self.assertEqual(len([e for e in self.store.release_journal() if e['kind'] == 'evidence_decision_v1']), 1)

    def test_stale_second_writer_fails_closed(self):
        stale = self.reload()
        self.persist_approvals()
        with self.assertRaises(ValueError):
            stale.append_confirmation(self.confirmation('producer'), T + timedelta(seconds=3))

    def test_revocation_racing_between_check_and_write_prevents_permission(self):
        self.persist_approvals()
        bundle = self.strict_bundle()
        other_writer = self.reload()
        original_persist = self.store._persist
        def concurrent_revocation():
            other_writer.append_confirmation(self.confirmation('consumer', version=2, status='revoked',
                                              valid_from=self.now), self.now)
            original_persist()
        with patch.object(self.store, '_persist', side_effect=concurrent_revocation):
            with self.assertRaises(ValueError): self.authorize(bundle=bundle)
        restored = self.reload()
        self.assertFalse(restored.pending_publications())
        self.assertEqual(restored.confirmation_view(self.subject())[0].status, 'revoked')

    def test_write_failure_cannot_return_a_permission(self):
        self.persist_approvals()
        bundle = self.strict_bundle()
        with patch('datamesh_release_protocol.knowledge.os.replace', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                self.authorize(bundle=bundle)
        with self.assertRaises(ValueError):
            self.store.pending_publications()
        restored = self.reload()
        self.assertFalse(restored.pending_publications())
        self.assertEqual(self.authorize(bundle=bundle, store=restored).terminal_state, 'COMMITTED')

    def test_failed_confirmation_write_cannot_supply_cached_approval(self):
        with patch('datamesh_release_protocol.knowledge.os.replace', side_effect=OSError('injected failure')):
            with self.assertRaises(OSError):
                self.store.append_confirmation(self.confirmation('producer'), T + timedelta(seconds=3))
        with self.assertRaises(ValueError): self.strict_bundle()
        restored = self.reload()
        self.assertFalse(restored.confirmation_view(self.subject()))

    def test_changed_trusted_keys_do_not_silently_restore_history(self):
        self.persist_approvals()
        self.trust['pilot-unknown'] = ('fintech', self.trust['producer'][1])
        with self.assertRaises(ValueError): self.reload()

    def test_failure_after_replace_recovers_one_committed_record(self):
        self.persist_approvals()
        bundle = self.strict_bundle()
        import os
        real_fsync = os.fsync
        calls = []
        def fail_directory(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError('injected directory fsync failure')
            return real_fsync(fd)
        with patch('datamesh_release_protocol.knowledge.os.fsync', side_effect=fail_directory):
            with self.assertRaises(OSError):
                self.authorize(bundle=bundle)
        restored = self.reload()
        self.assertEqual(len(restored.pending_publications()), 1)
        self.assertEqual(self.authorize(bundle=bundle, store=restored).terminal_state, 'COMMITTED')
        self.assertEqual(len(restored.pending_publications()), 1)

    def test_shared_target_version_uniqueness(self):
        self.persist_approvals()
        first = self.authorize()
        alternate = self.snapshot.new_contract.model_copy(deep=True)
        alternate.semantic.description = 'different content in same version'
        other = self.store.build_snapshot('other', self.snapshot.old_contract, alternate,
                                         self.now + timedelta(seconds=1))
        bundle = self.store.evidence_snapshot(other.snapshot_id, [], [], [], self.now + timedelta(seconds=1))
        result = EvidenceReleaseEngine(self.store).run(other.snapshot_id, 'other', self.now + timedelta(seconds=1),
                                                       [], [], [], bundle)
        self.assertEqual(result.terminal_state, 'ABORTED')
        self.assertIsNone(result.release_id)
        self.assertEqual(len(self.store.pending_publications()), 1)

    def test_tampered_signature_detected_even_after_rehashing_file(self):
        self.persist_approvals()
        payload = json.loads(self.path.read_text())
        payload['release_events'][0]['record']['signature'] = 'fake'
        previous = None
        for event in payload['release_events']:
            event['previous_hash'] = previous
            event['event_hash'] = digest({k: v for k, v in event.items() if k != 'event_hash'})
            previous = event['event_hash']
        payload['integrity_hash'] = digest({k: v for k, v in payload.items() if k != 'integrity_hash'})
        self.path.write_text(json.dumps(payload))
        with self.assertRaises(ValueError): self.reload()

    def test_old_reader_refuses_new_confirmation_events(self):
        self.persist_approvals()
        with self.assertRaises(ValueError): KnowledgeStore(self.authorities, self.path)

    def test_publication_ack_survives_restart_without_republishing(self):
        self.persist_approvals()
        release = self.authorize()
        self.store.acknowledge_publication(release.release_id, 'test:publisher-receipt', self.now + timedelta(seconds=1))
        restored = self.reload()
        self.assertFalse(restored.pending_publications())
        restored.acknowledge_publication(release.release_id, 'test:publisher-receipt', self.now + timedelta(seconds=2))
        self.assertFalse(restored.pending_publications())
