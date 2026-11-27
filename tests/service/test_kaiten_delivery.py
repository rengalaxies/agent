import unittest
from dataclasses import replace
from unittest.mock import Mock

from agent_service.connectors.base import Snapshot, Prepared, Comment, ResourceNotAllowed
from agent_service.connectors.bitbucket_kaiten import BitbucketKaitenConnector, BitbucketKaitenBackend
from agent_service.config import ServiceConfig, build
from agent_service.service import Service
from tests.service.test_tracker_api_probe import Stand
from tests.service import test_bitbucket_analysis as worker_fixture


class BindingTest(unittest.TestCase):
    def setUp(self):
        self.source = Mock()
        self.source.fetch.return_value = Snapshot('bitbucket:pr','pr','source-1',{'title':'PR'})
        self.source.prepare.return_value = Prepared({'provider':'bitbucket'}, {'orders':'a'*40})
        self.target = Mock(bot_identity='7')
        self.target.identity.side_effect = lambda card: __import__('agent_service.connectors.tracker_contract',fromlist=['TaskIdentity']).TaskIdentity('kaiten','https://demo.kaiten.ru',card)
        self.target.read_card.return_value = Snapshot('kaiten:12','task','task-1',{'card_id':'12','title':'Card'})
        self.connector = BitbucketKaitenConnector(self.source,self.target,bindings={'bitbucket:pr':'12'})
        self.backend = BitbucketKaitenBackend(self.connector,self.target)
        self.store = Mock(); self.store.resource.return_value={'version': self.connector.fetch('bitbucket:pr').version}
        self.backend.bind_store(self.store)

    def test_task_context_version_and_prepare_are_fenced(self):
        first = self.connector.fetch('bitbucket:pr')
        self.target.read_card.return_value = replace(self.target.read_card.return_value, version='task-2')
        self.assertNotEqual(first.version,self.connector.fetch('bitbucket:pr').version)
        with self.assertRaises(Exception): self.connector.prepare(first)
        prepared = self.connector.prepare(self.connector.fetch('bitbucket:pr'))
        self.assertEqual(prepared.attachments['tracker_context']['title'],'Card')

    def test_scoped_ids_and_relink_cannot_edit_old_card(self):
        self.target.create_comment.return_value='9'
        cid = self.backend.create_comment('bitbucket:pr',{},'marker',expected_intent={'resource_id':'bitbucket:pr','resource_version':self.store.resource.return_value['version'],'generation':1})
        self.connector.bindings['bitbucket:pr']='13'
        with self.assertRaises(ResourceNotAllowed): self.backend.update_comment('bitbucket:pr',cid,{},'marker')
        self.target.update_comment.assert_not_called()

    def test_unbound_closed_and_duplicate_owned_markers_refused(self):
        with self.assertRaises(ResourceNotAllowed): self.connector.fetch('bitbucket:other')
        self.target.list_comments.return_value=[Comment('1','7','a'*16,'b'*64,1),Comment('2','7','a'*16,'b'*64,1)]
        with self.assertRaises(ResourceNotAllowed): self.backend.list_comments('bitbucket:pr')
        self.target.read_card.return_value=replace(self.target.read_card.return_value,closed=True)
        with self.assertRaises(ResourceNotAllowed): self.backend.create_comment('bitbucket:pr',{},'marker')


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.fixture=worker_fixture.WorkerTest(); self.fixture.setUp(); self.addCleanup(self.fixture.doCleanups)
        self.stand=Stand('kaiten'); self.addCleanup(self.stand.close)
        f=self.fixture.f
        f.document['bitbucket']['mode']='kaiten_delivery'
        f.document['kaiten']={'base_url':self.stand.client.base_url,'board_ids':['20'],'bot_id':'7','token_env':'KAITEN_TOKEN','bindings':{self.fixture.rid:'12'}}
        f.document['publication']='live'
        f.secrets['KAITEN_TOKEN']='synthetic'
        self.config=f.config()
        self.store,self.connectors,self.backends=build(self.config,env_secret=f.secrets.__getitem__)
        self.service=Service(store=self.store,connectors=self.connectors,backends=self.backends,analyzer=self.fixture.analyzer,installation_id='agent-pilot',environment='test')

    def run_worker(self):
        self.service.reconcile(); return self.service.run_until_idle()

    def test_real_core_to_http_same_comment_after_change_and_restart(self):
        self.run_worker()
        self.assertEqual(len(self.stand.comments),1)
        self.assertTrue(any(r[0]=='POST' for r in self.stand.requests))
        first=self.stand.comments[0]['text']
        self.fixture.pr['title']='Updated title'
        self.run_worker()
        self.assertEqual(len(self.stand.comments),1)
        self.assertNotEqual(first,self.stand.comments[0]['text'])
        self.assertTrue(any(r[0]=='PATCH' for r in self.stand.requests))
        self.service.recover(); self.run_worker()
        self.assertEqual(len(self.stand.comments),1)
        self.assertEqual(self.store.intents(self.fixture.rid)[-1]['state'],'DELIVERED')

    def test_dry_run_never_posts_to_kaiten(self):
        self.config.publication='dry_run'
        store,connectors,backends=build(self.config,env_secret=self.fixture.f.secrets.__getitem__)
        service=Service(store=store,connectors=connectors,backends=backends,analyzer=self.fixture.analyzer,installation_id='agent-pilot',environment='test')
        service.reconcile();service.run_until_idle()
        self.assertFalse(any(r[0]!='GET' for r in self.stand.requests))

    def test_ambiguous_config_rejected(self):
        document=self.config.model_dump(mode='json')
        document['bitbucket']['mode']='local_analysis'
        with self.assertRaises(ValueError): build(ServiceConfig.model_validate(document),env_secret=self.fixture.f.secrets.__getitem__)

