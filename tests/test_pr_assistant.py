import copy
from datetime import datetime
import json
from pathlib import Path
import unittest

from datamesh_release_protocol.dependency_import import import_sql, import_manifest, impact_paths
from datamesh_release_protocol.change_assistant import execute_fixture, check_regression
from run_pr_assistant import load_example, report, artifacts, write_report
from compare_pr_assistant import compare, variant, same_artifacts, execute_modes

ROOT = Path(__file__).resolve().parents[1]


class ImportTests(unittest.TestCase):
    def test_independently_declared_import_examples(self):
        catalog = json.loads((ROOT / 'examples/pr-assistant/import-catalog.json').read_text())
        for case in catalog['cases']:
            with self.subTest(case=case['id']):
                result = import_sql(case['sql'], 'consumer', catalog['schemas'], 'git:fixture@1')
                actual = {o['producer']: o['fields'] for o in result['observations']}
                self.assertEqual(actual, case['expected'])
                self.assertEqual(bool(result['gaps']), case['gap'])
                self.assertTrue(all(o['status'] == 'observed' for o in result['observations']))

    def test_write_attach_and_multiple_statements_are_not_supported(self):
        for sql in ['DROP TABLE spend', "ATTACH DATABASE '/tmp/should-not-exist' AS other",
                    'SELECT amount FROM spend; DELETE FROM spend']:
            result = import_sql(sql, 'consumer', {'spend': {'amount': 'decimal'}}, 'test:1')
            self.assertTrue(result['gaps'])

    def test_source_and_schema_changes_change_evidence(self):
        first = import_sql('SELECT * FROM spend', 'c', {'spend': {'amount': 'decimal'}}, 'commit:1')
        second = import_sql('SELECT * FROM spend', 'c', {'spend': {'amount': 'decimal', 'fee': 'decimal'}}, 'commit:2')
        self.assertNotEqual(first['artifact_hash'], second['artifact_hash'])

    def test_manifest_mapping_multihop_and_orphan(self):
        data, _, _ = load_example()
        result = import_manifest(data['manifest'], data['source_ref'], data['bindings'])
        traversal = impact_paths(result['observations'], 'spending_activity_profile')
        self.assertEqual(len(traversal['paths']['retail-offers']), 2)
        data['manifest']['nodes']['model.demo.retail']['depends_on']['nodes'] = ['unknown']
        self.assertTrue(import_manifest(data['manifest'], 'commit:1')['gaps'])

    def test_unknown_manifest_version_never_claims_supported(self):
        self.assertEqual(import_manifest({'metadata': {}}, 'commit:1')['parse_status'], 'partial')

    def test_cycle_and_diamond_have_deterministic_equal_retrieval(self):
        edges = [dict(producer=p, consumer=c) for p, c in [('p', 'a'), ('p', 'b'), ('a', 'c'), ('b', 'c'), ('c', 'p')]]
        graph = impact_paths(edges, 'p')
        flat = impact_paths(list(reversed(edges)), 'p', strategy='flat')
        self.assertEqual(graph['paths'], flat['paths'])
        self.assertEqual(set(graph['paths']), {'a', 'b', 'c'})
        self.assertLess(graph['edge_inspections'], flat['edge_inspections'])
        self.assertEqual(graph['index_build_edges'], len(edges))


