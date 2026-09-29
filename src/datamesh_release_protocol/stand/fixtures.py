"""Synthetic E4 fixtures; no imports from evaluation catalog or scoring labels."""
import json
from datetime import datetime,timezone,timedelta
from pathlib import Path
from ..knowledge import Authority,KnowledgeRecord,KnowledgeStore
from ..models import DataContract

T=datetime(2026,9,29,tzinfo=timezone.utc)
ROUTES={'sales':'sales','risk':'risk','analytics':'analytics','federation':'sales'}


def catalog(path=None):
    grants=[Authority(actor=a,domain=d,kinds=k,authority_ref='grant:'+a) for a,d,k in [
        ('producer','sales',['team','product','attribute']),('risk-owner','risk',['team','usage','obligation']),
        ('analytics-owner','analytics',['team','usage','obligation']),('registry','federation',['coverage','constitution','global_rule'])]]
    store=KnowledgeStore(grants,path,domain_routes=ROUTES)
    snapshots={}
    for outcome in ('ACCEPT','REJECT','NEEDS_REVIEW','INDEPENDENT'):
        product='e4-'+outcome.lower();prefix=product+':'
        old=DataContract(product_id=product,contract_version='1',owner_domain='sales',schema_fields={'active':'bool'},
            semantic=dict(meaning='active',formula='purchases_30d > 0',unit='bool',identity_scope='person',allowed_sources=['crm'],purposes=['risk']))
        new=old.model_copy(deep=True);new.contract_version='2'
        if outcome=='REJECT':new.semantic.formula='sessions_30d > 0'
        consumers=[('risk-app','risk','risk-owner')]
        if outcome!='INDEPENDENT':consumers.append(('analytics-app','analytics','analytics-owner'))
        entries=[('producer-team','team','sales','producer',dict(team_id=prefix+'producer',domain_id='sales',authority_ref='grant:producer')),
            ('product','product','sales','producer',dict(product_id=product,producer_team_ref=prefix+'producer-team',contract=old.model_dump(mode='json'))),
            ('attribute','attribute','sales','producer',dict(product_id=product,field_path='active',semantic_profile_ref=prefix+'semantic:1',contract_version='1')),
            ('coverage','coverage','federation','registry',dict(product_id=product,membership_epoch=1,registered_consumer_ids=[c[0] for c in consumers],registry_evidence_ref=prefix+'registry:1',registration_boundary='registered synthetic consumers',authority_ref='grant:registry')),
            ('constitution','constitution','federation','registry',dict(product_id=product,constitution_ref=prefix+'constitution',constitution_version='1',content_hash='synthetic-constitution-1'))]
        for cid,domain,actor in consumers:
            requirement=dict(obligation_id=prefix+cid,obligation_version='1',consumer_id=cid,consumer_domain=domain,product_id=product)
            if outcome!='NEEDS_REVIEW' or domain!='risk':requirement['required_formula']=old.semantic.formula
            entries.extend([(domain+'-team','team',domain,actor,dict(team_id=prefix+domain,domain_id=domain,authority_ref='grant:'+actor)),
                (domain+'-usage','usage',domain,actor,dict(consumer_id=cid,consumer_team_ref=prefix+domain+'-team',product_id=product,field_paths=['active'],purpose='risk',calculation_ref=prefix+'calc',registration_ref=prefix+'registry',active=True)),
                (domain+'-obligation','obligation',domain,actor,dict(usage_ref=prefix+domain+'-usage',requirement=requirement))])
        for rid,kind,domain,actor,data in entries:
            store.propose_record(KnowledgeRecord(record_id=prefix+rid,version=1,kind=kind,owner_domain=domain,evidence_ref=prefix+'source',valid_from=T,data=data),actor,T)
            store.confirm_record(prefix+rid,actor,prefix+'confirmation',T+timedelta(seconds=1))
        snapshots[outcome]=store.build_snapshot('proposal:'+product,old,new,T+timedelta(seconds=2))
    return store,snapshots
