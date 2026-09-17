import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from datamesh_release_protocol.cli import run_catalog, score_results


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
                purpose="development_regression",
            )
            results = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(results), 80)
            for result in results:
                self.assertNotIn("expected_decision", result)
                self.assertNotIn("matches_expected", result)
            run_manifest = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(run_manifest["run_id"], "oracle-isolation-test")
            self.assertEqual(run_manifest["status"], "validators_completed_unscored")
            self.assertIsNone(run_manifest["oracle_sha256"])
            self.assertFalse(run_manifest["oracle_loaded_by_validator_process"])
            self.assertEqual(
                run_manifest["raw_results_sha256"],
                hashlib.sha256(output.read_bytes()).hexdigest(),
            )

    def test_scoring_preserves_raw_results_and_links_manifests(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.json"
            run_manifest = root / "run-manifest.json"
            scored = root / "scored.json"
            metrics = root / "metrics.json"
            score_manifest = root / "score-manifest.json"
            run_catalog(
                scenarios_dir=Path("scenarios/development"),
                baseline_path=Path("policies/v1-ind.yaml"),
                output=raw,
                manifest=run_manifest,
                run_id="two-stage-test",
                purpose="development_regression",
            )
            raw_before = raw.read_bytes()
            score_results(
                raw_results_path=raw,
                run_manifest_path=run_manifest,
                scenarios_dir=Path("scenarios/development"),
                catalog_manifest_path=Path("experiments/development-catalog.yaml"),
                analysis_plan_path=Path("experiments/analysis-plan-0.3.1.yaml"),
                oracle_path=Path("oracles/development.yaml"),
                output=scored,
                metrics_path=metrics,
                score_manifest_path=score_manifest,
            )
            self.assertEqual(raw.read_bytes(), raw_before)
            self.assertTrue(
                all("expected_decision" not in item for item in json.loads(raw_before))
            )
            self.assertTrue(
                all("expected_decision" in item for item in json.loads(scored.read_text()))
            )
            score_payload = json.loads(score_manifest.read_text(encoding="utf-8"))
            self.assertEqual(
                score_payload["raw_results_sha256"],
                hashlib.sha256(raw_before).hexdigest(),
            )
            self.assertTrue(score_payload["oracle_loaded_by_scoring_process_only"])
            self.assertFalse(score_payload["expected_labels_exposed_to_validators"])
            self.assertIn("catalog_manifest_sha256", score_payload)
            self.assertIn("analysis_plan_sha256", score_payload)
            self.assertEqual(
                json.loads(metrics.read_text(encoding="utf-8"))["purpose"],
                "development_regression",
            )

    def test_scoring_rejects_tampered_raw_results(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            raw = root / "raw.json"
            run_manifest = root / "run-manifest.json"
            run_catalog(
                scenarios_dir=Path("scenarios/development"),
                baseline_path=Path("policies/v1-ind.yaml"),
                output=raw,
                manifest=run_manifest,
                run_id="tamper-test",
                purpose="development_regression",
            )
            raw.write_text(raw.read_text(encoding="utf-8") + " ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "raw results hash"):
                score_results(
                    raw_results_path=raw,
                    run_manifest_path=run_manifest,
                    scenarios_dir=Path("scenarios/development"),
                    catalog_manifest_path=Path("experiments/development-catalog.yaml"),
                    analysis_plan_path=Path("experiments/analysis-plan-0.3.1.yaml"),
                    oracle_path=Path("oracles/development.yaml"),
                    output=root / "scored.json",
                    metrics_path=root / "metrics.json",
                    score_manifest_path=root / "score-manifest.json",
                )


if __name__ == "__main__":
    unittest.main()
