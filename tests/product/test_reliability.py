import unittest
from unittest.mock import patch
from change_completion.bounded_verification import bounded_verify
from change_completion.models import ContentRef
from tests.product import test_runtime as fixture

class ReliabilityTest(unittest.TestCase):
    def setUp(self):
        self.lab = fixture.RuntimeTest(); self.lab.setUp(); self.addCleanup(self.lab.doCleanups)

    def test_operator_retry_is_distinct_idempotent_and_retains_history(self):
        # Provider failure is transient; its immutable attempt remains inspectable.
        class Provider:
            identity = "transient/1"
            broken = True
            def propose(inner, source, **kwargs):
                if inner.broken: raise RuntimeError("temporary")
                from change_completion.providers import WindowPatchProvider
                return WindowPatchProvider().propose(source, **kwargs)
        p = Provider()
        failed = self.lab.run_case(provider=p)
        self.assertEqual(failed['status'], 'STOP')
        p.broken = False
        self.assertEqual(self.lab.run_case(provider=p)['run_id'], failed['run_id'])
        recovered = self.lab.run_case(provider=p, retry_of=failed['run_id'], retry_key='manual-attempt-1')
        self.assertEqual(recovered['status'], 'READY_FOR_REVIEW', recovered)
        self.assertNotEqual(recovered['run_id'], failed['run_id'])
        self.assertEqual(self.lab.store.get(failed['run_id'])['status'], 'STOP')
        self.assertEqual(self.lab.run_case(provider=p, retry_of=failed['run_id'], retry_key='manual-attempt-1')['run_id'], recovered['run_id'])

    def test_success_cannot_be_retried_as_failure(self):
        run = self.lab.run_case()
        retry = self.lab.run_case(retry_of=run['run_id'], retry_key='manual-attempt-1')
        self.assertEqual(retry['status'], 'STOP')
        self.assertIn('retry_requires_terminal_failure', retry['reason_codes'])

    def test_verifier_deadline_stops_without_accepting(self):
        candidate = ContentRef(uri='test', sha256='0'*64)
        report = bounded_verify(self.lab.spec, candidate, self.lab.suite, b'{}', self.lab.policy,
                                at=fixture.NOW, actor='demo-worker', timeout_seconds=.000001)
        self.assertEqual(report.status, 'STOP')
        self.assertIn('VERIFIER_WALL_TIME_LIMIT', report.reason_codes)

    def test_interrupted_reconciliation_requires_stopped_worker(self):
        store = self.lab.store
        run = store.claim('test-transition','fingerprint')['run_id']
        store.append(run, 'CONTEXT', {'context_sha256':'0'*64})
        with self.assertRaises(ValueError): store.reconcile_interrupted(run, actor='operator', reason='checked')
        result = store.reconcile_interrupted(run, actor='operator', reason='process confirmed dead', worker_stopped=True)
        self.assertEqual(result['status'],'STOP')
        self.assertEqual(store.get(run)['events'][-2]['kind'],'OPERATOR_RECONCILED')
