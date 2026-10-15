from pathlib import Path
import unittest
import yaml
from datamesh_release_protocol.consumer_test_baseline import consumer_test_decision
from datamesh_release_protocol.models import Scenario, Decision

ROOT = Path(__file__).resolve().parents[1]


class ConsumerTestBaselineTests(unittest.TestCase):
    def setUp(self):
        self.scenario = Scenario.model_validate(yaml.safe_load(
            (ROOT / 'scenarios/development/U-01.yaml').read_text()))

    def test_detects_unit_change_without_migration(self):
        self.assertEqual(consumer_test_decision(self.scenario), Decision.REJECT)

    def test_missing_required_window_is_unknown(self):
        s = self.scenario
        s.new_contract = s.old_contract.model_copy(deep=True)
        s.obligations[0].min_window_days = 30
        s.new_contract.semantic.calculation_window_days = None
        self.assertEqual(consumer_test_decision(s), Decision.NEEDS_REVIEW)

    def test_failure_dominates_unknown(self):
        s = self.scenario
        s.obligations[0].min_window_days = 30
        s.new_contract.semantic.calculation_window_days = None
        self.assertEqual(consumer_test_decision(s), Decision.REJECT)

    def test_examples_do_not_prove_migration_expression(self):
        # Deliberately captures a limitation shared with current V2: expression
        # content is not executed or proved, only declaration metadata is checked.
        from datamesh_release_protocol.models import Migration
        s = self.scenario
        source = s.new_contract.semantic
        target = s.old_contract.semantic
        s.migrations = [Migration(dimension='unit_scale', source=f'{source.unit}:{source.scale}',
                                 target=f'{target.unit}:{target.scale}', expression='WRONG',
                                 validated_examples=1)]
        self.assertEqual(consumer_test_decision(s), Decision.ACCEPT)
        from datamesh_release_protocol.interpreter import TypedObligationInterpreter
        checks = TypedObligationInterpreter().evaluate(s.new_contract, s.obligations[0], s.migrations)
        self.assertTrue(all(c.outcome == 'TRUE' for c in checks))
