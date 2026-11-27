"""Measurement contracts, semantic transparency and artifact privacy (not quality evaluation)."""
import copy
import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from examples.orders_reporting.stand import build_stand, _git, _tree, git_env, REPORTING_CLIENT
from tools import benchmark_impactmap as bench

ROOT = Path(__file__).resolve().parents[2]


class SpanTests(unittest.TestCase):
    def test_nested_spans_exclude_children_without_double_counting(self):
        ticks = iter([0.0, 2.0, 5.0, 10.0])
        cpu = iter([(0, 0), (2, 1), (5, 3), (10, 6)])
        def usage():
            own, child = next(cpu)
            return {'self_user_s': own, 'self_system_s': 0, 'child_user_s': child, 'child_system_s': 0,
                    'self_peak_rss_bytes': 100, 'children_peak_rss_bytes': 50}
        meter = bench.SpanRecorder(clock=lambda: next(ticks), usage=usage)
        with meter.span('outer'):
            with meter.span('inner'):
                pass
        by_stage = {s['stage']: s for s in meter.spans}
        self.assertEqual(by_stage['outer']['wall_s'], 10)
        self.assertEqual(by_stage['outer']['exclusive_wall_s'], 7)
        self.assertEqual(by_stage['inner']['wall_s'], 3)
        self.assertEqual(by_stage['inner']['parent_id'], by_stage['outer']['span_id'])
        self.assertEqual(by_stage['outer']['exclusive_self_user_s'], 7)
        self.assertEqual(by_stage['outer']['exclusive_child_user_s'], 4)

    def test_error_records_no_exception_message(self):
        meter = bench.SpanRecorder()
        with self.assertRaisesRegex(ValueError, 'TOKEN_NEVER_EXPORT'):
            with meter.span('test'):
                raise ValueError('TOKEN_NEVER_EXPORT')
        self.assertEqual(meter.spans[0]['error_type'], 'ValueError')
        self.assertNotIn('TOKEN_NEVER_EXPORT', json.dumps(meter.spans))

    def test_peak_rss_units_are_platform_specific(self):
        self.assertEqual(bench.rss_bytes(3, 'Darwin'), 3)
        self.assertEqual(bench.rss_bytes(3, 'Linux'), 3072)
        self.assertIsNone(bench.rss_bytes(3, 'Unsupported'))


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.stand = build_stand(cls.root / 'stand')
        cls.manifest = dict(schema_version='impactmap-benchmark-input-1', provenance='author_fixture',
                            policy=cls.stand.policy(), base_revisions=cls.stand.revisions(),
                            head_revisions=cls.stand.revisions(orders='pr-7'), provider_repository='orders', pr_id=7)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_instrumented_pipeline_preserves_results_facts_and_restores_functions(self):
        from agent_graph import engine
        original_collect, original_extract = engine.collect, engine.extract
        observed = bench.run_case(self.manifest, self.root / 'measured')
        reference = bench.run_case(self.manifest, self.root / 'reference', instrumented=False)
        self.assertIs(engine.collect, original_collect)
        self.assertIs(engine.extract, original_extract)
        self.assertEqual([s['semantic_sha256'] for s in observed['samples']],
                         [s['semantic_sha256'] for s in reference['samples']])
        self.assertEqual(observed['graph_facts_sha256'], reference['graph_facts_sha256'])
        self.assertEqual([s['mode'] for s in observed['samples']], ['first_analysis', 'warm_repeat'])
        stages = {s['stage'] for s in observed['spans']}
        self.assertTrue({'collect', 'extract', 'graph_sync', 'analysis', 'render',
                         'local_publication_create', 'local_publication_update'} <= stages)
        self.assertTrue(observed['contexts'])
        counts = observed['contexts'][0]
        self.assertEqual(counts['repositories_configured'], 5)
        self.assertEqual(counts['repositories_available'], 5)
        self.assertGreater(counts['files_read'], 0)
        self.assertGreater(counts['python_nonblank_noncomment_lines'], 0)
        self.assertGreater(counts['dependencies'], 0)
        self.assertTrue(all(s['result']['status'] == 'USEFUL' for s in observed['samples']))
        exported = json.dumps(observed)
        self.assertNotIn('response.raise_for_status()', exported)
        self.assertNotIn('store.read_orders', exported)
        self.assertNotIn(str(self.root), exported)
        self.assertEqual(observed['network']['status'], 'NOT_RUN_OFFLINE')
        self.assertEqual(observed['polling']['status'], 'NOT_RUN_OFFLINE')

    def test_partial_access_stays_visible_and_wrappers_restore_on_exception(self):
        from agent_graph import engine
        manifest = copy.deepcopy(self.manifest)
        manifest['policy']['repositories'][1]['root'] = str(self.root / 'absent')
        observed = bench.run_case(manifest, self.root / 'partial')
        self.assertTrue(any(c['repositories_available'] < c['repositories_configured'] for c in observed['contexts']))
        self.assertTrue(any(c['gap_counts'].get('commit_unavailable') for c in observed['contexts']))
        original = engine.collect
        with self.assertRaises(RuntimeError):
            with bench.instrument(bench.SpanRecorder(), []):
                self.assertIsNot(engine.collect, original)
                raise RuntimeError('DO_NOT_EXPORT_THIS')
        self.assertIs(engine.collect, original)

    def test_model_configuration_is_refused_before_analysis(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['policy']['model'] = {'token': 'SECRET_NEVER_EXPORT'}
        with self.assertRaisesRegex(ValueError, '^benchmark_model_must_be_off$'):
            bench.run_case(manifest, self.root / 'model')

    def test_sensitive_source_content_is_omitted_and_never_exported(self):
        env = git_env(self.stand.root / 'git-home')
        repo = self.stand.repo('reporting')
        tree = _tree(repo, env, {'client.py': REPORTING_CLIENT + '\nAPI_KEY = "BENCHMARK_SECRET_12345"\n'})
        commit = _git(repo, env, 'commit-tree', tree, '-p', self.stand.head('reporting'), '-m', 'sensitive fixture')
        _git(repo, env, 'update-ref', 'refs/heads/privacy-fixture', commit)
        manifest = copy.deepcopy(self.manifest)
        manifest['base_revisions']['reporting'] = commit
        manifest['head_revisions']['reporting'] = commit
        observed = bench.run_case(manifest, self.root / 'sensitive')
        self.assertTrue(any(c['gap_counts'].get('sensitive_source') for c in observed['contexts']))
        self.assertNotIn('BENCHMARK_SECRET_12345', json.dumps(observed))

    def test_provenance_cannot_export_arbitrary_input(self):
        manifest = copy.deepcopy(self.manifest)
        manifest['provenance'] = {'private_note': 'SECRET_NEVER_EXPORT'}
        with self.assertRaisesRegex(ValueError, '^benchmark_invalid_provenance$'):
            bench.public_manifest(manifest)


class CLITests(unittest.TestCase):
    def invoke(self, *args):
        return subprocess.run([sys.executable, '-m', 'tools.benchmark_impactmap', *map(str, args)],
                              cwd=ROOT, capture_output=True, text=True)

    def test_cli_writes_consistent_raw_artifacts_and_does_not_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / 'result'
            result = self.invoke('--output', output, '--repeats', 1)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            summary = json.loads((output / 'summary.json').read_text())
            rows = [json.loads(line) for line in (output / 'measurements.jsonl').read_text().splitlines()]
            with (output / 'spans.csv').open() as stream:
                spans = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 1)
            self.assertEqual(len(spans), len(rows[0]['measured']['spans']))
            self.assertTrue(summary['all_semantics_equal'])
            self.assertEqual(summary['independent_worker_processes'], 1)
            self.assertEqual(summary['performance_observations'], 2)
            sentinel = output / 'keep.txt'
            sentinel.write_text('preserve')
            duplicate = self.invoke('--output', output, '--repeats', 1)
            self.assertNotEqual(duplicate.returncode, 0)
            self.assertEqual(sentinel.read_text(), 'preserve')

    def test_invalid_manifest_never_exports_input_or_exception_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / 'input.json'
            manifest.write_text('{"SECRET_NEVER_EXPORT":"sensitive-input"}')
            result = self.invoke('--manifest', manifest, '--output', Path(tmp) / 'out')
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('SECRET_NEVER_EXPORT', result.stdout + result.stderr)
            self.assertNotIn('sensitive-input', result.stdout + result.stderr)
            self.assertNotIn('Traceback', result.stderr)

    def test_timeout_launch_and_invalid_json_preserve_failure_rows_and_summary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            stand = build_stand(root / 'stand')
            manifest = dict(schema_version='impactmap-benchmark-input-1', provenance='author_fixture',
                            policy=stand.policy(), base_revisions=stand.revisions(),
                            head_revisions=stand.revisions(orders='pr-7'), provider_repository='orders', pr_id=7)
            success = SimpleNamespace(returncode=0, stdout=json.dumps(dict(
                measured=dict(spans=[], samples=[]), semantics_equal=True)))
            failures = [subprocess.TimeoutExpired(['synthetic'], 1), OSError('SECRET_NEVER_EXPORT'),
                        SimpleNamespace(returncode=0, stdout='SECRET_NEVER_EXPORT')]
            for index, failure in enumerate(failures):
                with self.subTest(index=index), patch.object(bench, 'source_identity', return_value={}), \
                        patch.object(bench, 'environment', return_value={}), \
                        patch.object(bench.subprocess, 'run', side_effect=[success, failure]):
                    output = root / f'out-{index}'
                    summary = bench.execute(manifest, output, 2)
                rows = [json.loads(line) for line in (output / 'measurements.jsonl').read_text().splitlines()]
                self.assertEqual(len(rows), 2)
                self.assertFalse(rows[1]['semantics_equal'])
                self.assertEqual(summary['worker_errors'], 1)
                self.assertTrue((output / 'spans.csv').exists())
                self.assertTrue((output / 'summary.json').exists())
                self.assertNotIn('SECRET_NEVER_EXPORT', (output / 'measurements.jsonl').read_text())


if __name__ == '__main__':
    unittest.main()
