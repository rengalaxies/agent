"""Scoped control registry and durable, fenced execution integration."""
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from change_completion.control_plane import ControlPlane

ROOT = Path(__file__).resolve().parents[2] / 'examples/product/execution'
ADMIN = 'operator-' + 'a'*32
WORKER = 'worker-' + 'b'*32
OTHER = 'other-' + 'c'*32


class ControlPlaneTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.time = datetime(2026, 10, 17, tzinfo=timezone.utc).timestamp()
        self.plane = ControlPlane(self.base/'control/db.sqlite3', clock=lambda: self.time)
        self.plane.bootstrap(ADMIN)
        self.plane.add_scope(ADMIN, 'org', 'organization')
        self.plane.add_scope(ADMIN, 'division', 'division', 'org')
        for name in ['finance', 'sales']:
            self.plane.add_scope(ADMIN, name, 'department', 'division')
        self.plane.add_identity(ADMIN, WORKER, 'demo-worker', self.time+1000)
        self.plane.add_identity(ADMIN, OTHER, 'other', self.time+1000)
        self.plane.grant(ADMIN, 'demo-worker', 'finance', ['read', 'enqueue', 'work'], self.time+900)
        self.plane.grant(ADMIN, 'other', 'sales', ['read', 'enqueue', 'work'], self.time+900)
        shutil.copytree(ROOT, self.base/'example')
        self.binding = dict(repository=self.base/'example/repository', transition=self.base/'example/transition.json', expectations=self.base/'example/expectations.json', fixtures=self.base/'example/fixtures', trust=self.base/'example/trust.json', state=self.base/'state', worker_actor='demo-worker')
        self.plane.register(ADMIN, 'finance', 'billing', **self.binding)

    def test_cross_department_and_parent_membership_do_not_leak(self):
        with self.assertRaises(PermissionError):
            self.plane.enqueue(OTHER, 'billing', 'request')
        with self.assertRaises(PermissionError):
            self.plane.history(OTHER, 'finance')
        self.plane.grant(ADMIN, 'other', 'org', ['read', 'enqueue', 'work'], self.time+900)
        with self.assertRaises(PermissionError):
            self.plane.history(OTHER, 'finance')
        self.assertEqual(self.plane.work_once(OTHER), {'status': 'IDLE'})
        # Operator does not silently acquire per-department data access.
        with self.assertRaises(PermissionError):
            self.plane.history(ADMIN, 'finance')

    def test_real_execution_and_restart_idempotency(self):
        first = self.plane.enqueue(WORKER, 'billing', 'same-request')
        restarted = ControlPlane(self.plane.path, clock=lambda: self.time)
        self.assertEqual(restarted.enqueue(WORKER, 'billing', 'same-request'), first)
        completed = restarted.work_once(WORKER)
        self.assertEqual(completed['status'], 'READY_FOR_REVIEW', completed)
        self.assertFalse(completed['result']['effects_authorized'])
        self.assertEqual(restarted.work_once(WORKER), {'status': 'IDLE'})
        history = restarted.history(WORKER, 'finance')
        self.assertEqual(len(history['tasks']), 1)
        self.assertEqual(history['tasks'][0]['status'], 'READY_FOR_REVIEW')
        self.assertIn('TASK_FINISHED', [event['kind'] for event in history['audit']])

    def test_revocation_and_grant_expiry_take_effect_without_restart(self):
        self.plane.enqueue(WORKER, 'billing', 'pending')
        self.plane.revoke(ADMIN, 'demo-worker')
        for action in [lambda: self.plane.history(WORKER, 'finance'), lambda: self.plane.work_once(WORKER), lambda: self.plane.enqueue(WORKER, 'billing', 'another')]:
            with self.assertRaises(PermissionError):
                action()
        self.time += 901
        with self.assertRaises(PermissionError):
            self.plane.history(OTHER, 'sales')

    def test_expired_lease_is_unknown_not_automatically_retried(self):
        queued = self.plane.enqueue(WORKER, 'billing', 'crash')
        claimed = self.plane._claim(WORKER, 1)
        self.assertEqual(claimed['id'], queued['id'])
        self.time += 2
        restarted = ControlPlane(self.plane.path, clock=lambda: self.time)
        self.assertEqual(restarted.work_once(WORKER), {'status': 'IDLE'})
        self.assertEqual(restarted.history(WORKER, 'finance')['tasks'][0]['status'], 'UNKNOWN')
        self.assertEqual(restarted.enqueue(WORKER, 'billing', 'crash')['status'], 'UNKNOWN')

    def test_registration_pin_does_not_approve_modified_expectations(self):
        self.plane.enqueue(WORKER, 'billing', 'modified')
        path = self.binding['expectations']
        data = json.loads(path.read_text())
        data['cases'][0]['expected']['rows'] = [[999]]
        path.write_text(json.dumps(data))
        with patch('change_completion.control_plane.run_transition') as runtime:
            self.assertEqual(self.plane.work_once(WORKER)['status'], 'STOP')
            runtime.assert_not_called()

    def test_revocation_during_execution_redacts_completion(self):
        self.plane.enqueue(WORKER, 'billing', 'revoked')
        def interrupted(*args, **kwargs):
            self.plane.revoke(ADMIN, 'demo-worker')
            return {'status': 'READY_FOR_REVIEW', 'patches': {'secret': 'candidate'}}
        with patch('change_completion.control_plane.run_transition', side_effect=interrupted):
            result = self.plane.work_once(WORKER)
        self.assertEqual(result['status'], 'STOP')
        self.assertNotIn('patches', result['result'])

    def test_fencing_prevents_completion_after_lease_expiry(self):
        self.plane.enqueue(WORKER, 'billing', 'slow')
        def expired(*args, **kwargs):
            self.time += 2
            return {'status': 'READY_FOR_REVIEW'}
        with patch('change_completion.control_plane.run_transition', side_effect=expired):
            result = self.plane.work_once(WORKER, 1)
        self.assertEqual(result['status'], 'UNKNOWN')
        self.assertIsNone(self.plane.history(WORKER, 'finance')['tasks'][0]['result'])

    def test_no_transition_or_state_namespace_reuse_across_departments(self):
        with self.assertRaises(ValueError):
            self.plane.register(ADMIN, 'sales', 'collision', **self.binding)
        with self.assertRaises(PermissionError):
            self.plane.register(WORKER, 'finance', 'new', **self.binding)

    def test_controls_must_be_outside_candidate_repository(self):
        candidate = dict(self.binding, state=self.binding['repository']/'state')
        with self.assertRaises(ValueError):
            self.plane.register(ADMIN, 'finance', 'unsafe', **candidate)

    def test_audit_append_only_and_no_tokens_stored(self):
        with sqlite3.connect(self.plane.path) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM audit')
            stored = db.execute('SELECT token FROM identities').fetchall()
        self.assertNotIn(WORKER, str(stored))
        self.assertNotIn(ADMIN, str(stored))
        self.assertEqual(self.plane.path.stat().st_mode & 0o777, 0o600)

    def test_concurrent_workers_claim_only_once(self):
        from concurrent.futures import ThreadPoolExecutor
        self.plane.enqueue(WORKER, 'billing', 'concurrent')
        def claim(_):
            return ControlPlane(self.plane.path, clock=lambda: self.time)._claim(WORKER, 120)
        with ThreadPoolExecutor(max_workers=4) as workers:
            claims = list(workers.map(claim, range(4)))
        self.assertEqual(sum(claim is not None for claim in claims), 1)

    def test_revoked_runtime_grant_cannot_be_bypassed_by_queue_membership(self):
        data = json.loads(self.binding['trust'].read_text())
        data['revoked_grant_ids'] = ['demo-execution-grant']
        self.binding['trust'].write_text(json.dumps(data))
        self.plane.enqueue(WORKER, 'billing', 'runtime-revoked')
        result = self.plane.work_once(WORKER)
        self.assertEqual(result['status'], 'STOP')
        self.assertNotIn('patches', result['result'])

    def test_cli_has_no_secret_in_output(self):
        import os
        import subprocess
        import sys
        registry = self.base/'cli.sqlite3'
        environment = dict(os.environ, CONTROL_TEST_TOKEN=ADMIN, PYTHONPATH='src')
        command = [sys.executable, '-m', 'change_completion.control_cli', '--registry', str(registry), '--token-env', 'CONTROL_TEST_TOKEN']
        result = subprocess.run(command+['init'], env=environment, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        self.assertEqual(json.loads(result.stdout), {'status': 'OK'})
        self.assertNotIn(ADMIN, result.stdout+result.stderr)

    def test_explicit_retry_is_operator_scoped_idempotent_and_passes_runtime_attempt(self):
        queued = self.plane.enqueue(WORKER, 'billing', 'initial')
        recorded = {'status': 'FAIL', 'run_id': 'prior-run', 'context_sha256': 'a'*64, 'effects_authorized': False}
        with patch('change_completion.control_plane.run_transition', return_value=recorded):
            self.assertEqual(self.plane.work_once(WORKER)['status'], 'FAIL')
        with self.assertRaises(PermissionError):
            self.plane.retry(WORKER, queued['id'], 'retry-attempt')
        with self.assertRaises(PermissionError):
            self.plane.retry(ADMIN, queued['id'], 'retry-attempt')
        self.plane.grant(ADMIN, 'operator', 'finance', ['enqueue'], self.time+900)
        retried = self.plane.retry(ADMIN, queued['id'], 'retry-attempt')
        self.assertEqual(self.plane.retry(ADMIN, queued['id'], 'retry-attempt'), retried)
        with patch('change_completion.control_plane.run_transition', return_value={'status': 'READY_FOR_REVIEW'}) as runtime:
            self.assertEqual(self.plane.work_once(WORKER)['status'], 'READY_FOR_REVIEW')
            self.assertEqual(runtime.call_args.kwargs['retry_of'], 'prior-run')
            self.assertEqual(runtime.call_args.kwargs['retry_key'], 'retry-attempt')

    def test_unknown_attempt_cannot_be_retried_even_by_operator(self):
        queued = self.plane.enqueue(WORKER, 'billing', 'unknown')
        self.plane._claim(WORKER, 1)
        self.time += 2
        self.plane.work_once(WORKER)
        self.plane.grant(ADMIN, 'operator', 'finance', ['enqueue'], self.time+900)
        with self.assertRaises(ValueError):
            self.plane.retry(ADMIN, queued['id'], 'retry-unknown')

    def test_scope_hierarchy_cannot_skip_or_cycle(self):
        with self.assertRaises(ValueError):
            self.plane.add_scope(ADMIN, 'bad', 'department', 'org')
        with self.assertRaises(ValueError):
            self.plane.add_scope(ADMIN, 'bad', 'organization', 'finance')
        with self.assertRaises(ValueError):
            self.plane.add_scope(ADMIN, 'self', 'division', 'self')

    def test_real_contract_python_sql_profile_uses_queue_and_independent_pin(self):
        from change_completion.contract_profile import generate_candidate
        example = ROOT.parent/'contract_change'
        candidate = self.base/'contract-candidate'
        generate_candidate(example/'baseline', candidate, json.loads((example/'changes.json').read_text()))
        suite = self.base/'contract-suite.json'
        shutil.copyfile(example/'approval/suite.json', suite)
        approved = (example/'approval/suite.sha256').read_text().strip()
        contract = dict(repository=candidate, expectations=suite, state=self.base/'contract-state', worker_actor='demo-worker', profile='contract-python-sql/1')
        with self.assertRaises(ValueError):
            self.plane.register(ADMIN, 'finance', 'contract-no-approval', **contract)
        self.plane.register(ADMIN, 'finance', 'contract', approved_suite_sha256=approved, **contract)
        self.plane.enqueue(WORKER, 'contract', 'contract-case')
        result = self.plane.work_once(WORKER)
        self.assertEqual(result['status'], 'READY_FOR_REVIEW', result)
        self.assertEqual(result['result']['verification_status'], 'PASS')
        self.assertEqual(result['result']['profile'], 'contract-python-sql/1')
        self.assertFalse(result['result']['effects_authorized'])
        self.assertTrue(result['result']['artifacts'])


class WorkerLoopTests(unittest.TestCase):
    def test_idle_polling_stops_on_time_without_real_sleep(self):
        from change_completion.control_plane import run_worker_loop
        time = [0.0]
        calls = []
        class Idle:
            def work_once(self, token):
                calls.append(token)
                return {'status': 'IDLE'}
        def advance(seconds):
            time[0] += seconds
        result = run_worker_loop(Idle(), 'opaque', max_seconds=3, poll_seconds=1,
                                 monotonic=lambda: time[0], sleep=advance)
        self.assertEqual(result['reason'], 'time_budget')
        self.assertEqual(len(calls), 3)
        self.assertEqual(result['processed'], [])

    def test_job_budget_and_unknown_do_not_retry_automatically(self):
        from change_completion.control_plane import run_worker_loop
        queued = iter([{'id': 'a', 'status': 'UNKNOWN'}, {'id': 'b', 'status': 'READY_FOR_REVIEW'}])
        class Worker:
            def work_once(self, token):
                return next(queued)
        result = run_worker_loop(Worker(), 'opaque', max_jobs=2)
        self.assertEqual(result['reason'], 'job_budget')
        self.assertEqual([item['id'] for item in result['processed']], ['a', 'b'])

    def test_permission_failure_propagates_without_polling(self):
        from change_completion.control_plane import run_worker_loop
        class Revoked:
            def work_once(self, token):
                raise PermissionError('revoked')
        with self.assertRaises(PermissionError):
            run_worker_loop(Revoked(), 'opaque', sleep=lambda _: self.fail('must not sleep'))

    def test_worker_budget_validation(self):
        from change_completion.control_plane import run_worker_loop
        for arguments in [{'max_jobs': 1001}, {'max_seconds': 3601}, {'max_seconds': float('nan')}, {'poll_seconds': 0}, {'max_jobs': True}]:
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                run_worker_loop(None, 'opaque', **arguments)


class RestoreAuthorityTests(unittest.TestCase):
    def test_recovery_requires_marker_attestation_and_fresh_identity(self):
        with TemporaryDirectory() as directory:
            plane = ControlPlane(Path(directory)/'control.sqlite3')
            plane.bootstrap(ADMIN)
            with self.assertRaises(PermissionError):
                plane.recover_restored('z'*40, 'fresh')
            with self.assertRaises(ValueError):
                plane.recover_restored('z'*40, 'fresh', confirmed_authority=True)
            with sqlite3.connect(plane.path) as db:
                db.execute('CREATE TABLE restore_quarantine(singleton INTEGER PRIMARY KEY, acknowledged INTEGER NOT NULL)')
                db.execute('INSERT INTO restore_quarantine VALUES (1,0)')
                db.execute('UPDATE identities SET revoked=1')
            with self.assertRaises(ValueError):
                plane.recover_restored(ADMIN, 'fresh', confirmed_authority=True)
            with self.assertRaises(ValueError):
                plane.recover_restored('z'*40, 'operator', confirmed_authority=True)
            plane.recover_restored('z'*40, 'fresh', confirmed_authority=True)
            with self.assertRaises(PermissionError):
                plane.add_scope(ADMIN, 'old', 'organization')
            plane.add_scope('z'*40, 'new', 'organization')
            with self.assertRaises(ValueError):
                plane.recover_restored('q'*40, 'second', confirmed_authority=True)
            with self.assertRaises(PermissionError):
                plane.history('z'*40, 'new')
            plane.grant('z'*40, 'fresh', 'new', ['read'], plane.clock()+100)
            self.assertEqual(plane.history('z'*40, 'new')['scope'], 'new')

    def test_actual_snapshot_restore_does_not_resurrect_old_authority(self):
        from change_completion.state_transfer import snapshot, restore
        with TemporaryDirectory() as directory:
            root = Path(directory)
            original = ControlPlane(root/'state/control.sqlite3')
            original.bootstrap(ADMIN)
            original.add_scope(ADMIN, 'org', 'organization')
            original.grant(ADMIN, 'operator', 'org', ['read'], original.clock()+1000)
            snapshot(root/'state', root/'backup', quiesced=True)
            restore(root/'backup', root/'restored')
            restored = ControlPlane(root/'restored/control.sqlite3')
            with self.assertRaises(PermissionError):
                restored.history(ADMIN, 'org')
            with self.assertRaises(PermissionError):
                restored.recover_restored('r'*40, 'restored-operator')
            restored.recover_restored('r'*40, 'restored-operator', confirmed_authority=True)
            with self.assertRaises(PermissionError):
                restored.history('r'*40, 'org')
            restored.grant('r'*40, 'restored-operator', 'org', ['read'], restored.clock()+1000)
            self.assertEqual(restored.history('r'*40, 'org')['scope'], 'org')


class RebindTests(unittest.TestCase):
    setUp = ControlPlaneTests.setUp

    def test_rebinding_preserves_pins_and_requires_fresh_scope_and_review(self):
        self.plane.add_identity(ADMIN, 'n'*40, 'new-worker', self.time+1000)
        with self.assertRaises(PermissionError):
            self.plane.rebind_worker(ADMIN, 'billing', 'new-worker')
        with self.assertRaises(PermissionError):
            self.plane.rebind_worker(ADMIN, 'billing', 'new-worker', confirmed_binding_review=True)
        self.plane.grant(ADMIN, 'new-worker', 'finance', ['work'], self.time+900)
        with sqlite3.connect(self.plane.path) as db:
            before = json.loads(db.execute('SELECT config FROM bindings WHERE id=?', ('billing',)).fetchone()[0])
        self.plane.rebind_worker(ADMIN, 'billing', 'new-worker', confirmed_binding_review=True)
        with sqlite3.connect(self.plane.path) as db:
            after = json.loads(db.execute('SELECT config FROM bindings WHERE id=?', ('billing',)).fetchone()[0])
        self.assertEqual(after, dict(before, worker_actor='new-worker'))
        # Registry membership never creates independent runtime grants.
        self.plane.enqueue(WORKER, 'billing', 'new-worker-task')
        result = self.plane.work_once('n'*40)
        self.assertEqual(result['status'], 'STOP')
        self.assertIn('discovery_authority_unavailable', result['result']['reason_codes'])

    def test_rebinding_rejects_inflight_task(self):
        self.plane.enqueue(WORKER, 'billing', 'running-task')
        self.plane._claim(WORKER, 120)
        with self.assertRaises(ValueError):
            self.plane.rebind_worker(ADMIN, 'billing', 'demo-worker', confirmed_binding_review=True)



class ContractIntentQueueTests(unittest.TestCase):
    setUp = ControlPlaneTests.setUp

    def test_worker_generates_candidate_from_pinned_intent_and_checks_independently(self):
        from change_completion.verification import digest_bytes
        example = ROOT.parent/'contract_change'
        baseline = self.base/'contract-baseline'
        shutil.copytree(example/'baseline', baseline)
        intent = self.base/'approved-changes.json'
        suite = self.base/'independent-suite.json'
        shutil.copyfile(example/'changes.json', intent)
        shutil.copyfile(example/'approval/suite.json', suite)
        approved = (example/'approval/suite.sha256').read_text().strip()
        config = dict(repository=baseline, expectations=suite, state=self.base/'intent-state', worker_actor='demo-worker', profile='contract-python-sql/1', approved_suite_sha256=approved, changes_path=intent)
        self.plane.register(ADMIN, 'finance', 'intent-contract', **config)
        original = {str(p.relative_to(baseline)): digest_bytes(p.read_bytes()) for p in baseline.rglob('*') if p.is_file()}
        self.plane.enqueue(WORKER, 'intent-contract', 'generate-and-check')
        result = self.plane.work_once(WORKER)
        self.assertEqual(result['status'], 'READY_FOR_REVIEW', result)
        self.assertEqual(result['result']['verification_status'], 'PASS')
        candidate = Path(result['result']['candidate_path'])
        self.assertTrue(candidate.is_dir())
        self.assertNotEqual(candidate, baseline)
        self.assertEqual(original, {str(p.relative_to(baseline)): digest_bytes(p.read_bytes()) for p in baseline.rglob('*') if p.is_file()})
        self.assertEqual(result['result']['intent_sha256'], digest_bytes(intent.read_bytes()))
        self.assertEqual(self.plane.work_once(WORKER), {'status': 'IDLE'})
        intent.write_text('{}')
        self.plane.enqueue(WORKER, 'intent-contract', 'tampered-intent')
        self.assertEqual(self.plane.work_once(WORKER)['status'], 'STOP')
