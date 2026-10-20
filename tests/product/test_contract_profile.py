import contextlib
import io
from hashlib import sha256
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from change_completion.contract_profile import check_profile, generate_candidate, render_consumer
from change_completion.contract_cli import main
from change_completion.comparison import Comparison
from unittest.mock import patch

EXAMPLE = Path(__file__).resolve().parents[2] / "examples/product/contract_change"


class ContractProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.base = self.root / "baseline"
        shutil.copytree(EXAMPLE / "baseline", self.base)
        self.suite = (EXAMPLE / "approval/suite.json").read_bytes()
        self.digest = sha256(self.suite).hexdigest()
        self.changes = json.loads((EXAMPLE / "changes.json").read_bytes())

    def candidate(self, changes=None):
        candidate = self.root / "candidate"
        generate_candidate(self.base, candidate, self.changes if changes is None else changes)
        return candidate

    def check(self, candidate):
        return check_profile(candidate, self.suite, self.digest)

    def test_real_transform_passes_different_consumer_requirements(self):
        candidate = self.candidate()
        result = self.check(candidate)
        self.assertEqual(result["status"], "PASS", result)
        self.assertEqual(len(result["checks"]), 4)
        self.assertEqual((candidate / 'audit.py').read_bytes(), (self.base / 'audit.py').read_bytes())
        self.assertNotEqual((candidate / 'finance.py').read_bytes(), (self.base / 'finance.py').read_bytes())
        self.assertFalse(result['effects_authorized'])

    def test_baseline_does_not_meet_new_finance_requirement(self):
        result = self.check(self.base)
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(any(c['consumer'] == 'finance' and c['status'] == 'FAIL' for c in result['checks']))

    def test_blanket_adaptation_breaks_unchanged_audit(self):
        changes = json.loads((EXAMPLE / 'negative-changes.json').read_bytes())
        result = self.check(self.candidate(changes))
        self.assertEqual(result['status'], 'FAIL')
        self.assertTrue(any(c['consumer'] == 'audit' and c['status'] == 'FAIL' for c in result['checks']))

    def test_candidate_cannot_replace_pinned_suite(self):
        candidate = self.candidate()
        self.assertEqual(check_profile(candidate, self.suite + b' ', self.digest)['status'], 'STOP')

    def test_arbitrary_python_is_never_executed(self):
        candidate = self.candidate()
        marker = self.root / 'executed'
        (candidate / 'finance.py').write_text(f'from pathlib import Path\nPath({str(marker)!r}).touch()\n')
        self.assertEqual(self.check(candidate)['status'], 'STOP')
        self.assertFalse(marker.exists())

    def test_float_input_and_overflow_fail_closed(self):
        candidate = self.candidate()
        for value in (1.0, 2**63 - 1, True):
            suite = json.loads(self.suite)
            suite['cases'][0]['input'][0]['amount'] = value
            raw = json.dumps(suite).encode()
            self.assertEqual(check_profile(candidate, raw, sha256(raw).hexdigest())['status'], 'STOP')

    def test_sql_cannot_write_or_read_host_file(self):
        candidate = self.candidate()
        for sql in ('DELETE FROM events', "SELECT readfile('/etc/passwd') AS secret"):
            (candidate / 'finance.sql').write_text(sql)
            self.assertEqual(self.check(candidate)['status'], 'STOP')

    def test_missing_consumer_expectation_and_duplicate_cases_stop(self):
        candidate = self.candidate()
        for variant in ('missing', 'duplicate'):
            suite = json.loads(self.suite)
            if variant == 'missing':
                del suite['cases'][0]['expected']['audit']
            else:
                suite['cases'][1]['id'] = suite['cases'][0]['id']
            raw = json.dumps(suite).encode()
            self.assertEqual(check_profile(candidate, raw, sha256(raw).hexdigest())['status'], 'STOP')

    def test_symlink_consumer_and_traversal_rejected(self):
        candidate = self.candidate()
        (candidate / 'finance.py').unlink()
        (candidate / 'finance.py').symlink_to(self.base / 'finance.py')
        self.assertEqual(self.check(candidate)['status'], 'STOP')
        manifest=json.loads((candidate/'profile.json').read_text())
        manifest['consumers'][0]['python']='../baseline/finance.py'
        (candidate/'profile.json').write_text(json.dumps(manifest))
        self.assertEqual(self.check(candidate)['status'], 'STOP')

    def test_generation_does_not_overwrite_source_or_existing_output(self):
        before = (self.base/'finance.py').read_bytes()
        with self.assertRaises((ValueError, FileExistsError)):
            generate_candidate(self.base, self.base, self.changes)
        candidate = self.candidate()
        with self.assertRaises(FileExistsError):
            generate_candidate(self.base, candidate, self.changes)
        self.assertEqual((self.base/'finance.py').read_bytes(), before)


    def test_cli_generate_check_and_independent_pin_exit_codes(self):
        candidate = self.root / "cli-candidate"
        changes = self.root / "changes.json"
        suite = self.root / "suite.json"
        changes.write_text(json.dumps(self.changes))
        suite.write_bytes(self.suite)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(main(["generate", "--source", str(self.base), "--output", str(candidate),
                                   "--changes", str(changes)]), 0)
            common = ["check", "--repository", str(candidate), "--suite", str(suite),
                      "--approved-suite-sha256"]
            self.assertEqual(main(common + [self.digest]), 0)
            self.assertEqual(main(common + ["0" * 64]), 1)

    def test_comparator_stop_stays_stop(self):
        candidate = self.candidate()
        with patch("change_completion.contract_profile.compare_tables", return_value=Comparison("STOP", ("COMPARISON_WORK_LIMIT",))):
            self.assertEqual(self.check(candidate)["status"], "STOP")

    def test_aggregate_capture_limit(self):
        candidate = self.candidate()
        manifest = json.loads((candidate / "profile.json").read_text())
        # 32 cases x 3 consumers exceeds the explicit 64-capture ceiling.
        extra = {"id": "third", "python": "third.py", "sql": "third.sql"}
        manifest["consumers"].append(extra)
        (candidate / "profile.json").write_text(json.dumps(manifest))
        suite = json.loads(self.suite)
        suite["cases"] = [dict(suite["cases"][0], id=str(i)) for i in range(32)]
        raw = json.dumps(suite).encode()
        result = check_profile(candidate, raw, sha256(raw).hexdigest())
        self.assertEqual(result["reason_codes"], ["capture_budget_limit"])

    def test_manifest_contract_snapshot_change_is_not_accepted(self):
        candidate = self.candidate()
        from change_completion import contract_profile as module
        original = module._read
        seen = [False]
        def change_after_read(root, path):
            data = original(root, path)
            if path == "contract.json" and not seen[0]:
                seen[0] = True
                (root / path).write_bytes(data + b" ")
            return data
        with patch.object(module, "_read", side_effect=change_after_read):
            result = self.check(candidate)
        self.assertEqual(result["status"], "STOP")
        self.assertEqual(result["reason_codes"], ["snapshot_changed"])

    def test_output_parent_symlink_and_source_subdirectory_rejected(self):
        link = self.root / "linked"
        link.symlink_to(self.root, target_is_directory=True)
        for output in (link / "candidate", self.base / "nested"):
            with self.assertRaises(ValueError):
                generate_candidate(self.base, output, self.changes)

if __name__ == '__main__':
    unittest.main()