class ChangeAssistantTests(unittest.TestCase):
    def test_end_to_end_repair_and_fixture_recheck(self):
        data, scenario, policy = load_example()
        result = report(data, scenario, policy)
        self.assertEqual(result['decision'], 'REJECT')
        candidate = result['proposed_artifact']
        self.assertEqual(candidate['typed_recheck'], 'ACCEPT')
        self.assertEqual(candidate['regression_recheck']['decision'], 'ACCEPT')
        regression = candidate['regression_test']
        self.assertEqual(check_regression(candidate['sql'], regression['schemas'], regression['tables'],
                                         regression['expected'])['decision'], 'ACCEPT')
        self.assertEqual(scenario.new_contract.semantic.unit, 'kopeck')
        self.assertFalse(result['release_authorization'])
        self.assertFalse(candidate['applies_automatically'])

    def test_safe_change_has_no_new_approval_or_repair(self):
        data, scenario, policy = variant('safe')
        result = report(data, scenario, policy)
        self.assertEqual(result['decision'], 'ACCEPT')
        self.assertIsNone(result['proposed_artifact'])

    def test_stale_metadata_does_not_silently_accept(self):
        for name in ['missing_state', 'expired', 'owner_changed', 'candidate', 'boundary_unknown']:
            with self.subTest(name=name):
                data, scenario, policy = variant(name)
                self.assertEqual(report(data, scenario, policy)['decision'], 'NEEDS_REVIEW')

    def test_known_violation_dominates_missing_evidence(self):
        data, scenario, policy = load_example()
        data['requirement_states'] = {}
        self.assertEqual(report(data, scenario, policy)['decision'], 'REJECT')

    def test_undocumented_consumer_is_visible(self):
        data, scenario, policy = variant('unregistered')
        _, _, result = execute_modes(data, scenario, policy, same_artifacts(data, 'unregistered'))
        self.assertEqual(result['decision'], 'NEEDS_REVIEW')
        self.assertTrue(any('shadow-consumer' in issue for issue in result['gaps']))

    def test_fixture_execution_is_bounded_and_read_only(self):
        schemas = {'t': {'x': 'integer'}}
        tables = {'t': [{'x': 1}]}
        for sql in ['DELETE FROM t', "SELECT load_extension('/tmp/not-allowed')", 'SELECT missing_udf(x) FROM t',
                    'WITH RECURSIVE x(n) AS (SELECT 1 UNION ALL SELECT n+1 FROM x) SELECT sum(n) FROM x']:
            with self.subTest(sql=sql):
                self.assertEqual(execute_fixture(sql, schemas, tables)['status'], 'needs_review')

    def test_generated_review_bundle_is_reusable(self):
        from tempfile import TemporaryDirectory
        data, scenario, policy = load_example()
        result = report(data, scenario, policy)
        with TemporaryDirectory() as directory:
            output = Path(directory)
            write_report(result, output)
            self.assertEqual((output / 'compatibility.sql').read_text(), data['old_sql'])
            self.assertTrue((output / 'pr-review.md').read_text())
            self.assertTrue(json.loads((output / 'regression-fixture.json').read_text()))
            safe_data, safe_scenario, safe_policy = variant('safe')
            with self.assertRaises(ValueError):
                write_report(report(safe_data, safe_scenario, safe_policy), output)

    def test_empty_data_does_not_count_as_successful_regression(self):
        result = check_regression('SELECT amount FROM t', {'t': {'amount': 'decimal'}}, {'t': []},
                                  {'columns': ['amount'], 'rows': []})
        self.assertEqual(result['decision'], 'NEEDS_REVIEW')


class ComparisonTests(unittest.TestCase):
    def test_comparison_is_reproducible_and_can_show_v2_loss(self):
        result = compare()
        self.assertEqual(result, compare())
        self.assertEqual(result['cases'], 16)
        self.assertTrue(result['retrieval_parity'])
        # This intentionally fails if results are massaged to make V2 win.
        cosmetic = next(row for row in result['rows'] if row['id'] == 'formula-formatting')
        self.assertEqual(cosmetic['decisions']['consumer_tests_scan'], 'ACCEPT')
        self.assertEqual(cosmetic['decisions']['v2_graph_assistant'], 'REJECT')

    def test_scoring_labels_are_not_mode_inputs(self):
        data, scenario, policy = variant('unit_break')
        imported = same_artifacts(data, 'unit_break')
        decisions, _, _ = execute_modes(data, scenario, policy, imported)
        self.assertEqual(set(decisions.values()), {'REJECT'})


if __name__ == '__main__':
    unittest.main()
