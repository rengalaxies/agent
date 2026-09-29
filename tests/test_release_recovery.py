import copy
import json
from datetime import timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest
from datamesh_release_protocol.knowledge import KnowledgeStore, KnowledgeRecord, digest
from datamesh_release_protocol.knowledge_release import KnowledgeReleaseEngine
from tests.test_knowledge import fixture,T

class ReleaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'ledger.json'
        self.store,self.old,self.new=fixture(self.path)
        self.snapshot=self.store.build_snapshot('p',self.old,self.new,T+timedelta(seconds=2))
    def reopen(self):return KnowledgeStore(list(self.store.authorities),self.path)
    def release(self,store=None,run='run',snapshot=None,seconds=4):
        return KnowledgeReleaseEngine(store or self.store).run((snapshot or self.snapshot).snapshot_id,run,T+timedelta(seconds=seconds))
    def test_restart_replays_exact_decision(self):
        original=self.release();restored=self.reopen()
        self.assertEqual(original,self.release(restored,seconds=5))
        self.assertEqual(len(restored.release_journal()),1)
    def test_multiple_engine_instances_share_runs(self):
        original=self.release();self.assertEqual(original,self.release());self.assertEqual(len(self.store.release_journal()),1)
    def test_different_runs_only_one_authorization(self):
        a=self.release();b=self.release(run='other')
        self.assertEqual(b.terminal_state,'ALREADY_COMMITTED');self.assertEqual(a.release_id,b.release_id)
        self.assertEqual(len(self.store.pending_publications()),1)
        self.assertEqual(sum(e.get('result',{}).get('terminal_state')=='COMMITTED' for e in self.store.release_journal()),1)
    def test_different_proposals_only_one_authorization(self):
        a=self.release();s=self.store.build_snapshot('another',self.old,self.new,T+timedelta(seconds=3))
        b=self.release(run='other',snapshot=s)
        self.assertEqual(b.terminal_state,'ALREADY_COMMITTED');self.assertEqual(a.release_id,b.release_id)
    def test_conflicting_target_version_abort(self):
        self.release();changed=self.new.model_copy(deep=True);changed.semantic.description='different contents'
        s=self.store.build_snapshot('other',self.old,changed,T+timedelta(seconds=3))
        result=self.release(run='other',snapshot=s)
        self.assertEqual(result.terminal_state,'ABORTED');self.assertIsNone(result.release_id)
    def test_conflicting_run_after_restart(self):
        self.release();s=self.store.build_snapshot('other',self.old,self.new,T+timedelta(seconds=3))
        with self.assertRaises(ValueError):self.release(self.reopen(),snapshot=s)
    def test_acknowledgement_survives_restart(self):
        result=self.release();self.store.acknowledge_publication(result.release_id,'receipt:1',T+timedelta(seconds=5))
        restored=self.reopen();self.assertEqual(restored.pending_publications(),[])
        self.assertEqual(self.release(restored),result)
        self.assertEqual(restored.acknowledge_publication(result.release_id,'receipt:1',T+timedelta(seconds=6)),restored.release_journal()[-1])
        with self.assertRaises(ValueError):restored.acknowledge_publication(result.release_id,'receipt:2',T+timedelta(seconds=6))
    def test_early_ack_does_not_damage_journal(self):
        r=self.release();before=self.store.release_journal()
        with self.assertRaises(ValueError):self.store.acknowledge_publication(r.release_id,'receipt',T+timedelta(seconds=3))
        self.assertEqual(self.store.release_journal(),before);self.reopen()
    def test_stale_writer_cannot_overwrite(self):
        stale=self.reopen();self.release()
        with self.assertRaises(ValueError):self.release(stale,run='other')
        self.assertEqual(len(self.reopen().release_journal()),1)
    def test_replace_failure_never_returns_commit(self):
        with patch('datamesh_release_protocol.knowledge.os.replace',side_effect=OSError('disk unavailable')):
            with self.assertRaises(OSError):self.release()
        with self.assertRaises(ValueError):self.release()
        restored=self.reopen();self.assertEqual(restored.release_journal(),[])
        self.assertEqual(self.release(restored).terminal_state,'COMMITTED')
    def test_crash_after_replace_can_recover(self):
        # File fsync succeeds; directory fsync fails after atomic replace.
        from datamesh_release_protocol import knowledge
        original=knowledge.os.fsync;count=0
        def fail_second(fd):
            nonlocal count
            count+=1
            if count==2:raise OSError('process interrupted after replace')
            return original(fd)
        with patch('datamesh_release_protocol.knowledge.os.fsync',side_effect=fail_second):
            with self.assertRaises(OSError):self.release()
        restored=self.reopen();self.assertEqual(len(restored.pending_publications()),1)
        self.assertEqual(self.release(restored).terminal_state,'COMMITTED')
    def test_corrupt_journal_rejected(self):
        self.release();p=json.loads(self.path.read_text());p['release_events'][0]['result']['decision']='REJECT'
        self.path.write_text(json.dumps(p))
        with self.assertRaises(ValueError):self.reopen()
    def test_rehashed_invalid_terminal_rejected(self):
        self.release();p=json.loads(self.path.read_text());e=p['release_events'][0];e['result']['decision']='REJECT'
        e['event_hash']=digest({k:v for k,v in e.items() if k!='event_hash'});p['integrity_hash']=digest({k:v for k,v in p.items() if k!='integrity_hash'})
        self.path.write_text(json.dumps(p))
        with self.assertRaises(ValueError):self.reopen()
    def test_defensive_journal_copy(self):
        self.release();events=self.store.release_journal();events[0]['result']['reasons'].append('fake')
        self.assertNotIn('fake',self.store.release_journal()[0]['result']['reasons'])
    def test_rejected_and_aborted_decisions_restored(self):
        self.new.semantic.formula='different';s=self.store.build_snapshot('reject',self.old,self.new,T+timedelta(seconds=3))
        r=self.release(run='reject',snapshot=s);self.assertEqual(r.terminal_state,'QUARANTINED')
        self.store.revoke_record('usage','consumer','revoked',T+timedelta(seconds=5))
        a=self.release(run='abort',seconds=6);self.assertEqual(a.terminal_state,'ABORTED')
        restored=self.reopen();self.assertEqual(self.release(restored,run='reject',snapshot=s,seconds=7),r)
        self.assertEqual(self.release(restored,run='abort',seconds=7),a)
        self.assertEqual(restored.pending_publications(),[])
    def test_invalid_attribute_cannot_prove_violation(self):
        self.store.revoke_record('attribute','producer','revoked',T+timedelta(seconds=3))
        self.new.semantic.formula='different';s=self.store.build_snapshot('review',self.old,self.new,T+timedelta(seconds=4))
        r=self.release(run='review',snapshot=s,seconds=5)
        self.assertEqual(r.terminal_state,'ESCALATED')
    def test_recovery_in_fresh_python_process(self):
        import subprocess,sys,os
        original=self.release()
        grants=Path(self.temp.name)/'grants.json';grants.write_text(json.dumps([a.model_dump(mode='json') for a in self.store.authorities]))
        code="""import json,sys
from pathlib import Path
from datetime import datetime
from datamesh_release_protocol.knowledge import Authority,KnowledgeStore
from datamesh_release_protocol.knowledge_release import KnowledgeReleaseEngine
store=KnowledgeStore([Authority.model_validate(a) for a in json.loads(Path(sys.argv[1]).read_text())],Path(sys.argv[2]))
r=KnowledgeReleaseEngine(store).run(sys.argv[3],'run',datetime.fromisoformat('2026-09-29T00:00:05+00:00'))
print(r.model_dump_json())
"""
        result=subprocess.run([sys.executable,'-c',code,str(grants),str(self.path),self.snapshot.snapshot_id],capture_output=True,text=True,check=True,timeout=15)
        self.assertEqual(json.loads(result.stdout),original.model_dump(mode='json'))
    def test_backdating_record_after_commit_forbidden(self):
        self.release()
        with self.assertRaises(ValueError):self.store.revoke_record('usage','consumer','backdate',T+timedelta(seconds=3))
    def test_journal_time_cannot_go_backwards(self):
        self.release(seconds=5)
        with self.assertRaises(ValueError):self.release(run='other',seconds=4)
        self.assertEqual(len(self.store.release_journal()),1)
    def test_rehashed_evidence_corruption_rejected(self):
        self.release();p=json.loads(self.path.read_text());e=p['release_events'][0]
        e['result']['evidence'][0]['checks']=[]
        e['event_hash']=digest({k:v for k,v in e.items() if k!='event_hash'});p['integrity_hash']=digest({k:v for k,v in p.items() if k!='integrity_hash'})
        self.path.write_text(json.dumps(p))
        with self.assertRaises(ValueError):self.reopen()
    def test_snapshot_completeness_not_self_asserted(self):
        p=json.loads(self.path.read_text());s=p['snapshots'][0];s['required_consumer_ids']=[]
        s['snapshot_id']=digest({k:v for k,v in s.items() if k not in ('snapshot_id','canonical_payload_hash')});s['canonical_payload_hash']=s['snapshot_id']
        p['integrity_hash']=digest({k:v for k,v in p.items() if k!='integrity_hash'});self.path.write_text(json.dumps(p))
        with self.assertRaises(ValueError):self.reopen()
    def test_readable_consumer_view(self):
        self.new.semantic.formula='changed';s=self.store.build_snapshot('bad',self.old,self.new,T+timedelta(seconds=3))
        r=self.release(run='bad',snapshot=s);view=r.consumer_view('risk-app')
        self.assertEqual(view['contract_change']['new_contract']['semantic']['formula'],'changed')
        self.assertTrue(any('формуле' in e['message'] for e in view['explanations']))
