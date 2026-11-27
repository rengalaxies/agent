"""Operator diagnostics: real SQLite and ASGI, no connector calls or writes."""
import json,sqlite3,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from fastapi.testclient import TestClient
from agent_service.api import create_app
from agent_service.queue import ServiceStore
from agent_service.envelope import canonical,digest
from tests.graph.test_output_contracts import request
from tests.service.helpers import orders_result

class DiagnosticTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.store=ServiceStore(Path(tmp.name)/'state.sqlite')
        self.service=SimpleNamespace(store=self.store)
        self.client=TestClient(create_app(self.service,status_token='operator'))
        self.addCleanup(self.client.close);self.auth={'Authorization':'Bearer operator'}
        self.rid='bitbucket:fixture/repo#1';self.open()
    def open(self,version='v1',closed=False,rid=None):
        return self.store.apply_snapshot(resource_id=rid or self.rid,provider='bitbucket',kind='pr',version=version,
            snapshot={'title':'PRIVATE_SNAPSHOT_DESCRIPTION','token':'PRIVATE_SNAPSHOT_SECRET'},event_id='event',closed=closed)
    def finish(self,raw=None):
        job=self.store.claim_job('worker');raw=orders_result(request()) if raw is None else raw
        doc={'title':'Full analysis','sections':[{'title':'Checks','items':['Inspect caller']} ]}
        self.store.complete_job(job,state='ANALYZED',result=raw,reason=raw.get('reason_code','incompatible_schema'),
            intent={'kind':'result','result_digest':digest(raw),'body':canonical(doc),'body_digest':digest(doc),'marker':'marker'})
        return raw
    def get(self,rid=None):return self.client.get('/result',params={'resource_id':rid or self.rid},headers=self.auth)
    def dump(self):
        c=sqlite3.connect(self.store.path)
        try:return '\n'.join(c.iterdump())
        finally:c.close()
    def test_auth_precedes_input_validation_and_missing_token_fails_closed(self):
        for path in ('/resources?limit=bad','/result','/result?resource_id=x'):
            for headers in ({},{'Authorization':'Bearer wrong'}):
                self.assertEqual(self.client.get(path,headers=headers).status_code,401)
        client=TestClient(create_app(self.service));self.addCleanup(client.close)
        self.assertEqual(client.get('/resources',headers=self.auth).status_code,401)
    def test_non_ascii_authorization_is_rejected_without_server_error(self):
        self.assertEqual(self.client.get('/status',headers={b'authorization':b'Bearer \xff'}).status_code,401)
    def test_delivered_analysis_is_selected_with_safe_metadata_and_no_store(self):
        raw=self.finish()
        with self.store._tx() as c:
            c.execute("UPDATE jobs SET state='DONE'")
            c.execute("UPDATE intents SET state='DELIVERED',receipt=?",(json.dumps({'Authorization':'PRIVATE_HTTP_RECEIPT'}),))
        before=self.dump();response=self.get();self.assertEqual(response.status_code,200);data=response.json()
        self.assertEqual(data['schema'],'impactmap-diagnostics-1')
        self.assertEqual(data['analysis']['raw'],raw);self.assertEqual(data['analysis']['freshness'],'CURRENT')
        self.assertEqual(data['publication']['state'],'DELIVERED');self.assertEqual(data['document']['title'],'Full analysis')
        self.assertEqual(data['current_job']['state'],'DONE');self.assertEqual(response.headers['cache-control'],'no-store')
        self.assertEqual(before,self.dump())
        for secret in ('PRIVATE_SNAPSHOT','PRIVATE_HTTP_RECEIPT','Authorization'):self.assertNotIn(secret,response.text)
    def test_new_generation_marks_previous_output_stale_with_current_job(self):
        self.finish();self.open('v2');data=self.get().json()
        self.assertEqual(data['resource']['generation'],2);self.assertEqual(data['current_job']['state'],'QUEUED')
        self.assertEqual(data['analysis']['generation'],1);self.assertEqual(data['analysis']['freshness'],'STALE')
    def test_failed_current_job_does_not_present_old_success_as_current(self):
        self.finish();self.open('v2');job=self.store.claim_job('worker')
        self.store.complete_job(job,state='FAILED',result=None,intent=None,reason='commit_unavailable')
        data=self.get().json();self.assertEqual(data['current_job']['reason'],'commit_unavailable')
        self.assertEqual(data['current_job']['state'],'FAILED');self.assertEqual(data['analysis']['freshness'],'STALE')
    def test_current_failed_analysis_is_visible_instead_of_older_useful(self):
        self.finish();self.open('v2');raw=orders_result(request());raw.update(status='FAILED',reason_code='commit_unavailable',affected=[],claims=[],deltas=[],checks=[],relationships=[],evidence=[],impact_paths=[])
        self.finish(raw);data=self.get().json()
        self.assertEqual(data['analysis']['generation'],2);self.assertEqual(data['analysis']['raw']['status'],'FAILED')
        self.assertEqual(data['analysis']['freshness'],'CURRENT')
    def test_closed_and_same_version_rebuild_are_explicit(self):
        self.finish();self.store.reopen_open_resources(reason='core_changed',event_id='refresh',providers={'bitbucket'})
        self.assertEqual(self.get().json()['analysis']['freshness'],'STALE')
        self.open('v1',closed=True);self.assertTrue(self.get().json()['resource']['closed'])
        self.assertEqual(self.get().json()['analysis']['freshness'],'CLOSED')
    def test_no_result_and_unknown_or_traversal_ids_never_read_a_file(self):
        data=self.get().json();self.assertIsNone(data['analysis']);self.assertEqual(data['current_job']['state'],'QUEUED')
        for rid in ('unknown','../../etc/passwd',self.rid+"' OR 1=1 --"):
            self.assertEqual(self.get(rid).status_code,404)
        for params in ({},{'resource_id':''},{'resource_id':'x'*513}):
            self.assertEqual(self.client.get('/result',params=params,headers=self.auth).status_code,400)
    def test_untrusted_incompatible_raw_is_not_exposed_as_analysis(self):
        self.finish({'reason_code':'alien','secret':'PRIVATE_RAW_SECRET'})
        data=self.get().json();self.assertFalse(data['analysis']['compatible']);self.assertIsNone(data['analysis']['raw'])
        self.assertNotIn('PRIVATE_RAW_SECRET',self.get().text)
    def test_resource_listing_is_bounded_and_does_not_include_snapshot(self):
        for i in range(3):self.open(rid='bitbucket:other#'+str(i))
        before=self.dump();response=self.client.get('/resources',params={'limit':'2'},headers=self.auth)
        self.assertEqual(response.status_code,200);data=response.json();self.assertEqual(len(data['items']),2);self.assertTrue(data['has_more'])
        self.assertEqual(before,self.dump());self.assertNotIn('PRIVATE_SNAPSHOT',response.text)
        for limit in ('0','101','-1','true','1.2'):
            self.assertEqual(self.client.get('/resources',params={'limit':limit},headers=self.auth).status_code,400)
    def test_other_resources_cannot_change_a_selected_result(self):
        self.finish();self.open(rid='bitbucket:other#2');data=self.get().json()
        self.assertEqual(data['resource']['resource_id'],self.rid);self.assertEqual(data['analysis']['generation'],1)
        self.assertEqual(self.client.post('/result',headers=self.auth).status_code,405)
