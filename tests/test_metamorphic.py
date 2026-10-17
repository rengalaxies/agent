from pathlib import Path
import unittest

from datamesh_release_protocol.engine import ReleaseEngine
from datamesh_release_protocol.loaders import load_baseline_policy, load_scenario
from datamesh_release_protocol.models import Decision, ValidationMode


class MetamorphicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ReleaseEngine(load_baseline_policy(Path("policies/v1-ind.yaml")))

    def test_obligation_order_does_not_change_decision(self):
        scenario = load_scenario(Path("scenarios/development/T-01.yaml"))
        first = self.engine.run(scenario, ValidationMode.V2, run_id="metamorphic")
        scenario.obligations.reverse()
        second = self.engine.run(scenario, ValidationMode.V2, run_id="metamorphic")
        self.assertEqual(first.decision, second.decision)

    def test_adding_accepting_consumer_cannot_override_reject(self):
        scenario = load_scenario(Path("scenarios/development/M-03.yaml"))
        rejecting = self.engine.run(scenario, ValidationMode.V2, run_id="metamorphic")
        duplicate = scenario.obligations[1].model_copy(deep=True)
        duplicate.obligation_id = "fintech-engagement-profile-copy"
        duplicate.consumer_id = "fintech-segmentation-copy"
        scenario.obligations.append(duplicate)
        expanded = self.engine.run(scenario, ValidationMode.V2, run_id="metamorphic")
        self.assertEqual(rejecting.decision, Decision.REJECT)
        self.assertEqual(expanded.decision, Decision.REJECT)

    def test_increasing_window_preserves_acceptance_for_minimum_constraints(self):
        scenario = load_scenario(Path("scenarios/development/T-02.yaml"))
        original = self.engine.run(scenario, ValidationMode.V2, run_id="metamorphic")
        scenario.new_contract.semantic.calculation_window_days = 30
        increased = self.engine.run(scenario, ValidationMode.V2, run_id="metamorphic")
        self.assertEqual(original.decision, Decision.ACCEPT)
        self.assertEqual(increased.decision, Decision.ACCEPT)

    def test_narrowing_allowed_sources_preserves_acceptance(self):
        scenario = load_scenario(Path("scenarios/development/L-02.yaml"))
        original = self.engine.run(scenario, ValidationMode.V2, run_id="metamorphic")
        scenario.new_contract.semantic.allowed_sources = ["transactions"]
        narrowed = self.engine.run(scenario, ValidationMode.V2, run_id="metamorphic")
        self.assertEqual(original.decision, Decision.ACCEPT)
        self.assertEqual(narrowed.decision, Decision.ACCEPT)

    def test_valid_migration_restores_acceptance_after_unit_change(self):
        without_migration = load_scenario(Path("scenarios/development/U-01.yaml"))
        rejected = self.engine.run(without_migration, ValidationMode.V2, run_id="metamorphic")
        with_migration = load_scenario(Path("scenarios/development/U-02.yaml"))
        accepted = self.engine.run(with_migration, ValidationMode.V2, run_id="metamorphic")
        self.assertEqual(rejected.decision, Decision.REJECT)
        self.assertEqual(accepted.decision, Decision.ACCEPT)


if __name__ == "__main__":
    unittest.main()
