"""Fresh deliveries must not wait behind a whole profile-upgrade backlog."""
from pathlib import Path
import tempfile
import unittest

from agent_service.queue import Limits, ServiceStore
from tests.service.clock import Clock


class FairnessTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.path = Path(tmp.name) / 'queue.sqlite'
        self.limits = Limits(job_deadline_seconds=60, lease_seconds=10)
        self.store = ServiceStore(self.path, clock=self.clock, limits=self.limits)

    def open(self, number, version='v1'):
        rid = f'github:acme/orders#{number}'
        self.store.apply_snapshot(resource_id=rid, provider='github', kind='pr', version=version,
                                  snapshot={'number': number}, event_id=f'push:{number}:{version}')
        return rid

    def finish(self, job):
        self.store.complete_job(job, state='DONE', result={}, reason=None, intent=None)

    def background(self, count=3):
        for number in range(1, count + 1):
            self.open(number)
            self.finish(self.store.claim_job('w'))
        self.store.reopen_open_resources(reason='analysis_basis_changed', event_id='analysis_basis:new',
                                         providers={'github'})

    def test_fresh_delivery_precedes_an_older_profile_backlog(self):
        self.background()
        self.clock.advance(1)
        fresh = self.open(99)
        self.assertEqual(self.store.claim_job('w')['resource_id'], fresh)

    def test_unstarted_background_job_keeps_budget_after_a_long_queue_wait(self):
        self.background(1)
        self.clock.advance(120)
        job = self.store.claim_job('w')
        self.assertIsNotNone(job)
        self.assertEqual(job['deadline'], self.clock() + 60)
        self.assertEqual(job['attempts'], 1)

    def test_fairness_survives_restart_under_continuous_fresh_work(self):
        self.background(1)
        for number in range(100, 110):
            self.open(number)
        claimed = []
        for _ in range(5):
            self.store = ServiceStore(self.path, clock=self.clock, limits=self.limits)
            job = self.store.claim_job('w')
            claimed.append(job['resource_id'])
            self.finish(job)
        self.assertNotIn('github:acme/orders#1', claimed[:4])
        self.assertEqual(claimed[4], 'github:acme/orders#1')

    def test_background_retry_does_not_reset_the_started_deadline(self):
        self.background(1)
        self.clock.advance(20)
        first = self.store.claim_job('w')
        self.clock.advance(10)
        self.store.requeue_job(first, 'source_unavailable', count_attempt=True, delay=0)
        second = self.store.claim_job('w')
        self.assertEqual(second['deadline'], first['deadline'])

    def test_expired_foreground_is_not_granted_a_new_budget(self):
        rid = self.open(99)
        self.clock.advance(120)
        self.assertIsNone(self.store.claim_job('w'))
        self.assertEqual(self.store.jobs(rid)[0]['reason'], 'deadline_exceeded')

    def test_new_version_revokes_queued_background_generation(self):
        self.background(1)
        self.open(1, 'v2')
        job = self.store.claim_job('w')
        self.assertEqual(job['resource_version'], 'v2')
        self.assertEqual([j['state'] for j in self.store.jobs(job['resource_id'])],
                         ['DONE', 'SUPERSEDED', 'RUNNING'])

    def test_legacy_background_queue_is_recognized_on_upgrade(self):
        self.background(2)
        # Old releases wrote jobs + generation history, but no scheduling metadata.
        with self.store._tx() as c:
            c.execute("DELETE FROM checkpoints WHERE name LIKE 'background_job:%' "
                      "OR name='queue_scheduling_history_seq'")
        self.store = ServiceStore(self.path, clock=self.clock, limits=self.limits)
        fresh = self.open(99)
        self.assertEqual(self.store.claim_job('w')['resource_id'], fresh)

    def test_expired_recovered_background_does_not_get_a_second_budget(self):
        self.background(1)
        self.clock.advance(20)
        first = self.store.claim_job('w')
        self.clock.advance(61)
        self.store.recover()
        self.assertIsNone(self.store.claim_job('other-worker'))
        self.assertEqual(self.store.job(first['job_id'])['reason'], 'deadline_exceeded')

    def test_external_event_id_cannot_choose_background_budget(self):
        self.store.apply_snapshot(resource_id='github:acme/orders#99', provider='github', kind='pr',
                                  version='v1', snapshot={}, event_id='analysis_basis:external')
        self.store = ServiceStore(self.path, clock=self.clock, limits=self.limits)
        self.clock.advance(120)
        self.assertIsNone(self.store.claim_job('w'))

    def test_uncounted_retry_does_not_renew_background_budget(self):
        self.background(1)
        first = self.store.claim_job('w')
        self.store.requeue_job(first, 'authentication_failed', count_attempt=False, delay=0)
        self.clock.advance(120)
        self.assertIsNone(self.store.claim_job('w'))
        self.assertEqual(self.store.job(first['job_id'])['reason'], 'deadline_exceeded')

    def test_old_writer_after_rollback_is_repaired_on_next_upgrade(self):
        self.background(1)
        # Saved queue/history written by the old release after a newer version had
        # initialized the database. Old code leaves the newer checkpoint intact,
        # but does not write per-job scheduling markers.
        with self.store._tx() as c:
            c.execute("DELETE FROM checkpoints WHERE name LIKE 'background_job:%'")
        self.clock.advance(120)
        self.store = ServiceStore(self.path, clock=self.clock, limits=self.limits)
        job = self.store.claim_job('w')
        self.assertIsNotNone(job)
        self.assertEqual(job['deadline'], self.clock() + 60)
