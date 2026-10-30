from pathlib import Path
import tempfile
import unittest
from tests.graph.pilot_review import review

class PilotReviewTest(unittest.TestCase):
    def test_method_port_prefix_and_lifecycle_with_separate_expectations(self):
        with tempfile.TemporaryDirectory() as directory:
            report = review(Path(directory))
        self.assertEqual(report["status"], "PASS")
        self.assertTrue(all(not f["test_executed"] for f in report["findings"]))
