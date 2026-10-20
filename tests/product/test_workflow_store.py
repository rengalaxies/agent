import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from change_completion.store import RunStore
from change_completion.workflow_store import WorkflowStore


class WorkflowStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'workflow.sqlite'
        self.store = WorkflowStore(self.path)
        self.store.register('run', 'digest', {'analytics': 'alice', 'audit': 'bob'}, 'carol')

    def test_owners_then_acceptor(self):
        with self.assertRaises(ValueError):
            self.store.review('run', 'carol', 'approve', 'digest')
        with self.assertRaises(ValueError):
            self.store.review('run', 'mallory', 'approve', 'digest')
        with self.assertRaises(ValueError):
            self.store.review('run', 'alice', 'approve', 'other')
        first = self.store.review('run', 'alice', 'approve', 'digest', '<script>literal</script>')
        self.assertEqual(set(first['reviews']), {'analytics'})
        self.store.review('run', 'bob', 'approve', 'digest')
        accepted = self.store.review('run', 'carol', 'approve', 'digest')
        self.assertEqual(accepted['status'], 'ACCEPTED_FOR_REVIEW')
        changed = self.store.review('run', 'alice', 'reject', 'digest')
        self.assertEqual(changed['status'], 'REJECTED')

    def test_restart_registration_and_invalidation(self):
        self.store.review('run', 'alice', 'approve', 'digest')
        restarted = WorkflowStore(self.path)
        self.assertIn('analytics', restarted.get('run')['reviews'])
        restarted.register('run', 'digest', {'analytics': 'alice', 'audit': 'bob'}, 'carol')
        with self.assertRaises(ValueError):
            restarted.register('run', 'new', {'analytics': 'alice'}, 'carol')
        restarted.enqueue('run', 'key', 'notification', {'text': 'review'})
        stale = restarted.invalidate('run', 'snapshot changed')
        self.assertEqual(stale['reviews'], {})
        self.assertEqual(stale['outbox'][0]['status'], 'CANCELLED')
        for action in [lambda: restarted.review('run', 'alice', 'approve', 'digest'),
                       lambda: restarted.enqueue('run', 'other', 'pr', {}),
                       lambda: restarted.claim_delivery('key')]:
            with self.assertRaises(ValueError): action()
        self.assertEqual(stale['history'][-1]['kind'], 'INVALIDATED')

    def test_outbox_exact_idempotency_and_collision(self):
        first = self.store.enqueue('run', 'key', 'pr', {'branch': 'candidate'})
        self.assertEqual(first, self.store.enqueue('run', 'key', 'pr', {'branch': 'candidate'}))
        with self.assertRaises(ValueError):
            self.store.enqueue('run', 'key', 'pr', {'branch': 'changed'})
        self.store.register('other', 'digest', {'a': 'alice'}, 'carol')
        with self.assertRaises(ValueError):
            self.store.enqueue('other', 'key', 'pr', {'branch': 'candidate'})
        self.store.claim_delivery('key')
        restarted = WorkflowStore(self.path)
        with self.assertRaises(ValueError): restarted.claim_delivery('key')
        restarted.uncertain('key', 'request timed out')
        with self.assertRaises(ValueError): restarted.claim_delivery('key')
        self.assertEqual(restarted.get('run')['outbox'][0]['status'], 'UNKNOWN')

    def test_delivery_completion_and_receipt(self):
        self.store.enqueue('run', 'key', 'notification', {})
        with self.assertRaises(ValueError): self.store.delivered('key', {'id': '1'})
        self.store.claim_delivery('key')
        self.store.invalidate('run', 'permissions revoked during request')
        # Recording a completed effect must remain possible even after revocation.
        self.store.delivered('key', {'id': '1'})
        self.store.delivered('key', {'id': '1'})
        self.assertEqual(self.store.get('run')['outbox'][0]['receipt'], {'id': '1'})
        with self.assertRaises(ValueError): self.store.delivered('key', {'id': '2'})

    def test_atomic_claim(self):
        self.store.enqueue('run', 'key', 'pr', {})
        def claim(_):
            try:
                WorkflowStore(self.path).claim_delivery('key')
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=4) as pool:
            self.assertEqual(sum(pool.map(claim, range(4))), 1)

    def test_private_database_and_bounds(self):
        with self.assertRaises(ValueError): self.store.review('run', 'alice', 'approve', 'digest', 'x' * 4001)
        other = Path(self.temp.name) / 'runs.sqlite'
        RunStore(other)
        with self.assertRaises(ValueError): WorkflowStore(other)
        link = Path(self.temp.name) / 'link'
        link.symlink_to(self.path)
        with self.assertRaises(ValueError): WorkflowStore(link)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_acceptor_can_also_own_component(self):
        self.store.register('combined', 'digest', {'a': 'carol'}, 'carol')
        self.assertEqual(self.store.review('combined', 'carol', 'approve', 'digest')['status'], 'PENDING')
        self.assertEqual(self.store.review('combined', 'carol', 'approve', 'digest')['status'], 'ACCEPTED_FOR_REVIEW')

    def test_rejection_persists_across_unrelated_owner_review(self):
        self.store.review('run', 'bob', 'reject', 'digest')
        self.assertEqual(self.store.review('run', 'alice', 'approve', 'digest')['status'], 'REJECTED')
        self.assertEqual(self.store.review('run', 'bob', 'approve', 'digest')['status'], 'PENDING')
        self.store.review('run', 'carol', 'reject', 'digest')
        self.assertEqual(self.store.review('run', 'alice', 'approve', 'digest', 'updated comment')['status'], 'REJECTED')
        restarted = WorkflowStore(self.path)
        self.assertEqual(restarted.get('run')['final_review']['decision'], 'reject')
        self.assertEqual(restarted.review('run', 'carol', 'approve', 'digest')['status'], 'ACCEPTED_FOR_REVIEW')

    def test_repeated_invalidation_does_not_grow_history(self):
        first = self.store.invalidate('run', 'changed')
        second = self.store.invalidate('run', 'changed again')
        self.assertEqual(first, second)

    def test_rejection_atomically_blocks_outbox(self):
        self.store.enqueue('run', 'key', 'pr', {})
        self.store.review('run', 'alice', 'reject', 'digest')
        with self.assertRaises(ValueError): self.store.claim_delivery('key')
        with self.assertRaises(ValueError): self.store.enqueue('run', 'other', 'pr', {})
        self.assertEqual(self.store.get('run')['outbox'][0]['status'], 'PENDING')
        self.store.review('run', 'alice', 'approve', 'digest')
        self.assertEqual(self.store.claim_delivery('key')['status'], 'SENDING')

    def test_explicit_reopen_never_restores_approval(self):
        self.store.review('run', 'alice', 'approve', 'digest')
        self.store.review('run', 'bob', 'approve', 'digest')
        self.store.review('run', 'carol', 'approve', 'digest')
        self.store.enqueue('run', 'key', 'pr', {})
        self.store.invalidate('run', 'stale')
        with self.assertRaises(ValueError): self.store.reopen('run', 'other')
        reopened = self.store.reopen('run', 'digest')
        self.assertEqual(reopened['status'], 'PENDING')
        self.assertEqual(reopened['reviews'], {})
        self.assertIsNone(reopened['final_review'])
        self.assertEqual(reopened['outbox'][0]['status'], 'CANCELLED')
        self.assertEqual(self.store.enqueue('run', 'key', 'pr', {})['status'], 'PENDING')
        self.assertEqual(self.store.get('run')['history'][-1]['kind'], 'REQUEUED')
        self.store.claim_delivery('key')
        self.store.delivered('key', {'id': 'existing'})
        self.store.invalidate('run', 'stale again')
        self.store.reopen('run', 'digest')
        self.assertEqual(self.store.enqueue('run', 'key', 'pr', {})['status'], 'DELIVERED')
        with self.assertRaises(ValueError): self.store.claim_delivery('key')
        with self.assertRaises(ValueError): self.store.reopen('run', 'digest')


if __name__ == '__main__':
    unittest.main()
