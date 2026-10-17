from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from datamesh_release_protocol.knowledge import Authority, KnowledgeRecord, KnowledgeStore
from datamesh_release_protocol.knowledge_release import KnowledgeReleaseEngine
from datamesh_release_protocol.models import DataContract, Decision
T=datetime(2026,9,29,tzinfo=timezone.utc)

def fixture(path=None):
    grants=[Authority(actor=a,domain=d,kinds=k,authority_ref='grant:'+a) for a,d,k in [
        ('producer','sales',['team','product','attribute']),('consumer','risk',['team','usage','obligation']),
        ('registry','federation',['coverage','constitution','global_rule'])]]
    store=KnowledgeStore(grants,path)
    old=DataContract(product_id='active-users',contract_version='1',owner_domain='sales',schema_fields={'active':'bool'},semantic=dict(meaning='active',formula='purchases_30d > 0',unit='bool',identity_scope='person',allowed_sources=['crm'],purposes=['risk']))
    new=old.model_copy(deep=True);new.contract_version='2'
    entries=[
        ('pt','team','sales','producer',dict(team_id='p',domain_id='sales',authority_ref='grant:producer')),
        ('ct','team','risk','consumer',dict(team_id='c',domain_id='risk',authority_ref='grant:consumer')),
        ('product','product','sales','producer',dict(product_id=old.product_id,producer_team_ref='pt',contract=old.model_dump(mode='json'))),
        ('attribute','attribute','sales','producer',dict(product_id=old.product_id,field_path='active',semantic_profile_ref='semantic:1',contract_version='1')),
        ('usage','usage','risk','consumer',dict(consumer_id='risk-app',consumer_team_ref='ct',product_id=old.product_id,field_paths=['active'],purpose='risk',calculation_ref='calc:1',registration_ref='registry:1')),
        ('obligation','obligation','risk','consumer',dict(usage_ref='usage',requirement=dict(obligation_id='risk-obligation',obligation_version='1',consumer_id='risk-app',consumer_domain='risk',product_id=old.product_id,required_formula=old.semantic.formula))),
        ('coverage','coverage','federation','registry',dict(product_id=old.product_id,membership_epoch=1,registered_consumer_ids=['risk-app'],registry_evidence_ref='registry:1',registration_boundary='registered subscriptions',authority_ref='grant:registry')),
        ('constitution','constitution','federation','registry',dict(product_id=old.product_id,constitution_ref='constitution:1',constitution_version='1',content_hash='abc'))]
    for rid,kind,domain,actor,data in entries:
        store.propose_record(KnowledgeRecord(record_id=rid,version=1,kind=kind,owner_domain=domain,evidence_ref='source:1',valid_from=T,data=data),actor,T)
        store.confirm_record(rid,actor,'confirmation:1',T+timedelta(seconds=1))
    return store,old,new

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.store,self.old,self.new=fixture()
    def snap(self,seconds=2):
        return self.store.build_snapshot('proposal',self.old,self.new,T+timedelta(seconds=seconds))
    def run_release(self,s=None):
        return KnowledgeReleaseEngine(self.store).run((s or self.snap()).snapshot_id,'run',T+timedelta(seconds=4))
    def test_accept_views(self):
        s=self.snap();s.verify();self.assertEqual(s.completeness,'complete')
        r=self.run_release(s);self.assertEqual(r.terminal_state,'COMMITTED');self.assertIsNotNone(r.release_id)
        self.assertEqual(r.consumer_view('risk-app')['affected'][0]['field_paths'],['active'])
    def test_semantic_reject(self):
        self.new.semantic.formula='sessions_30d > 0';self.assertEqual(self.run_release().decision,Decision.REJECT)
    def test_schema_reject(self):
        self.new.schema_fields={'other':'bool'};self.assertEqual(self.run_release().decision,Decision.REJECT)
    def test_revoked_coverage_review(self):
        self.store.revoke_record('coverage','registry','revoked',T+timedelta(seconds=2))
        self.assertEqual(self.run_release().decision,Decision.NEEDS_REVIEW)
    def test_commit_fence(self):
        s=self.snap();self.store.revoke_record('obligation','consumer','revoked',T+timedelta(seconds=3))
        r=self.run_release(s);self.assertEqual(r.terminal_state,'ABORTED');self.assertIsNone(r.release_id)
        self.store.resolve_snapshot(s.snapshot_id).verify()
    def test_authority(self):
        with self.assertRaises(PermissionError):self.store.confirm_record('obligation','producer','fake',T+timedelta(seconds=2))
    def test_idempotent_conflict(self):
        e=KnowledgeReleaseEngine(self.store);s=self.snap();a=e.run(s.snapshot_id,'run',T+timedelta(seconds=3))
        self.assertEqual(a,e.run(s.snapshot_id,'run',T+timedelta(seconds=4)))
        self.new.semantic.formula='different'
        with self.assertRaises(ValueError):e.run(self.snap().snapshot_id,'run',T+timedelta(seconds=4))
    def test_defensive_copy_history_impact(self):
        s=self.snap();s.records[0].data.clear();self.store.resolve_snapshot(s.snapshot_id).verify()
        self.store.revoke_record('usage','consumer','revoked',T+timedelta(seconds=3))
        self.assertEqual(self.snap().completeness,'complete')
        self.assertTrue(self.store.list_impact(self.old.product_id,['active'],T+timedelta(seconds=2)))
        self.assertFalse(self.store.list_impact(self.old.product_id,['unrelated'],T+timedelta(seconds=2)))
    def test_persistence_tamper(self):
        with TemporaryDirectory() as d:
            path=Path(d)/'ledger.json';store,old,new=fixture(path);s=store.build_snapshot('p',old,new,T+timedelta(seconds=2))
            KnowledgeStore(list(store.authorities),path).resolve_snapshot(s.snapshot_id).verify()
            p=json.loads(path.read_text());p['events'][0]['actor']='intruder';path.write_text(json.dumps(p))
            with self.assertRaises(ValueError):KnowledgeStore(list(store.authorities),path)
    def test_tampered_snapshot(self):
        s=self.snap();s.required_consumer_ids=[]
        with self.assertRaises(ValueError):s.verify()
    def test_naive_time(self):
        with self.assertRaises(ValueError):self.store.build_snapshot('p',self.old,self.new,datetime(2026,9,29))
    def test_candidate_review(self):
        prior=self.store._records['obligation'][-1]
        r=KnowledgeRecord.model_validate({**prior.model_dump(),'version':3,'status':'candidate','confirmed_by':None,'valid_from':T+timedelta(seconds=2)})
        self.store.propose_record(r,'consumer',T+timedelta(seconds=2));self.assertEqual(self.run_release().decision,Decision.NEEDS_REVIEW)
    def test_expired_usage_review(self):
        prior=self.store._records['usage'][-1]
        r=KnowledgeRecord.model_validate({**prior.model_dump(),'version':3,'status':'candidate','confirmed_by':None,'valid_from':T+timedelta(seconds=2),'valid_until':T+timedelta(seconds=3)})
        self.store.propose_record(r,'consumer',T+timedelta(seconds=2));self.assertNotEqual(self.snap(4).completeness,'complete')

