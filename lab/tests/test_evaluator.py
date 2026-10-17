import tempfile
import unittest
from pathlib import Path
from lab.evaluator.verify import candidate_digest, frozen_expectations, verify

class EvaluatorUnitTests(unittest.TestCase):
    def test_frozen_source_matrix_has_exact_19_ids(self):
        self.assertEqual(set(frozen_expectations()['cases']), {f'T{i:02}' for i in range(1,20)})

    def test_digest_binds_file_content(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'patch.sql'; p.write_text('SELECT 1;')
            before = candidate_digest(d); p.write_text('SELECT 2;')
            self.assertNotEqual(before, candidate_digest(d))

    def test_rejects_evaluator_tampering_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'lab/evaluator';p.mkdir(parents=True)
            (p/'expectations.json').write_text('{}')
            result = verify(d)
            self.assertEqual(result['outcome'], 'FAIL')
            self.assertEqual(result['checks'][0]['id'], 'T04')

    def test_no_live_execution_never_passes(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'candidate.json').write_text('{}')
            self.assertNotEqual(verify(d)['outcome'], 'PASS')

    def test_symlink_candidate_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d)/'link').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):candidate_digest(d)