class ReviewRegressionTest(unittest.TestCase):
    def test_old_locator_is_stale_on_lookup_but_update_strict(self):
        f=BindingTest();f.setUp()
        self.assertIsNone(f.backend.get_comment('bitbucket:pr','dry-run-old-id'))
        from agent_service.connectors.tracker_contract import CommentIdentity,TaskIdentity
        old=CommentIdentity(TaskIdentity('kaiten','https://demo.kaiten.ru','13'),'9').encode()
        self.assertIsNone(f.backend.get_comment('bitbucket:pr',old))
        with self.assertRaises((ResourceNotAllowed,ValueError)): f.backend.update_comment('bitbucket:pr',old,{},'marker')

    def test_old_intent_cannot_write_even_when_latest_db_matches_latest_source(self):
        f=BindingTest();f.setUp()
        old_version=f.connector.fetch('bitbucket:pr').version
        intent={'resource_id':'bitbucket:pr','resource_version':old_version,'generation':1}
        f.source.fetch.return_value=replace(f.source.fetch.return_value,version='source-2')
        f.store.resource.return_value={'version':f.connector.fetch('bitbucket:pr').version,'generation':2}
        f.store.intent_is_current.return_value=False
        with self.assertRaises(ResourceNotAllowed): f.backend.create_comment('bitbucket:pr',{},'marker',expected_intent=intent)
        f.target.create_comment.assert_not_called()

    def test_missing_token_fails_during_build(self):
        f=RuntimeTest();f.setUp();self.addCleanup(f.doCleanups)
        del f.fixture.f.secrets['KAITEN_TOKEN']
        with self.assertRaises((ValueError,KeyError)): build(f.config,env_secret=f.fixture.f.secrets.__getitem__)

    def test_new_generation_during_sending_does_not_write_old_body(self):
        f=RuntimeTest();f.setUp();self.addCleanup(f.doCleanups)
        from tests.service.clock import Clock
        clock=Clock(); f.store.clock=clock
        changed=False
        def hook(phase,intent):
            nonlocal changed
            if phase=='sending' and not changed:
                changed=True
                f.fixture.pr['title']='Fresh change during send'
                f.service._apply(f.connectors['bitbucket'].fetch(f.fixture.rid),'newer-during-send')
        f.service.hook=hook;f.service.publisher.hook=hook
        f.run_worker()
        self.assertTrue(changed)
        clock.advance(10000); f.service.run_until_idle()
        self.assertFalse(any(r[0]=='POST' and 'generation=1' in r[3]['text'] for r in f.stand.requests))
        self.assertEqual(len(f.stand.comments),1)

    def test_lost_response_after_create_reconciles_on_restarted_store(self):
        from agent_service.http import TransportError
        from tests.service.clock import Clock
        f=RuntimeTest();f.setUp();self.addCleanup(f.doCleanups)
        clock=Clock(); f.store.clock=clock
        client=f.connectors['bitbucket'].kaiten.client; real=client.request
        def lost(method,*a,**kw):
            response=real(method,*a,**kw)
            if method=='POST': raise TransportError('simulated_after_apply')
            return response
        client.request=lost
        f.run_worker()
        self.assertEqual(len(f.stand.comments),1)
        self.assertEqual(f.store.intents(f.fixture.rid)[-1]['state'],'UNKNOWN')
        clock.advance(10000)
        store,connectors,backends=build(f.config,clock=clock,env_secret=f.fixture.f.secrets.__getitem__)
        service=Service(store=store,connectors=connectors,backends=backends,analyzer=f.fixture.analyzer,installation_id='agent-pilot',environment='test')
        service.recover();service.run_until_idle()
        self.assertEqual(len(f.stand.comments),1)
        self.assertEqual(store.intents(f.fixture.rid)[-1]['state'],'DELIVERED')
