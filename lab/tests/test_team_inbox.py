import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from lab.runtime.core import Stop
from lab.runtime.inbox import assess, decide, load, replay

ROOT=Path(__file__).resolve().parents[2]

class TeamInboxTests(unittest.TestCase):
    def setUp(self):
        self.replay=replay(ROOT);self.change=copy.deepcopy(self.replay['input']);self.store=load('/tmp/nonexistent-team-inbox-test-store')
    def assess(self,**kwargs):return assess(self.store,self.change,ROOT,'orders-owner','stand-coordinator',**kwargs)
    def active(self):return [c for c in self.store['cards'] if c['active']]
    def test_breaking_change_addressed_with_source_and_replay(self):
        self.assess();self.assertEqual({c['team'] for c in self.active()},{'billing','analytics'})
        for card in self.active():
            self.assertTrue(card['grounds']);self.assertTrue(card['next_action']);self.assertTrue(card['next_action_owner'])
            self.assertEqual(card['risk']['status'],'INFERRED_RISK')
            self.assertEqual(card['reproduction']['status'],'REPLAY_BROKEN_MIGRATION_REJECTED')
            self.assertEqual(card['independent_verification']['status'],'PASS_IN_HISTORICAL_REPLAY')
            self.assertEqual(card['status'],'проверено');self.assertFalse(card['execution_permission'])
            self.assertTrue(all(g['source_fragment'] and g['line'] and g['owner_origin']=='DECLARED_CATALOG_NOT_AUTO_DISCOVERY' for g in card['grounds']))
    def test_unknown_owner_routes_only_to_coordinator(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';shutil.copytree(self.replay['source'],source)
            p=source/'lab/catalog/owners.json';owners=json.loads(p.read_text())
            owners['bindings']=[b for b in owners['bindings'] if b.get('object_ref')!='lab/app/service.py#consume'];p.write_text(json.dumps(owners))
            self.assess(source=source)
        self.assertEqual({c['team'] for c in self.active()},{'COORDINATOR','analytics'})
        card=next(c for c in self.active() if c['team']=='COORDINATOR')
        self.assertEqual(card['responsible'],'stand-coordinator');self.assertEqual(card['status'],'заблокировано')
        self.assertEqual(card['grounds'][0]['owner'],'UNKNOWN')
        self.assertFalse(any(n['external_sent'] for n in self.store['local_notifications']))
    def test_revision_invalidates_decisions_without_duplicate_notifications(self):
        self.assess();card=self.active()[0]
        decide(self.store,card['card_id'],1,card['assessment_digest'],card['team'],'declared-reviewer','acknowledged')
        self.assertFalse(self.store['decisions'][0]['grants_execution']);self.assertFalse(self.store['execution_permission'])
        before=copy.deepcopy(self.store);self.assess();self.assertEqual(self.store,before)
        self.change['revision']=2;self.assess()
        self.assertEqual(len(self.store['cards']),4);self.assertEqual(len(self.store['local_notifications']),4)
        self.assertEqual(len({n['notification_id'] for n in self.store['local_notifications']}),4)
        self.assertTrue(all(c['status']=='устарело' for c in self.store['cards'] if c['revision']==1))
        self.assertFalse(self.store['decisions'][0]['valid'])
        self.assertTrue(all(c['independent_verification']['status']=='NOT_RUN_FOR_THIS_REVISION' and c['status']=='требуется решение' for c in self.active()))
        with self.assertRaises(Stop):decide(self.store,card['card_id'],1,card['assessment_digest'],card['team'],'reviewer','reviewed')
        before=copy.deepcopy(self.store);self.assess();self.assertEqual(self.store,before)
    def test_changed_input_same_revision_and_wrong_team_are_rejected(self):
        self.assess();card=self.active()[0]
        with self.assertRaises(Stop):decide(self.store,card['card_id'],1,card['assessment_digest'],'wrong-team','a','reviewed')
        self.change['intent']+=' changed'
        with self.assertRaises(Stop):self.assess()
    def test_changed_code_cannot_borrow_historical_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'source';shutil.copytree(self.replay['source'],source)
            p=source/'lab/app/service.py';p.write_text(p.read_text()+'\n# changed local source\n')
            self.assess(source=source)
            self.assertTrue(all(c['independent_verification']['status']=='NOT_RUN_FOR_THIS_REVISION' for c in self.active()))
            self.assertTrue(all(g['source_commit']=='UNVERIFIED_LOCAL_SOURCE_NOT_REPLAY_COMMIT' for c in self.active() for g in c['grounds']))
