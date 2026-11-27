"""Load acceptance uses real graph/core/queue, with only local transport substituted."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from tools import prepare_impactmap_corpora as corpora
from tools import load_impactmap as load
from unittest.mock import patch


class LoadTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        cls.corpus = cls.root / 'corpus'
        cls.manifest = corpora.generate_corpus(cls.corpus, repositories=5, python_lines=300)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_fresh_reconcile_matches_persisted_events_including_removals(self):
        r=load.run_graph_equivalence(self.corpus,self.root/'equivalence')
        self.assertTrue(r['passed'])
        self.assertEqual(set(x['scenario'] for x in r['cases']),{'baseline','new_consumer','removed_consumer','operation_removed'})
        self.assertTrue(all(x['equal'] and x['source_access_complete'] for x in r['cases']))
        self.assertTrue(all(x['facts_count']==x['expected_facts_count']>0 for x in r['cases']))
        removed=next(x for x in r['cases'] if x['scenario']=='operation_removed')
        self.assertEqual(removed['counts']['gap_counts'],{'unmapped_call':3})
        self.assertEqual(removed['coverage'],'PARTIAL')

    def test_head_burst_coalesces_duplicates_and_publishes_latest_once(self):
        r=load.run_queue(self.corpus,self.root/'burst',size=5,family='head_updates',delivery='burst')
        self.assertTrue(r['passed'])
        self.assertEqual(r['duplicates_ignored'],5)
        self.assertEqual(r['analyzed_jobs'],1)
        self.assertEqual(r['creates'],1)
        self.assertEqual(r['resources'][0]['head_sha'],self.manifest['streams']['head_updates']['5'][-1]['head_sha'])
        self.assertTrue(r['resources'][0]['latest_published'])
        self.assertEqual(r['resources'][0]['findings'],3)
        self.assertEqual(r['status']['events'],{'INGESTED':1,'COALESCED':4})

    def test_independent_burst_runs_all_prs_and_exposes_wait_and_coverage(self):
        r=load.run_queue(self.corpus,self.root/'independent',size=5,family='independent_prs',delivery='burst')
        self.assertTrue(r['passed']);self.assertEqual(r['analyzed_jobs'],5);self.assertEqual(r['creates'],5)
        self.assertEqual(len(r['queue_wait_seconds']),5)
        self.assertTrue(all(x>=0 for x in r['queue_wait_seconds']))
        self.assertTrue(all(c['coverage']=='COMPLETE_WITHIN_PROFILE' for c in r['contexts']))

    def test_sequential_updates_reuse_comment_and_survive_store_reopen(self):
        r=load.run_queue(self.corpus,self.root/'sequential',size=5,family='head_updates',delivery='sequential')
        self.assertTrue(r['passed']);self.assertEqual(r['analyzed_jobs'],5);self.assertEqual(r['creates'],1)
        self.assertGreaterEqual(r['updates'],4)
        self.assertEqual(r['resources'][0]['generation'],5)
        self.assertTrue(r['restart_checked'])

    def test_failure_is_saved_and_not_accepted_as_idle_success(self):
        r=load.run_queue(self.corpus,self.root/'limited',size=1,family='independent_prs',delivery='burst',limits={'max_corpus_bytes':1})
        self.assertFalse(r['passed'])
        self.assertTrue((self.root/'limited/result.json').exists())
        self.assertEqual(r['resources'][0]['result_status'],'FAILED')
        self.assertEqual(r['processed_fraction'],0)
        self.assertNotIn(str(self.corpus),json.dumps(r))
        with self.assertRaises(FileExistsError):
            load.run_queue(self.corpus,self.root/'limited',size=1,family='independent_prs',delivery='burst')

    def test_default_limit_reports_collection_fraction_separately_from_analysis(self):
        r=load.probe_limits(self.corpus,self.root/'probe',limits={'max_corpus_bytes':100})
        self.assertFalse(r['passed']);self.assertEqual(r['error_code'],'corpus_limit')
        self.assertEqual(r['analyzed_fraction'],0)
        self.assertLess(r['collection_fraction'],1)
        self.assertEqual(r['expected_bytes'],self.manifest['totals']['bytes'])

    def test_unexpected_worker_error_leaves_safe_failure_artifact(self):
        with patch.object(load.Service,'step',side_effect=RuntimeError('TOKEN_NEVER_EXPORT')):
            r=load.run_queue(self.corpus,self.root/'unexpected',size=1,family='independent_prs',delivery='burst')
        self.assertFalse(r['passed'])
        self.assertEqual(r['error_type'],'RuntimeError')
        self.assertNotIn('TOKEN_NEVER_EXPORT',json.dumps(r))
        self.assertTrue((self.root/'unexpected/result.json').exists())

    def test_manifest_input_can_replay_known_abstention_without_claiming_useful(self):
        inp=corpora.load_benchmark_input(self.corpus)
        event=dict(self.manifest['streams']['independent_prs']['1'][0])
        event['head_sha']=event['base_sha']
        r=load.run_queue_input(inp,[event],self.root/'abstained',expected_status='ABSTAINED',expected_findings=0,
                               expected_reason='no_supported_delta')
        self.assertTrue(r['passed'])
        self.assertEqual(r['resources'][0]['result_status'],'ABSTAINED')
        self.assertEqual(r['expectation']['findings'],0)

    def test_vm_helper_program_compiles_and_failed_transport_hides_output(self):
        from experiments.impactmap_scale import run_pilot_vm_load as vm
        from types import SimpleNamespace
        pins=dict(schema_version='impactmap-pilot-pins-1',provider_repository='r00',pr_id=4,
                  base_revisions=self.manifest['base_revisions'],head_revisions=self.manifest['base_revisions'])
        compile(vm.build_payload(pins),'vm-program','exec')
        pinfile=self.root/'pins.json';pinfile.write_text(json.dumps(pins))
        out=self.root/'vm-failed'
        with patch.object(vm.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout='TOKEN',stderr='SECRET')):
            self.assertEqual(vm.main(['--ssh-config','unused','--pins-from',str(pinfile),'--output',str(out)]),1)
        r=json.loads((out/'result.json').read_text());self.assertEqual(r,{'passed':False,'error_code':'remote_load_failed'})

    def test_recovered_latest_generation_cannot_hide_an_earlier_failed_analysis(self):
        from agent_graph.output_contracts import parse_document,dump_document
        from agent_graph.results import failed_result
        original=load.CoreAnalyzer.analyze
        calls=[]
        def fail_first(analyzer,request,**kwargs):
            calls.append(request)
            actual=original(analyzer,request,**kwargs)
            if len(calls)==1:
                return dump_document(failed_result(parse_document(request),'internal_error',
                    code_version='load-static',constitution_version=analyzer.constitution_version,correlation_id=request['request_id']))
            return actual
        with patch.object(load.CoreAnalyzer,'analyze',fail_first):
            r=load.run_queue(self.corpus,self.root/'recovered',size=5,family='head_updates',delivery='sequential')
        self.assertEqual(r['resources'][0]['result_status'],'USEFUL')
        self.assertFalse(r['passed'])
        self.assertFalse(r['all_results_expected'])

    def test_partial_access_cannot_pass_as_complete_equality(self):
        bad=self.root/'absent-corpus'
        corpora.generate_corpus(bad,repositories=5,python_lines=300)
        m=json.loads((bad/'corpus-manifest.json').read_text())
        m['policy']['repositories'][1]['root']='unavailable/r01'
        (bad/'corpus-manifest.json').write_text(json.dumps(m))
        r=load.run_graph_equivalence(bad,self.root/'partial-equality')
        self.assertFalse(r['passed'])
        self.assertTrue(any(c['coverage']=='PARTIAL' for c in r['cases']))


if __name__=='__main__':unittest.main()
