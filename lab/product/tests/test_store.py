import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from lab.product.store import Store
from lab.product.worker import Worker
from lab.runtime.core import Stop

ROOT=Path(__file__).resolve().parents[3]

def change(revision=1,**kw):return dict(change_id='test',revision=revision,title='Unit change',intent='Change amount semantics',proposed_diff='--- a/lab/sql/expand.sql\n+++ b/lab/sql/expand.sql\n-old\n+bad',proposed_files={},source_commit='test-source',**kw)

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.db=Path(self.temp.name)/'state.db';self.s=Store(self.db)
        self.s.create_change(change());self.basis='first';self.w=Worker(self.s,Path(self.temp.name)/'artifacts',ROOT,collector=lambda:{'mode':'LIVE RUN','basis_digest':self.basis,'edges':[],'coverage_gaps':['test collector only']})
    def tearDown(self):self.temp.cleanup()
    def job(self,op,mode='FIXTURE / CONTROL',key=None):
        j=self.s.enqueue(dict(change_id='test',operation=op,mode=mode,idempotency_key=key or str(len(self.s.rows('jobs')))));self.w.run_once();return self.s.entity('jobs',j['id'])
    def snapshot(self):self.assertEqual(self.job('snapshot','LIVE RUN')['status'],'SUCCEEDED')
    def test_addressed_cards_and_exact_decision(self):
        self.snapshot();self.assertEqual(self.job('analysis')['status'],'SUCCEEDED')
        cards=self.s.rows('cards');self.assertEqual({c['team'] for c in cards},{'billing','analytics'})
        c=cards[0];d=self.s.decide(dict(card_id=c['id'],revision=1,assessment_digest=c['assessment_digest'],team=c['team'],actor='demo',decision='acknowledged'))
        self.assertFalse(d['grants_execution']);self.assertTrue(c['grounds'])
        self.s.create_change(change(2));self.assertFalse(self.s.rows('decisions')[0]['current']);self.assertTrue(all(not x['current'] for x in self.s.rows('cards')))
        with self.assertRaises(Stop):self.s.decide(dict(card_id=c['id'],revision=1,assessment_digest=c['assessment_digest'],team=c['team'],actor='demo',decision='reviewed'))
    def test_snapshot_basis_invalidates(self):
        self.snapshot();self.job('analysis');self.snapshot();self.assertTrue(self.s.rows('assessments')[0]['current'])
        self.basis='changed binding';self.snapshot();self.assertFalse(self.s.rows('assessments')[0]['current'])
    def test_late_analysis_stays_history(self):
        self.snapshot();original=self.w.execute
        def late(j,c):
            self.s.create_change(change(2));return original(j,c)
        self.w.execute=late;self.job('analysis');self.assertFalse(self.s.rows('assessments')[0]['current']);self.assertTrue(all(not x['current'] for x in self.s.rows('cards')))
    def test_restart_unknown_and_idempotency(self):
        p=dict(change_id='test',operation='snapshot',mode='LIVE RUN',idempotency_key='same')
        j=self.s.enqueue(p);self.assertEqual(j['id'],self.s.enqueue(p)['id'])
        with self.assertRaises(Stop):self.s.enqueue({**p,'operation':'analysis'})
        with self.s.transaction():j['status']='RUNNING';self.s.put('jobs',j)
        recovered=Store(self.db);self.assertEqual(recovered.rows('jobs')[0]['status'],'UNKNOWN');self.assertEqual(len(recovered.rows('changes')),1)
    def test_client_safe_flag_does_not_bypass(self):
        self.s.create_change(change(2,kind='safe'));self.snapshot();self.job('analysis');self.assertEqual(len([c for c in self.s.rows('cards') if c['current']]),2)
    def test_unknown_owner_coordinator(self):
        self.snapshot()
        from lab.runtime.inbox import collect
        evidence=collect(ROOT,'test-source')
        for item in evidence:item['owner']='UNKNOWN'
        with patch('lab.product.worker.inbox.collect',return_value=evidence):self.job('analysis')
        self.assertEqual({c['team'] for c in self.s.rows('cards')},{'COORDINATOR'})
        self.assertEqual(self.s.rows('cards')[0]['status'],'заблокировано')
    def test_submitted_source_overrides_reference(self):
        c=change();c['proposed_files']={'lab/sql/expand.sql':'WRONG SQL'}
        discovery=self.w.model_discovery(c)
        self.assertEqual(next(x['content'] for x in discovery['evidence'] if x['object_ref']=='lab/sql/expand.sql'),'WRONG SQL')
    def test_live_missing_credential_blocks_no_fixture_fallback(self):
        self.snapshot()
        with patch.dict('os.environ',{'CLOUDRU_FOUNDATION_API_KEY':'','CLOUDRU_LLM_MODEL':''}):j=self.job('analysis','LIVE RUN')
        self.assertEqual(j['status'],'BLOCKED');self.assertEqual(self.s.rows('assessments'),[])
    def test_docs_only_supported_profile(self):
        c=change(2,kind='safe');c.update(proposed_diff='--- a/docs/note.md\n+++ b/docs/note.md\n-old\n+new',proposed_files={'docs/note.md':'new'})
        self.s.create_change(c);self.snapshot();self.job('analysis');self.assertEqual(self.s.rows('assessments')[-1]['classification'],'SUPPORTED_DOCS_ONLY');self.assertEqual(len(self.s.rows('cards')),0)

    def test_superseded_snapshot_not_current(self):
        self.snapshot();self.basis='new-binding';self.snapshot()
        self.assertFalse(self.s.rows('snapshots')[0]['current']);self.assertTrue(self.s.rows('snapshots')[1]['current'])

if __name__=='__main__':unittest.main()
