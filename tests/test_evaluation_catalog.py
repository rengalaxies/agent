from collections import Counter
import json
from pathlib import Path
import unittest

import yaml

from datamesh_release_protocol.loaders import (
    load_catalog,
    load_cluster_map,
    load_oracle_catalog,
    validate_oracle_coverage,
)


DEVELOPMENT = Path("scenarios/development")
EVALUATION = Path("scenarios/evaluation")
ORACLE = Path("oracles/evaluation.yaml")
MANIFEST = Path("experiments/evaluation-catalog.yaml")

ALLOWED_CHANGED_DIMENSIONS = {
    "F1": {"meaning", "description", "formula", "allowed_sources"},
    "F2": {"unit", "scale"},
    "F3": {"calculation_window_days"},
    "F4": {"identity_scope"},
    "F5": {"allowed_sources"},
    "F6": {"purposes"},
}


class EvaluationCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.development = load_catalog(DEVELOPMENT)
        cls.evaluation = load_catalog(EVALUATION)
        cls.oracles = load_oracle_catalog(ORACLE)
        cls.manifest = yaml.safe_load(MANIFEST.read_text(encoding="utf-8"))
        cls.cluster_ids = load_cluster_map(MANIFEST, cls.evaluation)

    def test_catalog_has_forty_new_scenarios(self):
        self.assertEqual(len(self.evaluation), 40)
        evaluation_ids = {scenario.scenario_id for scenario in self.evaluation}
        development_ids = {scenario.scenario_id for scenario in self.development}
        self.assertTrue(evaluation_ids.isdisjoint(development_ids))
        self.assertTrue(all(scenario.split == "evaluation" for scenario in self.evaluation))

    def test_oracle_is_balanced_and_complete(self):
        validate_oracle_coverage(self.evaluation, self.oracles)
        classes = Counter(item.scenario_class.value for item in self.oracles.values())
        self.assertEqual(classes, {"dangerous": 20, "admissible": 20})
        for family in {"F1", "F2", "F3", "F4", "F5", "F6"}:
            family_ids = {
                scenario.scenario_id
                for scenario in self.evaluation
                if scenario.family_id == family
            }
            family_classes = {
                self.oracles[scenario_id].scenario_class.value
                for scenario_id in family_ids
            }
            self.assertEqual(family_classes, {"dangerous", "admissible"})

    def test_family_distribution_matches_frozen_manifest(self):
        actual = Counter(scenario.family_id for scenario in self.evaluation)
        self.assertEqual(dict(actual), self.manifest["family_distribution"])
        self.assertEqual(self.manifest["scenario_count"], 40)
        self.assertFalse(self.manifest["oracle_exposed_to_validators"])
        self.assertFalse(self.manifest["main_e3_executed"])

    def test_template_groups_are_unique_and_evaluation_only(self):
        entries = self.manifest["scenarios"]
        self.assertEqual(len(entries), 40)
        groups = [entry["template_group"] for entry in entries]
        self.assertEqual(len(groups), len(set(groups)))
        self.assertEqual(
            {entry["scenario_id"] for entry in entries},
            {scenario.scenario_id for scenario in self.evaluation},
        )

    def test_clusters_pair_dependent_dangerous_and_admissible_variants(self):
        clusters = {}
        for scenario_id, cluster_id in self.cluster_ids.items():
            clusters.setdefault(cluster_id, []).append(scenario_id)
        self.assertEqual(len(clusters), 20)
        self.assertTrue(all(len(items) == 2 for items in clusters.values()))
        for scenario_ids in clusters.values():
            classes = {
                self.oracles[scenario_id].scenario_class.value
                for scenario_id in scenario_ids
            }
            self.assertEqual(classes, {"dangerous", "admissible"})

    def test_no_exact_semantic_transition_is_reused_from_development(self):
        def fingerprint(scenario):
            old = scenario.old_contract.semantic.model_dump(mode="json")
            new = scenario.new_contract.semantic.model_dump(mode="json")
            changed = {
                key: [old.get(key), new.get(key)]
                for key in sorted(set(old) | set(new))
                if old.get(key) != new.get(key)
            }
            return json.dumps(
                [scenario.family_id, changed],
                ensure_ascii=False,
                sort_keys=True,
            )

        development = {fingerprint(scenario) for scenario in self.development}
        evaluation = {fingerprint(scenario) for scenario in self.evaluation}
        self.assertTrue(development.isdisjoint(evaluation))

    def test_scenarios_contain_no_labels_or_baseline_rules(self):
        for path in EVALUATION.glob("*.yaml"):
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("expected_decision:", text)
            self.assertNotIn("expected_consumer_decisions:", text)
            self.assertNotIn("scenario_class:", text)
            self.assertNotIn("baseline_rules:", text)

    def test_each_scenario_changes_only_declared_dimensions(self):
        for scenario in self.evaluation:
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

    def test_oracle_consumer_keys_match_obligations(self):
        for scenario in self.evaluation:
            consumers = {item.consumer_id for item in scenario.obligations}
            expected = set(
                self.oracles[scenario.scenario_id].expected_consumer_decisions
            )
            self.assertEqual(consumers, expected, scenario.scenario_id)


if __name__ == "__main__":
    unittest.main()
