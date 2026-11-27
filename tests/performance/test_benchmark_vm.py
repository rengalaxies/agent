"""Remote benchmark exporter sends instrumentation in, numeric artifacts out."""
from contextlib import redirect_stdout
import ast
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from experiments.impactmap_scale import run_pilot_vm_benchmark as vm


class VMRunnerTests(unittest.TestCase):
    def test_frozen_pins_are_forwarded_to_remote_instead_of_following_live_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pins = dict(schema_version='impactmap-pilot-pins-1', provider_repository='bb.orders', pr_id=4,
                        base_revisions={'bb.orders': 'a' * 40}, head_revisions={'bb.orders': 'b' * 40})
            source = root / 'pins.json'
            source.write_text(json.dumps(pins))
            response = SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(dict(
                measured=dict(spans=[], samples=[]), semantics_equal=True, pins=[])))
            with patch.object(vm.subprocess, 'run', return_value=response) as run, redirect_stdout(io.StringIO()):
                result = vm.main(['--ssh-config', '/synthetic/config', '--pins-from', str(source),
                                  '--output', str(root / 'out'), '--repeats', '1'])
            self.assertEqual(result, 0)
            payload = ast.parse(run.call_args.kwargs['input'])
            assigned = next(n.value for n in payload.body if isinstance(n, ast.Assign)
                            and any(isinstance(t, ast.Name) and t.id == 'PIN_OVERRIDE' for t in n.targets))
            self.assertEqual(ast.literal_eval(assigned), pins)

    def test_failed_remote_attempts_preserve_rows_without_stderr_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'reports'
            stdout = io.StringIO()
            with patch.object(vm.subprocess, 'run', return_value=SimpleNamespace(
                    returncode=1, stdout='', stderr='SECRET_DO_NOT_EXPORT')) as run, redirect_stdout(stdout):
                result = vm.main(['--ssh-config', '/synthetic/config', '--output', str(out), '--repeats', '2'])
            self.assertEqual(result, 1)
            rows = [json.loads(x) for x in (out / 'measurements.jsonl').read_text().splitlines()]
            self.assertEqual(len(rows), 2)
            self.assertTrue(all(r['error_code'] == 'remote_benchmark_failed' for r in rows))
            self.assertNotIn('SECRET_DO_NOT_EXPORT', stdout.getvalue() + (out / 'measurements.jsonl').read_text())
            self.assertIn('exec(compile(', run.call_args.kwargs['input'])
            self.assertEqual(run.call_args.args[0][0], 'ssh')

    def test_changing_pins_cannot_silently_form_one_series(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / 'reports'
            def response(pin):
                return SimpleNamespace(returncode=0, stderr='', stdout=json.dumps(dict(
                    measured=dict(spans=[], samples=[]), semantics_equal=True, pins=[dict(head=pin)])))
            with patch.object(vm.subprocess, 'run', side_effect=[response('a'), response('b')]), redirect_stdout(io.StringIO()):
                result = vm.main(['--ssh-config', '/synthetic/config', '--output', str(out), '--repeats', '2'])
            self.assertEqual(result, 1)
            rows = [json.loads(x) for x in (out / 'measurements.jsonl').read_text().splitlines()]
            self.assertEqual(rows[1]['error_code'], 'input_pins_changed')


if __name__ == '__main__':
    unittest.main()
