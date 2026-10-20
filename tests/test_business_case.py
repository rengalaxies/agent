import json
import io
from contextlib import redirect_stdout
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from datamesh_release_protocol.business_case import build_business_case_report
from datamesh_release_protocol.cli import run_catalog, score_results
from datamesh_release_protocol.loaders import load_business_case_model
from datamesh_release_protocol.models import Decision, ScenarioRunResult, ValidationMode


class BusinessCaseTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Exercise the current development pipeline without rewriting historical
        # result files or loading retired validator modes into the live schema.
        temporary = TemporaryDirectory()
        cls.addClassCleanup(temporary.cleanup)
        root = Path(temporary.name)
        raw, manifest = root / "raw.json", root / "run-manifest.json"
        scored, metrics = root / "scored.json", root / "metrics.json"
        with redirect_stdout(io.StringIO()):
            run_catalog(
                scenarios_dir=Path("scenarios/development"),
                baseline_path=Path("policies/v1-ind.yaml"),
                output=raw,
                manifest=manifest,
                run_id="business-case-regression",
                purpose="development_regression",
            )
            score_results(
                raw_results_path=raw,
                run_manifest_path=manifest,
                scenarios_dir=Path("scenarios/development"),
                catalog_manifest_path=Path("experiments/development-catalog.yaml"),
                analysis_plan_path=Path("experiments/analysis-plan-0.3.1.yaml"),
                oracle_path=Path("oracles/development.yaml"),
                output=scored,
                metrics_path=metrics,
                score_manifest_path=root / "score-manifest.json",
            )
        cls.results = [
            ScenarioRunResult.model_validate(item)
            for item in json.loads(
                scored.read_text(encoding="utf-8")
            )
        ]
        cls.metrics = json.loads(
            metrics.read_text(encoding="utf-8")
        )
        cls.model = load_business_case_model(Path("business/economic-model.yaml"))

    def test_development_report_preserves_claim_boundary(self):
        report = build_business_case_report(
            self.results, self.metrics, self.model
        )
        self.assertEqual(report["experiment_purpose"], "development_regression")
        self.assertEqual(report["claim_scope"], "scenario_analysis_only")
        self.assertFalse(report["realized_roi_supported"])
        self.assertIn("not an E3 result", report["warning"])

    def test_false_blocks_are_split_without_double_counting(self):
        report = build_business_case_report(
            self.results, self.metrics, self.model
        )
        v1 = report["observed_rates_by_mode"]["V1-ind"]
        self.assertEqual(v1["false_block_rate"], 0.1)
        self.assertEqual(v1["admissible_reject_rate"], 0.1)
        self.assertEqual(v1["admissible_review_rate"], 0.0)
        self.assertEqual(v1["needs_review_rate"], 0.0)

    def test_sensitivity_scenarios_include_unfavorable_and_favorable_cases(self):
        report = build_business_case_report(
            self.results, self.metrics, self.model
        )
        scenarios = {item["scenario_id"]: item for item in report["scenarios"]}
        self.assertLess(scenarios["low"]["comparison"]["v2_savings_reu"], 0)
        self.assertGreater(scenarios["base"]["comparison"]["v2_savings_reu"], 0)
        self.assertGreater(scenarios["high"]["comparison"]["v2_savings_reu"], 0)
        self.assertEqual(
            scenarios["low"]["break_even"]["status"], "finite_threshold"
        )
        self.assertGreater(scenarios["low"]["break_even"]["incident_cost_reu"], 5)

    def test_metrics_and_scored_results_must_match(self):
        tampered = json.loads(json.dumps(self.metrics))
        tampered["by_mode"]["V2"]["unsafe_accept_rate"] = 0.5
        with self.assertRaisesRegex(ValueError, "differs"):
            build_business_case_report(self.results, tampered, self.model)

    def test_admissible_review_is_not_also_costed_as_false_reject(self):
        changed = []
        replaced = False
        for result in self.results:
            if (
                not replaced
                and result.mode == ValidationMode.V2
                and result.expected_decision == Decision.ACCEPT
            ):
                changed.append(
                    result.model_copy(
                        update={
                            "actual_decision": Decision.NEEDS_REVIEW,
                            "matches_expected": False,
                        }
                    )
                )
                replaced = True
            else:
                changed.append(result)
        metrics = json.loads(json.dumps(self.metrics))
        metrics["by_mode"]["V2"]["false_block_rate"] = 0.1
        metrics["by_mode"]["V2"]["needs_review_rate"] = 0.05

        report = build_business_case_report(changed, metrics, self.model)
        low_v2 = report["scenarios"][0]["by_mode"]["V2"]
        self.assertEqual(low_v2["expected_false_rejections"], 0.0)
        self.assertEqual(low_v2["false_reject_cost_reu"], 0.0)
        self.assertEqual(low_v2["expected_manual_reviews"], 9.9)
        self.assertEqual(low_v2["manual_review_cost_reu"], 9.9)


if __name__ == "__main__":
    unittest.main()
