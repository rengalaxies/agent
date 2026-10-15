from pathlib import Path
import unittest
import yaml
from datamesh_release_protocol.migration_evidence import verify_migration, run_with_migration_evidence
from datamesh_release_protocol.models import Migration, Scenario, BaselinePolicy

ROOT = Path(__file__).resolve().parents[1]


class MigrationEvidenceTests(unittest.TestCase):
    def migration(self, expression='value / 100', **changes):
        return Migration(**(dict(dimension='unit_scale', source='kopeck:0', target='RUB:2',
                                 expression=expression, validated_examples=1) | changes))

    def fixtures(self):
        return [{'input': '123', 'expected': '1.23'}, {'input': '-50', 'expected': '-0.5'},
                {'input': '0', 'expected': '0'}]

    def test_positive_negative_and_zero(self):
        result = verify_migration(self.migration(), self.fixtures())
        self.assertEqual(result['decision'], 'ACCEPT')
        self.assertEqual(len(result['results']), 3)

    def test_wrong_formula_is_rejected_despite_legacy_count(self):
        result = verify_migration(self.migration('value * 100', validated_examples=100), self.fixtures())
        self.assertEqual(result['decision'], 'REJECT')

    def test_empty_examples_not_declaration(self):
        self.assertEqual(verify_migration(self.migration(), [])['decision'], 'NEEDS_REVIEW')

    def test_decimal_constants_not_binary_float(self):
        result = verify_migration(self.migration('value + 0.1'), [{'input': '0.2', 'expected': '0.3'}])
        self.assertEqual(result['decision'], 'ACCEPT')

    def test_non_executable_syntax_is_review(self):
        for expression in ['WRONG', 'identity_map_v1', '__import__("os")', 'value.__class__',
                           'value ** 100', '[value]', 'True', 'value // 100']:
            with self.subTest(expression=expression):
                self.assertEqual(verify_migration(self.migration(expression), self.fixtures())['decision'],
                                 'NEEDS_REVIEW')

    def test_bad_arithmetic_is_review(self):
        for expression in ['value / 0', 'value * 1000000000000000000']:
            self.assertEqual(verify_migration(self.migration(expression), self.fixtures())['decision'],
                             'NEEDS_REVIEW')

    def test_identity_mapping_requires_another_verifier(self):
        migration = self.migration(dimension='identity_scope', bijective=True)
        self.assertEqual(verify_migration(migration, self.fixtures())['reason'], 'UNSUPPORTED_DIMENSION')

    def test_invalid_fixture_numbers_are_review(self):
        for number in ['NaN', 'Infinity', '1000000000000000001', 'not-a-number']:
            self.assertEqual(verify_migration(self.migration(), [{'input': number, 'expected': '0'}])
                             ['decision'], 'NEEDS_REVIEW')

    def test_payload_limits_and_extra_passed_flags(self):
        for fixtures in [self.fixtures() * 100, [{'input': '1', 'expected': '0.01', 'passed': True}],
                         [{'input': 1, 'expected': '0.01'}]]:
            with self.assertRaises(ValueError):
                verify_migration(self.migration(), fixtures)

    def test_hash_binds_expression_inputs_and_results(self):
        first = verify_migration(self.migration(), self.fixtures())
        self.assertEqual(first, verify_migration(self.migration(), self.fixtures()))
        changed = verify_migration(self.migration('value * 100'), self.fixtures())
        self.assertNotEqual(first['input_hash'], changed['input_hash'])
        self.assertNotEqual(first['receipt_hash'], changed['receipt_hash'])
        changed = verify_migration(self.migration(), [{'input': '100', 'expected': '1'}])
        self.assertNotEqual(first['input_hash'], changed['input_hash'])

    def test_fixture_success_does_not_prove_unseen_values(self):
        # A bad conversion can match zero. The receipt must not overclaim.
        result = verify_migration(self.migration('value * 100'), [{'input': '0', 'expected': '0'}])
        self.assertEqual(result['decision'], 'ACCEPT')
        self.assertEqual(result['guarantee'], 'listed fixtures only')


class MigrationEvidenceGateTests(unittest.TestCase):
    def setUp(self):
        self.scenario = Scenario.model_validate(yaml.safe_load(
            (ROOT / 'scenarios/development/U-02.yaml').read_text()))
        self.policy = BaselinePolicy.model_validate(yaml.safe_load(
            (ROOT / 'policies/v1-ind.yaml').read_text()))

    def gate(self, fixtures):
        return run_with_migration_evidence(self.scenario, self.policy, fixtures, 'migration-evidence')

    def test_strict_gate_rejects_bad_executable_conversion(self):
        self.scenario.migrations[0].expression = 'value * 100'
        result = self.gate([[{'input': '123', 'expected': '1.23'}]])
        self.assertEqual(result['legacy_v2_decision'], 'ACCEPT')
        self.assertEqual(result['decision'], 'REJECT')
        self.assertFalse(result['release_authorization'])

    def test_no_receipt_means_review(self):
        result = self.gate([[]])
        self.assertEqual(result['legacy_v2_decision'], 'ACCEPT')
        self.assertEqual(result['decision'], 'NEEDS_REVIEW')

    def test_correct_conversion_and_exact_fixture_binding(self):
        self.assertEqual(self.gate([[{'input': '123', 'expected': '1.23'}]])['decision'], 'ACCEPT')
        with self.assertRaises(ValueError):
            self.gate([])

    def test_existing_schema_rejection_is_preserved(self):
        self.scenario.new_contract.schema_fields = {'other': 'string'}
        self.assertEqual(self.gate([[]])['decision'], 'REJECT')
