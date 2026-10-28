"""Offline publication checks; scripted candidates are not live model qualification."""
import copy
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch

from agent_graph.output_contracts import ContractError, dump_document, parse_document
from agent_service.core_analyzer import jira_result
from agent_service.smoke import SmokeBench


class ModelPublicationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.bench = SmokeBench(Path(self.tmp.name))
        self.addCleanup(self.bench.close)

    def investigation(self, context_id, cancelled, deadline):
        graph = self.bench.analyzer.graph
        context = graph.context(context_id)
        source = next(s for s in context['sources'].values() if s['repository'] == 'reporting')
        row = graph.propose(context_id, dict(key='model-publication-test', kind='hypothesis',
            statement='SCRIPTED: investigate whether reporting needs all orders.',
            citations=[dict(source_id=source['id'], start_line=1, end_line=1,
                            quote=source['text'].splitlines()[0])], supersedes=None), from_model=True)
        return dict(context_id=context_id, configuration_id='offline-script', model='SCRIPTED',
                    protocol='actions-v3', hypothesis_ids=[row['id']],
                    events=[dict(usage=dict(prompt_tokens=10, completion_tokens=5))], diagnostics=[], budget={})

    def run_jira(self, transform=lambda report: report):
        def scripted(*args):
            return transform(self.investigation(*args))
        with patch.object(self.bench.analyzer, '_investigate', side_effect=scripted):
            self.bench.deliver_jira()
            self.bench.drain()
        job = [j for j in self.bench.service.store.jobs('jira:10012') if j['state'] == 'DONE'][-1]
        return job['result'], self.bench.jira_texts()[0]

    def run_pr(self, transform=lambda report: report):
        self.bench.github.set_head('acme/orders', 7, self.bench.stand.head('orders', 'pr-7'))
        with patch.object(self.bench.analyzer, '_investigate',
                          side_effect=lambda *args: transform(self.investigation(*args))):
            self.bench.deliver_pr('opened')
            self.bench.drain()
        job = [j for j in self.bench.service.store.jobs('github:acme/orders#7') if j['state'] == 'DONE'][-1]
        return job['result'], self.bench.pr_comments()[0]['body']

    def test_full_deterministic_result_survives_extra_hypothesis(self):
        def full(*args, **kwargs):
            document = dump_document(jira_result(*args, **kwargs))
            claim = document['claims'][0]
            document['claims'] += [{**claim, 'id': f'capacity:{i}'}
                                   for i in range(128 - len(document['claims']))]
            return parse_document(document)
        with patch('agent_service.core_analyzer.jira_result', side_effect=full):
            result, text = self.run_jira()
        self.assertEqual(len(result['claims']), 128)
        self.assertNotIn('SCRIPTED:', text)
        self.assertEqual(result['status'], 'USEFUL')

    def test_supporting_references_are_checked_at_contract_boundary(self):
        result, _ = self.run_jira()
        hypothesis = next(e for e in result['evidence'] if e['origin'] == 'model_hypothesis')
        hypothesis['supporting_refs'] = ['ev:missing']
        with self.assertRaises(ContractError):
            parse_document(result)

    def test_pr_renders_hypothesis_and_supporting_source(self):
        result, text = self.run_pr()
        self.assertTrue(any(e['origin'] == 'model_hypothesis' for e in result['evidence']))
        self.assertIn('SCRIPTED:', text)
        self.assertIn('код reporting@', text)

    def test_pr_partial_usage_does_not_lose_result(self):
        def incomplete(report):
            report['events'][0]['usage'].pop('completion_tokens')
            return report
        result, _ = self.run_pr(incomplete)
        self.assertEqual(result['costs']['prompt_tokens'], 10)
        self.assertIsNone(result['costs']['completion_tokens'])

    def test_pr_transport_failure_keeps_usage_unknown(self):
        def failed(report):
            return {**report, 'events': [], 'hypothesis_ids': [],
                    'diagnostics': [dict(layer='transport', reason_code='model_timeout')]}
        result, _ = self.run_pr(failed)
        self.assertEqual(result['costs']['model_calls'], 1)
        self.assertIsNone(result['costs']['prompt_tokens'])
        self.assertIsNone(result['costs']['completion_tokens'])

    def test_pr_foreign_context_candidate_is_not_published(self):
        result, text = self.run_pr(lambda r: {**r, 'context_id': 'another-context'})
        self.assertNotIn('SCRIPTED:', text)

    def test_jira_publishes_candidate_as_hypothesis_with_source_reference(self):
        result, text = self.run_jira()
        claims = [c for c in result['claims'] if c['statement'].startswith('SCRIPTED:')]
        self.assertEqual(len(claims), 1)
        self.assertEqual((claims[0]['kind'], claims[0]['uncertainty']), ('hypothesis', 'HIGH'))
        refs = {e['id']: e for e in result['evidence']}
        hypothesis = refs[claims[0]['evidence_refs'][0]]
        self.assertEqual((hypothesis['origin'], hypothesis['sufficiency']), ('model_hypothesis', 'NOT_ASSESSED'))
        self.assertTrue(hypothesis['supporting_refs'])
        self.assertIn('SCRIPTED: investigate whether reporting needs all orders.', text)
        self.assertIn('гипотеза модели', text)
        self.assertIn('код reporting@', text)

    def test_absent_model_report_is_explicit_in_the_user_comment(self):
        self.bench.deliver_jira()
        self.bench.drain()
        job = [j for j in self.bench.service.store.jobs('jira:10012') if j['state'] == 'DONE'][-1]
        self.assertIsNone(job['result']['model'])
        self.assertEqual(job['result']['costs']['model_calls'], 0)
        self.assertIn('Детерминированный результат (модельный отчёт не представлен)', self.bench.jira_texts()[0])

    def test_bad_candidate_does_not_hide_an_authorized_candidate(self):
        result, text = self.run_jira(lambda r: {**r, 'hypothesis_ids': ['fabricated', *r['hypothesis_ids']]})
        self.assertIn('SCRIPTED:', text)
        self.assertEqual(sum(e['origin'] == 'model_hypothesis' for e in result['evidence']), 1)

    def test_full_evidence_capacity_preserves_static_result(self):
        def full(*args, **kwargs):
            document = dump_document(jira_result(*args, **kwargs))
            evidence = document['evidence'][0]
            document['evidence'] += [{**evidence, 'id': f'capacity:{i}'}
                                     for i in range(512 - len(document['evidence']))]
            return parse_document(document)
        with patch('agent_service.core_analyzer.jira_result', side_effect=full):
            result, text = self.run_jira()
        self.assertEqual(len(result['evidence']), 512)
        self.assertNotIn('SCRIPTED:', text)
        self.assertEqual(result['status'], 'USEFUL')

    def test_unknown_candidate_id_is_not_published(self):
        def unknown(report):
            return {**report, 'hypothesis_ids': ['fabricated']}
        result, text = self.run_jira(unknown)
        self.assertNotIn('SCRIPTED:', text)
        self.assertFalse(any(e['origin'] == 'model_hypothesis' for e in result['evidence']))

    def test_investigation_for_another_context_is_not_published(self):
        result, text = self.run_jira(lambda r: {**r, 'context_id': 'another-context'})
        self.assertNotIn('SCRIPTED:', text)

    def test_external_proposal_cannot_be_labeled_as_model_evidence(self):
        def external(report):
            graph = self.bench.analyzer.graph
            row = next(r for r in graph.proposals(graph.context(report['context_id']))
                       if r['id'] == report['hypothesis_ids'][0])
            proposal = {**row['proposal'], 'key': 'external', 'statement': 'EXTERNAL: not a model result'}
            external_row = graph.propose(report['context_id'], proposal, from_model=False)
            return {**report, 'hypothesis_ids': [external_row['id']]}
        result, text = self.run_jira(external)
        self.assertNotIn('EXTERNAL:', text)
        self.assertFalse(any(e['origin'] == 'model_hypothesis' for e in result['evidence']))

    def test_superseded_hypothesis_is_not_published(self):
        def supersede(report):
            graph = self.bench.analyzer.graph
            row = next(r for r in graph.proposals(graph.context(report['context_id']))
                       if r['id'] == report['hypothesis_ids'][0])
            graph.propose(report['context_id'], {**row['proposal'], 'kind': 'human_correction',
                'statement': 'Human correction', 'supersedes': row['id']})
            return report
        result, text = self.run_jira(supersede)
        self.assertNotIn('SCRIPTED:', text)

    def test_unclear_intent_is_not_promoted_by_a_model_hypothesis(self):
        fields = self.bench.jira.issues['10012']['fields']
        fields['summary'] = 'Speed up the dashboard'
        fields['description'] = None
        result, text = self.run_jira()
        self.assertEqual(result['status'], 'ABSTAINED')
        self.assertNotIn('SCRIPTED:', text)

    def test_missing_completion_usage_stays_unknown(self):
        def incomplete(report):
            report = copy.deepcopy(report)
            report['events'][0]['usage'].pop('completion_tokens')
            return report
        result, _ = self.run_jira(incomplete)
        self.assertEqual(result['costs']['prompt_tokens'], 10)
        self.assertIsNone(result['costs']['completion_tokens'])

    def test_transport_failure_without_reply_does_not_claim_zero_usage(self):
        def failed(report):
            return {**report, 'events': [], 'hypothesis_ids': [],
                    'diagnostics': [dict(layer='transport', reason_code='model_timeout')]}
        result, _ = self.run_jira(failed)
        self.assertEqual(result['costs']['model_calls'], 1)
        self.assertIsNone(result['costs']['prompt_tokens'])
        self.assertIsNone(result['costs']['completion_tokens'])


if __name__ == '__main__':
    unittest.main()
