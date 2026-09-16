import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from datamesh_release_protocol.cli import run_catalog


class OracleIsolationTest(unittest.TestCase):
    def test_unscored_run_contains_no_expected_labels(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "results.json"
            manifest = root / "manifest.json"
            run_catalog(
                scenarios_dir=Path("scenarios/development"),
                baseline_path=Path("policies/v1-ind.yaml"),
                output=output,
                manifest=manifest,
                run_id="oracle-isolation-test",
            )
            results = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(results), 80)
            for result in results:
                self.assertNotIn("expected_decision", result)
                self.assertNotIn("matches_expected", result)
            run_manifest = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(run_manifest["run_id"], "oracle-isolation-test")
            self.assertIsNone(run_manifest["oracle_sha256"])
            self.assertFalse(run_manifest["oracle_loaded_after_all_validator_runs"])


if __name__ == "__main__":
    unittest.main()
