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
EXPERIMENT = Path("experiments/evaluation.yaml")
ANALYSIS_PLAN = Path("experiments/analysis-plan-0.3.1.yaml")

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

    def test_clusters_group_scenarios_by_semantic_family(self):
        clusters = {}
        for scenario_id, cluster_id in self.cluster_ids.items():
            clusters.setdefault(cluster_id, []).append(scenario_id)
        self.assertEqual(set(clusters), {f"eval-f{index}" for index in range(1, 7)})
        for cluster_id, scenario_ids in clusters.items():
            family_id = cluster_id.removeprefix("eval-").upper()
            self.assertTrue(
                all(
                    next(
                        scenario.family_id
                        for scenario in self.evaluation
                        if scenario.scenario_id == scenario_id
                    )
                    == family_id
                    for scenario_id in scenario_ids
                )
            )
            classes = {
                self.oracles[scenario_id].scenario_class.value
                for scenario_id in scenario_ids
            }
            self.assertEqual(classes, {"dangerous", "admissible"})

    def test_working_protocol_versions_are_consistent(self):
        experiment = yaml.safe_load(EXPERIMENT.read_text(encoding="utf-8"))
        analysis_plan = yaml.safe_load(ANALYSIS_PLAN.read_text(encoding="utf-8"))
        oracle = yaml.safe_load(ORACLE.read_text(encoding="utf-8"))
        self.assertEqual(self.manifest["catalog_id"], "evaluation-catalog-0.3.1")
        self.assertEqual(self.manifest["protocol_version"], "0.3.1")
        self.assertEqual(self.manifest["cluster_unit"], "semantic_family")
        self.assertEqual(self.manifest["cluster_count"], 6)
        self.assertEqual(experiment["protocol_version"], "0.3.1")
        self.assertEqual(analysis_plan["protocol_line"], "0.3.1")
        self.assertEqual(analysis_plan["cluster_unit"], "semantic_family")
        self.assertEqual(analysis_plan["expected_cluster_count"], 6)
        self.assertEqual(oracle["protocol_version"], "0.3.1")

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
