"""Controlled scale data integrity and real-core lifecycle checks, not heldout quality."""
import ast
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_graph.contracts import Policy
from agent_graph.sources import collect
from tools import prepare_impactmap_corpora as corpora
from tools.benchmark_impactmap import validate_manifest


class CorpusTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.directory = cls.root / 'corpus'
        cls.manifest = corpora.generate_corpus(cls.directory, repositories=5, python_lines=900, seed=42)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_pinned_counts_equal_real_code_not_comments_and_oracle_stays_separate(self):
        inp = corpora.load_benchmark_input(self.directory)
        validate_manifest(inp)
        collected = collect(Policy.model_validate(inp['policy']), self.manifest['base_revisions'])
        sources = list(collected['sources'].values())
        actual = sum(bool(line.strip()) and not line.lstrip().startswith('#')
                     for s in sources for line in s['text'].splitlines())
        self.assertEqual(actual, 900)
        self.assertEqual(actual, self.manifest['totals']['python_nonblank_noncomment_lines'])
        self.assertEqual(len(sources), self.manifest['totals']['files'])
        self.assertEqual(collected['bytes_read'], self.manifest['totals']['bytes'])
        self.assertTrue(all(s['path'].endswith('.py') for s in sources))
        for source in sources:
            ast.parse(source['text'])
        self.assertNotIn('oracle', json.dumps(inp))
        self.assertNotIn('expected_dependencies', json.dumps(inp))
        self.assertEqual(self.manifest['effective_limits']['max_corpus_bytes'], 8_000_000)
        self.assertEqual(self.manifest['product_default_limits']['max_corpus_bytes'], 8_000_000)

    def test_same_seed_is_path_independent_and_different_seed_changes_sources(self):
        again = corpora.generate_corpus(self.root / 'again', repositories=5, python_lines=900, seed=42)
        other = corpora.generate_corpus(self.root / 'different', repositories=5, python_lines=900, seed=43)
        self.assertEqual(self.manifest, again)
        self.assertNotEqual(self.manifest['base_revisions'], other['base_revisions'])
        self.assertEqual((self.directory / 'oracle.json').read_bytes(), (self.root / 'again/oracle.json').read_bytes())

    def test_existing_output_and_invalid_size_are_refused(self):
        sentinel = self.directory / 'do-not-overwrite.txt'
        sentinel.write_text('preserve')
        with self.assertRaises(FileExistsError):
            corpora.generate_corpus(self.directory, repositories=5, python_lines=900)
        self.assertEqual(sentinel.read_text(), 'preserve')
        with self.assertRaises(ValueError):
            corpora.generate_corpus(self.root / 'invalid', repositories=5, python_lines=3)
        self.assertFalse((self.root / 'invalid').exists())

    def test_streams_pin_one_pr_head_updates_and_distinct_pr_ids(self):
        streams = self.manifest['streams']
        for n in (1, 5, 10):
            updates, independent = streams['head_updates'][str(n)], streams['independent_prs'][str(n)]
            self.assertEqual(len(updates), n)
            self.assertEqual({r['pr_id'] for r in updates}, {1})
            self.assertEqual({r['pr_id'] for r in independent}, set(range(1, n + 1)))
            self.assertTrue(all(r['base_sha'] == self.manifest['base_revisions']['r00'] for r in updates))
            self.assertEqual([r['parent_sha'] for r in updates[1:]], [r['head_sha'] for r in updates[:-1]])
        self.assertNotEqual(streams['independent_prs']['10'][-1]['head_sha'], streams['head_updates']['10'][-1]['head_sha'])

    def test_real_core_detects_new_consumer_retracts_call_and_keeps_unavailable_stale(self):
        result = corpora.verify_corpus(self.directory, self.root / 'verify')
        self.assertTrue(result['base_oracle_match'])
        self.assertTrue(result['operations_oracle_match'])
        self.assertTrue(result['source_inventory_match'])
        self.assertTrue(result['new_consumer_detected'])
        self.assertTrue(result['removed_call_retracted'])
        self.assertTrue(result['partial_access_visible'])
        self.assertTrue(result['stale_preserved'])
        self.assertTrue(result['baseline_findings_oracle_match'])
        self.assertTrue(result['new_consumer_findings_oracle_match'])
        self.assertTrue(result['added_head_dependencies_match'])
        self.assertTrue(result['removed_head_dependencies_match'])
        self.assertTrue(result['operation_removed_verified'])
        self.assertEqual(result['removed_comparative_coverage'], 'COMPLETE_WITHIN_PROFILE')
        self.assertEqual(result['removed_head_coverage'], 'PARTIAL')
        self.assertEqual(len(result['resolved_removed_calls']), 3)
        self.assertTrue(result['located_baseline_findings'][0]['witnesses'])
        self.assertEqual(result['partial_available_repositories'], 4)

    def test_noise_does_not_change_located_findings(self):
        larger = self.root / 'larger'
        corpora.generate_corpus(larger, repositories=5, python_lines=2100, seed=42)
        comparison = corpora.verify_noise_pair(self.directory, larger, self.root / 'noise-check')
        self.assertTrue(comparison['same_located_findings'])
        self.assertEqual(comparison['finding_count'], 3)

    def test_density_and_missing_source_inputs_keep_declared_shape(self):
        dense = corpora.generate_corpus(self.root / 'dense', repositories=5, python_lines=900,
                                        seed=42, calls_per_consumer=8)
        self.assertEqual(dense['totals']['python_nonblank_noncomment_lines'], 900)
        self.assertEqual(dense['known_dependency_callsites'], 24)
        verified = corpora.verify_corpus(self.root / 'dense', self.root / 'dense-verified')
        self.assertTrue(verified['removed_head_dependencies_match'])
        self.assertTrue(verified['verification_passed'])
        missing = corpora.load_benchmark_input(self.directory, scenario='partial_access')
        validate_manifest(missing)
        self.assertFalse(Path(missing['policy']['repositories'][1]['root']).exists())

    def test_portable_root_cannot_escape_corpus(self):
        bad = copy.deepcopy(self.manifest)
        bad['policy']['repositories'][0]['root'] = '../outside'
        path = self.directory / 'corpus-manifest.json'
        original = path.read_bytes()
        try:
            path.write_text(json.dumps(bad))
            with self.assertRaisesRegex(ValueError, '^corpus_root_escape$'):
                corpora.load_benchmark_input(self.directory)
        finally:
            path.write_bytes(original)

    def test_manifest_file_hash_mismatch_cannot_pass_on_counts_alone(self):
        bad = copy.deepcopy(self.manifest)
        bad['repositories'][0]['inventory'][0]['sha256'] = '0' * 64
        path = self.directory / 'corpus-manifest.json'
        original = path.read_bytes()
        try:
            path.write_text(json.dumps(bad))
            result = corpora.verify_corpus(self.directory, self.root / 'tampered-check')
            self.assertFalse(result['source_inventory_match'])
            self.assertFalse(result['verification_passed'])
        finally:
            path.write_bytes(original)

    def test_returned_manifest_does_not_mutate_global_limits(self):
        manifest = corpora.generate_corpus(self.root / 'isolated-limits', repositories=3, python_lines=300)
        original = dict(corpora.LIMITS)
        try:
            manifest['effective_limits']['max_files'] = 1
            self.assertEqual(corpora.LIMITS, original)
        finally:
            corpora.LIMITS.clear()
            corpora.LIMITS.update(original)

    def test_missing_existing_findings_cannot_pass_on_new_consumer_alone(self):
        from agent_graph.engine import Graph
        original = Graph.analyze_change
        def drop_existing(graph, *args, **kwargs):
            result = original(graph, *args, **kwargs)
            return {**result, 'findings': [f for f in result['findings'] if f['consumer'] == 'consumer_04']}
        with patch.object(Graph, 'analyze_change', drop_existing):
            result = corpora.verify_corpus(self.directory, self.root / 'dropped-findings')
        self.assertFalse(result['verification_passed'])
        self.assertFalse(result['baseline_findings_oracle_match'])
        self.assertFalse(result['new_consumer_findings_oracle_match'])

    def test_suite_axes_hold_topology_and_non_target_dimension_fixed(self):
        specs = {s['name']: s for s in corpora.suite_specs()}
        self.assertEqual((specs['repos5-lines50k']['repositories'], specs['repos5-lines50k']['python_lines']), (5, 50_000))
        self.assertEqual((specs['repos10-lines100k']['repositories'], specs['repos10-lines100k']['python_lines']), (10, 100_000))
        self.assertEqual(specs['repos10-lines50k']['python_lines'], specs['repos5-lines50k']['python_lines'])
        self.assertEqual(specs['repos5-lines100k']['repositories'], specs['repos5-lines50k']['repositories'])
        self.assertEqual(specs['repos5-lines50k-dense']['calls_per_consumer'], 8)


if __name__ == '__main__':
    unittest.main()
