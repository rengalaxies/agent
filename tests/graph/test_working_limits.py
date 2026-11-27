"""Working pilot defaults, explicit operator budgets and atomic collection refusal."""
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from agent_graph.contracts import GraphError, Policy
from agent_graph.engine import Graph
from agent_graph.sources import collect
from agent_graph.store import Store
from examples.agent_graph.fixture import create_fixture


class WorkingLimitsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.policy = create_fixture(self.root)
        (self.root/'corpus/health/client.py').write_text('value = 1\n')
        self.store = Store(self.root/'state'); self.addCleanup(self.store.close)

    def configured(self, **limits):
        data = self.policy.model_dump(); data['limits'] = limits
        return Policy.model_validate(data)

    def test_omitted_limits_accept_more_than_two_megabytes_across_repositories(self):
        for repo in ('orders', 'reporting'):
            for index in range(20):
                (self.root/'corpus'/repo/f'note-{index}.md').write_text('x'*60_000)
        context = Graph(self.policy, self.store).prepare_context()
        self.assertGreater(sum(len(s['text'].encode()) for s in context['sources'].values()), 2_000_000)
        self.assertEqual(context['coverage'], 'COMPLETE_WITHIN_PROFILE')

    def test_omitted_limits_accept_more_than_256_selected_files(self):
        for index in range(280):
            (self.root/'corpus/orders'/f'note-{index}.md').write_text('note\n')
        context = Graph(self.policy, self.store).prepare_context()
        self.assertGreater(len(context['sources']), 256)
        self.assertEqual(context['coverage'], 'COMPLETE_WITHIN_PROFILE')

    def test_explicit_lower_byte_budget_aborts_without_saving_partial_context(self):
        graph = Graph(self.configured(max_corpus_bytes=1), self.store)
        before = self.store.head(graph.view)
        with self.assertRaisesRegex(GraphError, '^corpus_limit$'):
            graph.prepare_context()
        self.assertEqual(self.store.head(graph.view), before)

    def test_explicit_file_and_time_budgets_remain_effective(self):
        with self.assertRaisesRegex(GraphError, '^file_count_limit$'):
            collect(self.configured(max_files=1))
        with patch('agent_graph.sources.time.monotonic', side_effect=[0.0, 2.0]):
            with self.assertRaisesRegex(GraphError, '^scan_timeout$'):
                collect(self.configured(scan_seconds=1.0))

    def test_pinned_git_collection_keeps_cumulative_byte_guard(self):
        repo = self.root/'corpus/orders'
        def git(*args):
            return subprocess.check_output(['git','-C',str(repo),*args],stderr=subprocess.DEVNULL,text=True).strip()
        git('init','-b','main'); git('add','.')
        git('-c','user.name=fixture','-c','user.email=fixture@example.invalid','commit','-m','fixture')
        data = self.policy.model_dump(); data['limits'] = {'max_corpus_bytes':1}
        data['repositories'][0].update(snapshot='git', revision=git('rev-parse','HEAD'))
        with self.assertRaisesRegex(GraphError, '^corpus_limit$'):
            Graph(Policy.model_validate(data), self.store).prepare_context()

    def test_single_file_limit_stays_visible_as_partial_coverage(self):
        (self.root/'corpus/orders/oversize.md').write_text('x'*65_537)
        context = Graph(self.policy, self.store).prepare_context()
        self.assertEqual(context['coverage'], 'PARTIAL')
        self.assertIn('file_limit', [g['code'] for g in context['graph']['gaps']])
