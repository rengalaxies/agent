from pathlib import Path
import unittest

from datamesh_release_protocol.engine import ReleaseEngine
from datamesh_release_protocol.loaders import (
    load_analysis_plan,
    load_baseline_policy,
    load_catalog,
    load_cluster_map,
    load_oracle_catalog,
)
from datamesh_release_protocol.metrics import build_metrics_report
from datamesh_release_protocol.models import ScenarioRunResult, ValidationMode


class FrozenMetricsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        scenarios = load_catalog(Path("scenarios/development"))
        cls.cluster_ids = load_cluster_map(
            Path("experiments/development-catalog.yaml"), scenarios
        )
        cls.analysis_plan = load_analysis_plan(
            Path("experiments/analysis-plan-0.3.1.yaml")
        )
        cls.oracles = load_oracle_catalog(Path("oracles/development.yaml"))
        engine = ReleaseEngine(load_baseline_policy(Path("policies/v1-ind.yaml")))
        cls.results = []
        for scenario in scenarios:
            for mode in ValidationMode:
                release = engine.run(scenario, mode, run_id="metrics")
                cls.results.append(
                    ScenarioRunResult(
                        scenario_id=scenario.scenario_id,
                        mode=mode,
                        actual_decision=release.decision,
                        duration_ms=1.0,
                        release=release,
                    )
                )

    def test_development_regression_values(self):
        report = build_metrics_report(
            self.results, self.oracles, self.cluster_ids, self.analysis_plan
        )["by_mode"]
        self.assertEqual(report["V0"]["exact_decision_accuracy"], 0.5)
        self.assertEqual(report["V0"]["unsafe_accept_rate"], 1.0)
        self.assertEqual(report["V1-ind"]["exact_decision_accuracy"], 0.8)
        self.assertEqual(report["V1-ind"]["dangerous_safe_detection_rate"], 0.7)
        self.assertEqual(report["V1-ind"]["false_block_rate"], 0.1)
        self.assertEqual(report["V2"]["exact_decision_accuracy"], 1.0)
        self.assertEqual(report["V2"]["unsafe_accept_rate"], 0.0)
        self.assertEqual(report["V2"]["false_block_rate"], 0.0)

    def test_needs_review_is_measured_separately(self):
        report = build_metrics_report(
            self.results, self.oracles, self.cluster_ids, self.analysis_plan
        )["by_mode"]
        for mode_report in report.values():
            self.assertIn("needs_review_rate", mode_report)
            self.assertIn("confidence_intervals_95", mode_report)
        v2_detection_ci = report["V2"]["confidence_intervals_95"][
            "dangerous_safe_detection_rate"
        ]
        self.assertEqual(v2_detection_ci["method"], "wilson_score")
        self.assertLess(v2_detection_ci["lower"], 1.0)
        self.assertEqual(v2_detection_ci["upper"], 1.0)

    def test_primary_comparison_is_paired_and_predefined(self):
        comparison = build_metrics_report(
            self.results, self.oracles, self.cluster_ids, self.analysis_plan
        )[
            "primary_comparison_v2_vs_v1_ind"
        ]
        self.assertEqual(comparison["safe_detection_rate_delta"], 0.3)
        self.assertEqual(comparison["paired_improvements"], 3)
        self.assertEqual(comparison["paired_regressions"], 0)
        self.assertEqual(comparison["dangerous_cluster_count"], 6)
        self.assertEqual(comparison["admissible_cluster_count"], 6)
        self.assertEqual(comparison["exact_cluster_sign_flip_pvalue"], 0.5)
        self.assertEqual(comparison["unadjusted_exact_mcnemar_pvalue"], 0.25)
        self.assertEqual(comparison["false_block_rate_delta"], -0.1)
        self.assertEqual(
            comparison["safe_detection_rate_delta_ci95"]["method"],
            "percentile_cluster_bootstrap",
        )

    def test_development_results_cannot_support_h1(self):
        assessment = build_metrics_report(
            self.results,
            self.oracles,
            self.cluster_ids,
            self.analysis_plan,
            purpose="development_regression",
        )["h1_assessment"]
        self.assertFalse(assessment["eligible_for_confirmatory_claim"])
        self.assertEqual(assessment["status"], "not_assessed_development_only")
        self.assertFalse(assessment["criteria"]["ci_excludes_zero"])

    def test_report_interpretation_depends_on_explicit_purpose(self):
        development = build_metrics_report(
            self.results,
            self.oracles,
            self.cluster_ids,
            self.analysis_plan,
            purpose="development_regression",
        )
        confirmatory = build_metrics_report(
            self.results,
            self.oracles,
            self.cluster_ids,
            self.analysis_plan,
            purpose="confirmatory_e3",
        )
        self.assertEqual(development["purpose"], "development_regression")
        self.assertEqual(confirmatory["purpose"], "confirmatory_e3")
        self.assertIn("not confirmatory", development["interpretation"])
        self.assertIn("confirmatory E3", confirmatory["interpretation"])
        self.assertTrue(confirmatory["h1_assessment"]["eligible_for_confirmatory_claim"])


if __name__ == "__main__":
    unittest.main()