class KnowledgeNegativeTests(unittest.TestCase):
    setUp = KnowledgeTests.setUp
    def change(self,rid,actor,update):
        prior=self.store._records[rid][-1]
        r=KnowledgeRecord.model_validate({**prior.model_dump(),'version':prior.version+1,'status':'candidate','confirmed_by':None,'valid_from':T+timedelta(seconds=2),'data':{**prior.data,**update}})
        self.store.propose_record(r,actor,T+timedelta(seconds=2));self.store.confirm_record(rid,actor,'changed',T+timedelta(seconds=3))
    def snap(self,seconds=4):return KnowledgeTests.snap(self,seconds)
    def run_release(self,s=None):return KnowledgeReleaseEngine(self.store).run((s or self.snap()).snapshot_id,'run',T+timedelta(seconds=5))
    def test_dangling_usage(self):
        self.change('obligation','consumer',{'usage_ref':'absent'})
        self.assertIn('dangling_usage:obligation',self.snap().issues);self.assertEqual(self.run_release().decision,Decision.NEEDS_REVIEW)
    def test_wrong_consumer_domain(self):
        requirement={**self.store._records['obligation'][-1].data['requirement'],'consumer_domain':'sales'}
        self.change('obligation','consumer',{'requirement':requirement})
        self.assertEqual(self.run_release().decision,Decision.NEEDS_REVIEW)
    def test_missing_attribute(self):
        self.change('usage','consumer',{'field_paths':['missing']})
        self.assertEqual(self.run_release().decision,Decision.NEEDS_REVIEW)
    def test_candidate_team_cannot_supply_proof(self):
        prior=self.store._records['ct'][-1]
        r=KnowledgeRecord.model_validate({**prior.model_dump(),'version':3,'status':'candidate','confirmed_by':None,'valid_from':T+timedelta(seconds=2)})
        self.store.propose_record(r,'consumer',T+timedelta(seconds=2));self.new.semantic.formula='different'
        self.assertEqual(self.run_release().decision,Decision.NEEDS_REVIEW)
    def test_registration_mismatch(self):
        self.change('coverage','registry',{'registered_consumer_ids':['unseen']})
        self.assertEqual(self.run_release().decision,Decision.NEEDS_REVIEW)
    def test_global_rule(self):
        req=dict(obligation_id='federation-rule',obligation_version='1',consumer_id='federation',consumer_domain='federation',product_id=self.old.product_id,required_formula='different')
        r=KnowledgeRecord(record_id='rule',version=1,kind='global_rule',owner_domain='federation',evidence_ref='rule:1',valid_from=T+timedelta(seconds=2),data=dict(product_id=self.old.product_id,rule_id='r',rule_version='1',predicate=req))
        self.store.propose_record(r,'registry',T+timedelta(seconds=2));self.store.confirm_record('rule','registry','approved',T+timedelta(seconds=3))
        self.assertEqual(self.run_release().decision,Decision.REJECT)
    def test_conflicting_obligation_ids_review(self):
        prior=self.store._records['obligation'][-1]
        r=KnowledgeRecord.model_validate({**prior.model_dump(),'record_id':'other-obligation','version':1,'status':'candidate','confirmed_by':None,'valid_from':T+timedelta(seconds=2)})
        self.store.propose_record(r,'consumer',T+timedelta(seconds=2));self.store.confirm_record(r.record_id,'consumer','approved',T+timedelta(seconds=3))
        self.assertEqual(self.run_release().decision,Decision.NEEDS_REVIEW)
    def test_contract_expiry_before_commit(self):
        prior=self.store._records['product'][-1]
        r=KnowledgeRecord.model_validate({**prior.model_dump(),'version':3,'status':'candidate','confirmed_by':None,'valid_from':T+timedelta(seconds=2),'valid_until':T+timedelta(seconds=5)})
        self.store.propose_record(r,'producer',T+timedelta(seconds=2));self.store.confirm_record('product','producer','approved',T+timedelta(seconds=3))
        s=self.snap();self.assertEqual(s.completeness,'complete')
        self.assertEqual(self.run_release(s).terminal_state,'ABORTED')
