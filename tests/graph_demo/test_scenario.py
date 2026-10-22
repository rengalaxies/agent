from pathlib import Path
import tempfile
import unittest

from examples.agent_graph_demo.oracle import check_ids
from examples.agent_graph_demo.scenarios import build_version, sources


class ScenarioTests(unittest.TestCase):
    def test_oracle_checks_exact_set_not_count(self):
        self.assertTrue(check_ids(list(range(1, 251)))["passed"])
        self.assertEqual(
            check_ids(list(range(1, 101)))["missing_ids"], list(range(101, 251))
        )
        self.assertFalse(check_ids([1] * 250)["passed"])
        self.assertFalse(check_ids(list(range(2, 252)))["passed"])
        for bad in ([True] * 250, ["1"], {"count": 250}):
            with self.assertRaises(ValueError):
                check_ids(bad)

    def test_controlled_diffs_and_export_preauthorized_empty(self):
        a, b, d, e = [sources(v) for v in "ABDE"]
        self.assertEqual(set(a), set(e))
        self.assertEqual([k for k in a if a[k] != b[k]], ["orders/app.py"])
        self.assertEqual([k for k in b if b[k] != d[k]], ["reporting/client.py"])
        self.assertEqual([k for k in d if d[k] != e[k]], ["export/client.py"])
        self.assertNotIn("requests.", a["export/client.py"])
        self.assertIn("http://status:8000/orders", a["health/client.py"])
        with tempfile.TemporaryDirectory() as td:
            build_version(Path(td), "A")
            build_version(Path(td), "E")
            self.assertEqual(
                (Path(td) / "export/client.py").read_text(), e["export/client.py"]
            )
