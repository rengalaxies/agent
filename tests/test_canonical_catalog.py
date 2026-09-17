from pathlib import Path
import unittest

from datamesh_release_protocol.engine import ReleaseEngine, scenario_snapshot_id
from pydantic import ValidationError

from datamesh_release_protocol.loaders import (
    load_baseline_policy,
    load_catalog,
    load_oracle_catalog,
    validate_oracle_coverage,
)
from datamesh_release_protocol.models import Decision, Scenario, ScenarioClass, ValidationMode


CATALOG = Path("scenarios/development")
BASELINE = Path("policies/v1-ind.yaml")
ORACLE = Path("oracles/development.yaml")


class CanonicalCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = load_catalog(CATALOG)
        cls.oracles = load_oracle_catalog(ORACLE)
        validate_oracle_coverage(cls.scenarios, cls.oracles)
        cls.engine = ReleaseEngine(load_baseline_policy(BASELINE))

    def test_catalog_has_twenty_unique_scenarios(self):
        self.assertEqual(len(self.scenarios), 20)
        self.assertEqual(len({scenario.scenario_id for scenario in self.scenarios}), 20)
        self.assertEqual(
            {scenario.family_id for scenario in self.scenarios},
            {"F1", "F2", "F3", "F4", "F5", "F6"},
        )

    def test_catalog_is_balanced_and_every_family_has_a_pair(self):
        classes = [oracle.scenario_class.value for oracle in self.oracles.values()]
        self.assertEqual(classes.count("dangerous"), 10)
        self.assertEqual(classes.count("admissible"), 10)
        for family_id in {"F1", "F2", "F3", "F4", "F5", "F6"}:
            family_ids = {
                scenario.scenario_id
                for scenario in self.scenarios
                if scenario.family_id == family_id
            }
            family_classes = {
                self.oracles[scenario_id].scenario_class.value
                for scenario_id in family_ids
            }
            self.assertEqual(family_classes, {"dangerous", "admissible"})

    def test_semantic_modes_match_the_external_oracle(self):
        for mode in [ValidationMode.V1_ORACLE, ValidationMode.V2]:
            for scenario in self.scenarios:
                with self.subTest(mode=mode, scenario=scenario.scenario_id):
                    result = self.engine.run(scenario, mode, run_id="test")
                    self.assertEqual(
                        result.decision,
                        self.oracles[scenario.scenario_id].expected_decision,
                    )

    def test_v2_matches_every_expected_consumer_decision(self):
        for scenario in self.scenarios:
            with self.subTest(scenario=scenario.scenario_id):
                result = self.engine.run(scenario, ValidationMode.V2, run_id="test")
                actual = {
                    consumer.consumer_id: consumer.decision
                    for domain in result.local_verdicts
                    for consumer in domain.consumer_verdicts
                }
                self.assertEqual(
                    actual,
                    self.oracles[scenario.scenario_id].expected_consumer_decisions,
                )

    def test_v0_is_only_a_structural_lower_bound(self):
        decisions = {
            scenario.scenario_id: self.engine.run(scenario, ValidationMode.V0, run_id="test").decision
            for scenario in self.scenarios
        }
        self.assertEqual(set(decisions.values()), {Decision.ACCEPT})

    def test_v1_ind_is_not_artificially_empty(self):
        decisions = {
            scenario.scenario_id: self.engine.run(scenario, ValidationMode.V1_IND, run_id="test").decision
            for scenario in self.scenarios
        }
        self.assertEqual(decisions["M-01"], Decision.ACCEPT)
        self.assertEqual(decisions["T-01"], Decision.ACCEPT)
        self.assertEqual(decisions["M-03"], Decision.ACCEPT)
        for scenario_id in ["U-01", "U-03", "I-01", "I-03", "L-01", "L-03", "P-01"]:
            self.assertEqual(decisions[scenario_id], Decision.REJECT)
        for scenario_id in ["M-02", "U-02", "U-04", "T-02", "T-03", "I-02", "L-02", "L-04", "P-02"]:
            self.assertEqual(decisions[scenario_id], Decision.ACCEPT)
        self.assertEqual(decisions["I-04"], Decision.REJECT)

    def test_consumer_aware_verdicts_differ_inside_t01(self):
        scenario = next(item for item in self.scenarios if item.scenario_id == "T-01")
        result = self.engine.run(scenario, ValidationMode.V2, run_id="test")
        local = {
            consumer.consumer_id: consumer.decision
            for domain in result.local_verdicts
            for consumer in domain.consumer_verdicts
        }
        self.assertEqual(
            local,
            {
                "retail-offers": Decision.REJECT,
                "mobility-offers": Decision.ACCEPT,
            },
        )
        self.assertEqual(result.decision, Decision.REJECT)
        self.assertEqual(
            {verdict.domain_id: verdict.decision for verdict in result.local_verdicts},
            {"mobility": Decision.ACCEPT, "retail": Decision.REJECT},
        )

    def test_v1_oracle_and_v2_have_independent_audit_traces(self):
        scenario = next(item for item in self.scenarios if item.scenario_id == "M-01")
        oracle_result = self.engine.run(
            scenario, ValidationMode.V1_ORACLE, run_id="oracle-trace"
        )
        v2_result = self.engine.run(scenario, ValidationMode.V2, run_id="v2-trace")

        oracle_codes = set(oracle_result.reason_codes)
        v2_codes = set(v2_result.reason_codes)
        self.assertEqual(oracle_result.decision, v2_result.decision)
        self.assertTrue(any(code.startswith("ORACLE_") for code in oracle_codes))
        self.assertFalse(any(code.startswith("V2_") for code in oracle_codes))
        self.assertTrue(any(code.startswith("V2_") for code in v2_codes))
        self.assertFalse(any(code.startswith("ORACLE_") for code in v2_codes))

    def test_v2_is_a_parallel_consumer_aware_strategy_not_v1_ind_plus(self):
        scenario = next(item for item in self.scenarios if item.scenario_id == "I-04")
        baseline = self.engine.run(scenario, ValidationMode.V1_IND, run_id="baseline")
        v2 = self.engine.run(scenario, ValidationMode.V2, run_id="v2")
        self.assertEqual(baseline.decision, Decision.REJECT)
        self.assertEqual(v2.decision, Decision.ACCEPT)

    def test_snapshot_is_deterministic(self):
        first = self.scenarios[0]
        self.assertEqual(
            scenario_snapshot_id(first),
            scenario_snapshot_id(first.model_copy(deep=True)),
        )

    def test_expected_label_is_not_an_engine_input(self):
        payload = self.scenarios[0].model_dump(mode="json")
        payload["expected_decision"] = "ACCEPT"
        with self.assertRaises(ValidationError):
            Scenario.model_validate(payload)

    def test_oracle_classes_match_global_decisions(self):
        for oracle in self.oracles.values():
            expected = (
                Decision.REJECT
                if oracle.scenario_class == ScenarioClass.DANGEROUS
                else Decision.ACCEPT
            )
            self.assertEqual(oracle.expected_decision, expected)


if __name__ == "__main__":
    unittest.main()
