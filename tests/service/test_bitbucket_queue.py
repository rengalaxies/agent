"""Real HTTP PR reads -> durable queue, with Jira/GitHub processing still active."""
import json
import unittest

from pydantic import ValidationError

from agent_service.config import build
from agent_service.connectors.base import ResourceNotAllowed
from agent_service.service import Service, _kind
from agent_service.analysis import NotWiredAnalyzer
from agent_service.publisher import DirectorySink
from tests.service import test_bitbucket_probe as probe_fixture
from tests.service import test_bitbucket_read as read_fixture
from tests.service import helpers

RID = 'bitbucket:11111111-1111-1111-1111-111111111111/22222222-2222-2222-2222-222222222222#7'


class QueueTest(unittest.TestCase):
    def setUp(self):
        self.fixture = probe_fixture.ProbeTest()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.fixture.document['bitbucket']['mode'] = 'queue_only'
        self.fixture.document['state_path'] = str(self.fixture.root/'queue.sqlite')
        self.pr = read_fixture.pull_request()
        self.fixture.routes[read_fixture.PINNED+'/pullrequests'] = {'values':[self.pr]}
        self.fixture.routes[read_fixture.PINNED+'/pullrequests/7'] = self.pr

    def service(self):
        try:
            cfg = self.fixture.config()
        except ValidationError:
            self.fail('Bitbucket queue_only mode is not implemented')
        store, connectors, backends = build(cfg, env_secret=self.fixture.secrets.__getitem__)
        return Service(store=store, connectors=connectors, backends=backends, analyzer=NotWiredAnalyzer(),
                       installation_id=cfg.installation_id, environment=cfg.environment)

    def ingest(self, service):
        summary = service.reconcile()
        service.run_until_idle()
        return summary

    def test_pr_enters_durable_queue_and_is_not_analysed_or_published(self):
        service = self.service()
        self.assertEqual(self.ingest(service)['enqueued'],1)
        row = service.store.resource(RID)
        self.assertEqual((row['provider'],row['kind']),('bitbucket','pr'))
        self.assertEqual(row['snapshot']['destination_tip_sha'],'b'*40)
        self.assertNotIn('base_sha',row['snapshot'])
        [job] = service.store.jobs(RID)
        self.assertEqual((job['state'],job['attempts']),('QUEUED',0))
        self.assertEqual(service.store.status()['intents'],{})
        self.assertIn('analysis_not_connected',{n['kind'] for n in service.store.notices()})
        self.assertEqual(_kind(job),'pr')
        self.assertTrue(all(method=='GET' for method,_,_ in self.fixture.requests))

    def test_repeat_and_restart_do_not_duplicate_same_generation(self):
        service = self.service()
        self.ingest(service)
        restarted = self.service()
        self.assertEqual(self.ingest(restarted)['enqueued'],0)
        self.assertEqual(len(restarted.store.jobs(RID)),1)
        self.assertEqual(restarted.store.resource(RID)['generation'],1)

    def test_title_edit_and_force_push_back_create_new_generations(self):
        service = self.service()
        self.ingest(service)
        self.pr['title']='ORD-99 changed requirement'
        self.ingest(service)
        self.pr['source']['commit']['hash']='d'*40
        self.ingest(service)
        self.pr['source']['commit']['hash']='a'*40
        self.ingest(service)
        self.assertEqual(service.store.resource(RID)['generation'],4)
        self.assertEqual([j['state'] for j in service.store.jobs(RID)],['SUPERSEDED']*3+['QUEUED'])

    def test_closure_is_refetched_and_stops_open_job(self):
        service = self.service()
        self.ingest(service)
        self.fixture.routes[read_fixture.PINNED+'/pullrequests']['values']=[]
        self.pr['state']='MERGED'
        self.ingest(service)
        self.assertTrue(service.store.resource(RID)['closed'])
        self.assertEqual(service.store.jobs(RID)[0]['state'],'SUPERSEDED')
        self.assertEqual(service.store.jobs(RID)[0]['reason'],'resource_closed')

    def test_commit_resolution_404_does_not_close_an_existing_pr(self):
        service = self.service()
        self.ingest(service)
        self.pr['source']['commit']['hash'] = 'a'*12
        # The PR endpoint remains200; the stand has no commit-resolution route.
        service._synthetic('bitbucket', RID, 'recheck-missing-commit')
        service.step()
        self.assertFalse(service.store.resource(RID)['closed'])
        self.assertEqual(service.store.jobs(RID)[0]['state'], 'QUEUED')
        self.assertEqual(service.store.status()['events'], {'FAILED':1, 'INGESTED':1})

    def test_missing_pr_closes_only_that_known_resource(self):
        service = self.service()
        self.ingest(service)
        self.fixture.routes[read_fixture.PINNED+'/pullrequests']['values']=[]
        del self.fixture.routes[read_fixture.PINNED+'/pullrequests/7']
        self.ingest(service)
        self.assertTrue(service.store.resource(RID)['closed'])

    def test_incomplete_listing_does_not_advance_checkpoint_or_close_absent_pr(self):
        service = self.service()
        self.ingest(service)
        before = service.store.checkpoint('reconcile:bitbucket')
        self.fixture.routes[read_fixture.PINNED+'/pullrequests']={'values':[], 'next':'https://evil.invalid/next'}
        self.assertEqual(service.reconcile()['enqueued'],0)
        self.assertEqual(service.store.checkpoint('reconcile:bitbucket'),before)
        self.assertFalse(service.store.resource(RID)['closed'])

    def test_wrong_uuid_or_auth_refusal_does_not_make_candidates(self):
        service = self.service()
        self.fixture.routes[read_fixture.ROOT]['uuid']=read_fixture.OTHER
        self.assertEqual(service.reconcile()['enqueued'],0)
        self.assertIsNone(service.store.checkpoint('reconcile:bitbucket'))
        self.fixture.routes[read_fixture.ROOT]['uuid']=read_fixture.REPO
        self.fixture.failure=401
        self.assertEqual(service.reconcile()['enqueued'],0)
        self.assertEqual(service.store.status()['jobs'],{})

    def test_foreign_resource_id_is_rejected_before_http(self):
        connector = self.service().connectors['bitbucket']
        for rid in [RID.replace('11111111','44444444'),RID.replace('22222222','44444444'),
                    'github:pilot/orders#7',RID.replace('#7','#../7')]:
            with self.assertRaises(ResourceNotAllowed):
                connector.fetch(rid)
        self.assertEqual(self.fixture.requests,[])

    def test_untrusted_webhooks_do_not_enqueue(self):
        service = self.service()
        status,_=service.receive('bitbucket',{},b'{}')
        self.assertEqual(status,404)
        self.assertEqual(service.store.status()['events'],{})

    def test_live_queue_only_refuses_before_state_or_secrets(self):
        self.fixture.document['publication']='live'
        try:
            cfg=self.fixture.config()
        except ValidationError:
            self.fail('queue_only config must parse; build must reject live before side effects')
        def secrets(name):
            self.fail('read a secret while rejecting live queue_only')
        with self.assertRaisesRegex(ValueError,'bitbucket_queue_only_requires_dry_run'):
            build(cfg,env_secret=secrets)
        self.assertFalse((self.fixture.root/'queue.sqlite').exists())

    def test_jira_and_github_are_processed_while_bitbucket_is_held(self):
        bb=self.service().connectors['bitbucket']
        other=helpers.ServiceCase()
        other.setUp()
        self.addCleanup(other.doCleanups)
        other.service.connectors['bitbucket']=bb
        other.service.publisher.connectors['bitbucket']=bb
        other.service.publisher.backends=dict(other.service.publisher.backends)
        other.service.publisher.backends['bitbucket']=DirectorySink(self.fixture.root/'bb-sink')
        other.service.reconcile()
        other.service.run_until_idle()
        self.assertEqual(other.service.store.jobs(RID)[0]['state'],'QUEUED')
        self.assertTrue(any(j['state']=='DONE' for j in other.service.store.jobs('github:acme/orders#7')))
        self.assertTrue(any(j['state']=='DONE' for j in other.service.store.jobs('jira:10001')))
        self.assertTrue(all(r['pr']['provider']=='github' for r,_ in other.analyzer.requests if r.get('pr')))

    def test_jira_keys_are_project_scoped_and_queue_snapshot_keeps_source_identity(self):
        connector=self.service().connectors['bitbucket']
        connector.jira_project_keys=['KAN']
        self.pr['title']='KAN-4 reduce page size; OTHER-1 is outside scope'
        snap=connector.fetch(RID)
        self.assertEqual(snap.data['linked_jira_keys'],['KAN-4'])
        self.assertEqual(snap.data['provider'],'bitbucket')
        self.assertEqual(snap.kind,'pr')

    def test_removing_bitbucket_config_preserves_pending_events_jobs_and_intents(self):
        service=self.service()
        service.reconcile()  # leave a durable event un-ingested before config removal
        paused=Service(store=service.store,connectors={},analyzer=NotWiredAnalyzer(),
                       installation_id='probe-1',environment='test')
        self.assertIsNone(paused.step())
        self.assertEqual(service.store.status()['events'],{'RECEIVED':1})
        service.run_until_idle()
        self.assertIsNone(paused.step())
        [job]=service.store.jobs(RID)
        self.assertEqual((job['state'],job['attempts']),('QUEUED',0))
        job=service.store.claim_job('setup',providers={'bitbucket'})
        service.store.complete_job(job,state='ANALYZED',result=None,reason='held',intent={
            'kind':'result','body':'{}','body_digest':'a'*64,'marker':'b'*16})
        self.assertIsNone(paused.step())
        self.assertEqual(service.store.status()['intents'],{'PENDING':1})

    def test_provider_filter_never_claims_held_job_or_intent(self):
        service=self.service()
        self.ingest(service)
        self.assertIsNone(service.store.claim_job('worker',providers=set()))
        job=service.store.claim_job('setup',providers={'bitbucket'})
        body={'title':'synthetic held intent','status_line':'pending','sections':[]}
        service.store.complete_job(job,state='ANALYZED',result=None,reason='held',intent={
            'kind':'result','body':json.dumps(body),'body_digest':'a'*64,'marker':'b'*16})
        self.assertIsNone(service.step())
        self.assertEqual(service.store.status()['intents'],{'PENDING':1})
        self.assertIsNone(service.store.claim_intent('worker',providers={'jira'}))
        self.assertEqual(service.store.claim_intent('worker',providers={'bitbucket'})['resource_id'],RID)


if __name__=='__main__':
    unittest.main()
