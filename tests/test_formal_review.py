from pathlib import Path
import unittest

from datamesh_release_protocol.loaders import (
    load_baseline_policy,
    load_catalog,
    load_oracle_catalog,
    validate_oracle_coverage,
)


CATALOG = Path("scenarios/development")
ORACLE = Path("oracles/development.yaml")
BASELINE = Path("policies/v1-ind.yaml")

FAMILY_PREFIX = {
    "F1": "M",
    "F2": "U",
    "F3": "T",
    "F4": "I",
    "F5": "L",
    "F6": "P",
}
ALLOWED_CHANGED_DIMENSIONS = {
    "F1": {"meaning", "description", "formula", "allowed_sources"},
    "F2": {"unit", "scale"},
    "F3": {"calculation_window_days"},
    "F4": {"identity_scope"},
    "F5": {"allowed_sources"},
    "F6": {"purposes"},
}


class FormalScenarioReviewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scenarios = load_catalog(CATALOG)
        cls.oracles = load_oracle_catalog(ORACLE)
        cls.baseline = load_baseline_policy(BASELINE)

    def test_oracle_has_exact_scenario_and_consumer_coverage(self):
        validate_oracle_coverage(self.scenarios, self.oracles)

    def test_family_prefixes_are_consistent(self):
        for scenario in self.scenarios:
            self.assertTrue(
                scenario.scenario_id.startswith(FAMILY_PREFIX[scenario.family_id] + "-"),
                scenario.scenario_id,
            )

    def test_each_scenario_changes_only_its_declared_family_dimensions(self):
        for scenario in self.scenarios:
            old = scenario.old_contract.semantic.model_dump()
            new = scenario.new_contract.semantic.model_dump()
            changed = {key for key in old if old[key] != new[key]}
            self.assertTrue(changed, scenario.scenario_id)
            self.assertLessEqual(
                changed,
                ALLOWED_CHANGED_DIMENSIONS[scenario.family_id],
                scenario.scenario_id,
            )
            self.assertEqual(
                scenario.old_contract.schema_fields,
                scenario.new_contract.schema_fields,
                scenario.scenario_id,
            )

    def test_lists_do_not_contain_duplicates(self):
        for scenario in self.scenarios:
            profiles = [scenario.old_contract.semantic, scenario.new_contract.semantic]
            for profile in profiles:
                self.assertEqual(len(profile.allowed_sources), len(set(profile.allowed_sources)))
                self.assertEqual(len(profile.purposes), len(set(profile.purposes)))
            for obligation in scenario.obligations:
                for values in [
                    obligation.accepted_units,
                    obligation.accepted_scales,
                    obligation.accepted_identity_scopes,
                    obligation.allowed_sources,
                    obligation.required_purposes,
                ]:
                    self.assertEqual(len(values), len(set(values)))

    def test_baseline_is_external_and_has_unique_rule_ids(self):
        rule_ids = []
        for rules in self.baseline.family_rules.values():
            rule_ids.extend(rule.rule_id for rule in rules)
        self.assertEqual(len(rule_ids), len(set(rule_ids)))
        for path in CATALOG.glob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("baseline_rules:", text)
            self.assertNotIn("expected_decision:", text)
            self.assertNotIn("expected_consumer_decisions:", text)
            self.assertNotIn("scenario_class:", text)


if __name__ == "__main__":
    unittest.main()
