from pathlib import Path
import unittest

from datamesh_release_protocol.engine import ReleaseEngine
from datamesh_release_protocol.loaders import load_baseline_policy, load_scenario
from datamesh_release_protocol.models import Decision, ValidationMode


class MutationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ReleaseEngine(load_baseline_policy(Path("policies/v1-ind.yaml")))

    def run_v2(self, scenario_id: str):
        scenario = load_scenario(Path(f"scenarios/development/{scenario_id}.yaml"))
        return scenario, self.engine.run(scenario, ValidationMode.V2, run_id="mutation")

    def test_formula_mutation_turns_documentation_change_into_reject(self):
        scenario, _ = self.run_v2("M-02")
        scenario.new_contract.semantic.formula = "sum(net_amount)"
        result = self.engine.run(scenario, ValidationMode.V2, run_id="mutation")
        self.assertEqual(result.decision, Decision.REJECT)

    def test_forbidden_source_mutation_is_rejected(self):
        scenario, _ = self.run_v2("L-02")
        scenario.new_contract.semantic.allowed_sources.append("ad_network")
        result = self.engine.run(scenario, ValidationMode.V2, run_id="mutation")
        self.assertEqual(result.decision, Decision.REJECT)

    def test_removed_required_purpose_is_rejected(self):
        scenario, _ = self.run_v2("P-02")
        scenario.new_contract.semantic.purposes.remove("risk_scoring")
        result = self.engine.run(scenario, ValidationMode.V2, run_id="mutation")
        self.assertEqual(result.decision, Decision.REJECT)

    def test_unvalidated_unit_migration_is_rejected(self):
        scenario, original = self.run_v2("U-02")
        self.assertEqual(original.decision, Decision.ACCEPT)
        scenario.migrations[0].validated_examples = 0
        result = self.engine.run(scenario, ValidationMode.V2, run_id="mutation")
        self.assertEqual(result.decision, Decision.REJECT)

    def test_non_bijective_identity_migration_is_rejected(self):
        scenario, original = self.run_v2("I-02")
        self.assertEqual(original.decision, Decision.ACCEPT)
        scenario.migrations[0].bijective = False
        result = self.engine.run(scenario, ValidationMode.V2, run_id="mutation")
        self.assertEqual(result.decision, Decision.REJECT)


if __name__ == "__main__":
    unittest.main()
