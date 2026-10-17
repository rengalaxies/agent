import tempfile
import unittest
from pathlib import Path
from lab.evaluator.qualify_boundaries import qualify

class QualificationTests(unittest.TestCase):
    def test_independent_control_world(self):
        with tempfile.TemporaryDirectory() as tmp:
            report=qualify(Path(__file__).resolve().parents[2],Path(tmp)/'r6-r8.json')
        self.assertEqual(report['outcome'],'PASS')
        self.assertEqual(report['checks']['R7_known_world_unknowns']['evidence']['full_control_world']['recall'],0.5)
