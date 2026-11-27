"""Read-only projections require trusted scope receipts, including stale generations."""
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from agent_service.queue import ServiceStore
from agent_service.ui_scope import UIScope
from agent_service.envelope import canonical,digest
from tests.graph.test_output_contracts import request,result


class ScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=ServiceStore(Path(self.tmp.name)/'service.sqlite')
        self.scope=UIScope('acme','prod','6'*64,('orders','reporting'),(),str(self.store.path.resolve()))
        self.rid='bitbucket:fixture#1';self.open()

    def open(self,version='v1',rid=None):
        self.store.apply_snapshot(resource_id=rid or self.rid,provider='bitbucket',kind='pr',version=version,
            snapshot={'title':'PRIVATE_UNPROJECTED_TITLE','password':'PRIVATE_SNAPSHOT'},event_id='event',closed=False)

    def claim(self,stamp=True,scope=None):
        job=self.store.claim_job('worker')
        if stamp:
            req=request();req.update((scope or self.scope).receipt())
            req['repository_revisions']={k:v for k,v in req['repository_revisions'].items()
                                         if k in req['access_scope']['repositories']}
            self.assertTrue(self.store.stamp_ui_scope(job,req))
        return job

    def finish(self,raw=None,stamp=True,scope=None):
        job=self.claim(stamp,scope);raw=result() if raw is None else raw
        doc={'title':'PRIVATE_PUBLISHER_DOCUMENT','receipt':'PRIVATE_HTTP_SECRET'}
        self.store.complete_job(job,state='ANALYZED',result=raw,reason=raw.get('reason_code'),
            intent={'kind':'result','result_digest':digest(raw),'body':canonical(doc),'body_digest':digest(doc),'marker':'m'})
        return job

    def get(self):return self.store.ui_result(self.scope,self.rid)

    def test_legacy_jobs_cannot_be_inferred_authorized_from_raw_alone(self):
        self.finish(stamp=False)
        self.assertIsNone(self.get());self.assertEqual(self.store.ui_listing(self.scope)['items'],[])

    def test_scope_receipt_allows_valid_result_without_private_documents(self):
        self.finish();data=self.get()
        self.assertEqual(data['analysis']['freshness'],'CURRENT')
        self.assertEqual(data['analysis']['result']['status'],'USEFUL')
        self.assertNotIn('raw',data['analysis']);self.assertNotIn('document',data)
        self.assertNotIn('PRIVATE_',json.dumps(data))
        items=self.store.ui_listing(self.scope)['items'];self.assertEqual(items[0]['resource_id'],self.rid)

    def test_other_installation_environment_view_or_grants_return_nothing(self):
        self.finish()
        for scope in [UIScope('other','prod','6'*64,('orders','reporting'),(),self.scope.database),
                      UIScope('acme','stage','6'*64,('orders','reporting'),(),self.scope.database),
                      UIScope('acme','prod','7'*64,('orders','reporting'),(),self.scope.database),
                      UIScope('acme','prod','6'*64,('orders',),(),self.scope.database)]:
            self.assertIsNone(self.store.ui_result(scope,self.rid))
            self.assertEqual(self.store.ui_listing(scope)['items'],[])

    def test_new_unstamped_generation_hides_prior_result_and_metadata(self):
        self.finish();self.open('v2')
        self.assertIsNone(self.get());self.assertEqual(self.store.ui_listing(self.scope)['items'],[])

    def test_failed_current_scope_keeps_authorized_previous_result_stale(self):
        self.finish();self.open('v2');job=self.claim()
        self.store.complete_job(job,state='FAILED',result=None,reason='commit_unavailable',intent=None)
        data=self.get();self.assertEqual(data['current_job']['state'],'FAILED')
        self.assertEqual(data['analysis']['freshness'],'STALE')

    def test_old_broader_scope_hidden_even_after_new_current_scope_is_stamped(self):
        self.finish();self.open('v2')
        narrowed=UIScope('acme','prod','7'*64,('orders',),(),self.scope.database)
        job=self.claim(scope=narrowed)
        self.store.complete_job(job,state='FAILED',result=None,reason='commit_unavailable',intent=None)
        self.assertIsNone(self.store.ui_result(narrowed,self.rid))

    def test_incompatible_payload_is_not_returned(self):
        self.finish({'schema_version':'alien','reason_code':'invalid','secret':'PRIVATE_RAW'})
        data=self.get();self.assertFalse(data['analysis']['compatible'])
        self.assertIsNone(data['analysis']['result']);self.assertNotIn('PRIVATE_RAW',json.dumps(data))

    def test_structurally_valid_foreign_output_does_not_leak_via_listing(self):
        raw=result();raw['installation_id']='other'
        self.finish(raw);self.assertIsNone(self.get());self.assertEqual(self.store.ui_listing(self.scope)['items'],[])

    def test_out_of_scope_evidence_is_denied_wholly(self):
        raw=result();raw['evidence'][0]['repository']='secret-repo'
        self.finish(raw);self.assertIsNone(self.get())

    def test_receipt_requires_current_lease_and_read_does_not_change_service_database(self):
        job=self.claim();self.open('v2')
        self.assertFalse(self.store.stamp_ui_scope(job,request()))
        current=self.claim();self.store.complete_job(current,state='FAILED',result=None,reason='none',intent=None)
        def dump():
            c=sqlite3.connect(self.store.path)
            try:return '\n'.join(c.iterdump())
            finally:c.close()
        before=dump();self.store.ui_listing(self.scope);self.get();self.assertEqual(before,dump())

    def test_scope_bound_listing_is_bounded(self):
        self.finish()
        for n in range(3):self.open(rid=f'bitbucket:other#{n}');self.finish()
        data=self.store.ui_listing(self.scope,2)
        self.assertEqual(len(data['items']),2);self.assertTrue(data['has_more'])
        self.assertEqual(data['coverage'],'STAMPED_SCOPE_ONLY')
        self.assertIsNone(self.store.ui_result(self.scope,'../../private'))
        for value in (0,101,True):
            with self.assertRaises(ValueError):self.store.ui_listing(self.scope,value)
