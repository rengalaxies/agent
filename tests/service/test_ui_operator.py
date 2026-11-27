"""Operator projections use real scope receipts and never connector/config serialization."""
import json
from pathlib import Path
import sqlite3
import unittest
from tests.service import test_ui_scope
from tests.graph.test_output_contracts import result
from agent_service.config import ServiceConfig


class OperatorTests(unittest.TestCase):
    setUp=test_ui_scope.ScopeTests.setUp
    open=test_ui_scope.ScopeTests.open
    claim=test_ui_scope.ScopeTests.claim
    finish=test_ui_scope.ScopeTests.finish

    def metadata(self):
        from agent_service.ui_operator import OperatorMetadata
        return OperatorMetadata('dry_run',('bitbucket',),(('orders','bitbucket'),('reporting','bitbucket')),
            (('kaiten',('10',),'bitbucket'),),((self.rid,'orders','kaiten','20'),))

    def get(self,section='operations',metadata=True):
        return self.store.ui_operator(self.scope,self.metadata() if metadata else None,section)

    def test_queue_failures_stale_and_unknown_delivery_remain_independent(self):
        self.finish();self.open('v2');job=self.claim()
        self.store.complete_job(job,state='FAILED',result=None,reason='commit_unavailable',intent=None)
        with self.store._connect() as c:c.execute("UPDATE intents SET state='UNKNOWN',reason='outcome_unknown',receipt='PRIVATE_RECEIPT'")
        data=self.get();row=data['items'][0]
        self.assertEqual(row['current_job']['state'],'FAILED')
        self.assertEqual(row['analysis']['freshness'],'STALE')
        self.assertTrue(row['analysis']['compatible'])
        self.assertEqual(row['outbox'][0]['state'],'UNKNOWN')
        self.assertEqual(data['worker']['state'],'NOT_OBSERVED')
        self.assertEqual(data['counts']['jobs'],{'FAILED':1})
        self.assertNotIn('PRIVATE_',json.dumps(data))

    def test_failure_intent_is_visible_without_returning_document_or_arbitrary_reason(self):
        job=self.claim()
        self.store.complete_job(job,state='FAILED',result=None,reason='PRIVATE_PASSWORD',
            intent={'kind':'failure','body':'PRIVATE_DOCUMENT','body_digest':'a'*64,'marker':'PRIVATE_MARKER'})
        row=self.get()['items'][0]
        self.assertEqual(row['current_job']['reason'],'UNKNOWN')
        self.assertEqual(row['outbox'][0]['kind'],'failure')
        self.assertNotIn('PRIVATE_',json.dumps(row))

    def test_notice_details_and_unattributed_resource_notices_never_leak(self):
        self.finish();self.store.note('connection_unauthorized','bitbucket','PRIVATE_HEADER',ui_scope=self.scope)
        self.store.note('provider_rejected',self.rid,'PRIVATE_BODY',ui_scope=self.scope)
        self.store.note('provider_rejected','foreign#77','PRIVATE_FOREIGN',ui_scope=self.scope)
        self.store.note('PRIVATE_NOTICE','bitbucket','PRIVATE_SECRET',ui_scope=self.scope)
        data=self.get()
        self.assertEqual({n['kind'] for n in data['notices']},{'connection_unauthorized','provider_rejected'})
        self.assertNotIn('PRIVATE_',json.dumps(data));self.assertNotIn('foreign#77',json.dumps(data))

    def test_hidden_rows_do_not_affect_counts_or_resource_links(self):
        self.finish();before=self.get()
        self.open(rid='foreign#1');self.finish(stamp=False)
        after=self.get()
        for key in ['counts','items','notices','has_more']:self.assertEqual(before[key],after[key])

    def test_connections_inventory_does_not_claim_health_and_yandex_stays_disconnected(self):
        self.finish();self.store.checkpoint('reconcile:bitbucket','1000')
        data=self.get('connections')
        kaiten=next(t for t in data['trackers'] if t['id']=='kaiten')
        yandex=next(t for t in data['trackers'] if t['id']=='yandex')
        self.assertEqual(kaiten['state'],'NOT_CHECKED');self.assertEqual(yandex['state'],'NOT_CONNECTED')
        self.assertEqual(data['intake'][0]['last_inventory_at'],1000)
        self.assertEqual(data['intake'][0]['state'],'NOT_CHECKED')

    def test_binding_is_explicit_unverified_and_changed_saved_target_conflicts(self):
        self.finish();data=self.get('connections');b=data['bindings'][0]
        self.assertEqual((b['target'],b['state']),('20','CONFIGURED_UNVERIFIED'))
        with self.store._connect() as c:c.execute('UPDATE resources SET snapshot=?',(json.dumps({'_tracker_target':'21','secret':'PRIVATE_SNAPSHOT'}),))
        b=self.get('connections')['bindings'][0]
        self.assertEqual(b['state'],'CONFLICT');self.assertNotIn('21',json.dumps(b))

    def test_missing_metadata_is_explicit_and_never_reads_connectors(self):
        self.assertFalse(self.get(metadata=False)['available'])

    def test_incompatible_analysis_reason_is_not_an_operator_secret_channel(self):
        self.finish({'schema_version':'alien','reason_code':'PRIVATE_REASON'})
        self.assertNotIn('PRIVATE_',json.dumps(self.get()))

    def test_arbitrary_reason_mismatch_is_not_accepted_as_queue_revocation(self):
        self.finish()
        with self.store._connect() as c:c.execute("UPDATE jobs SET state='SUPERSEDED',reason='PRIVATE_REASON'")
        self.assertFalse(self.get()['items'][0]['analysis']['compatible'])

    def test_repeated_operator_reads_leave_service_database_unchanged(self):
        self.finish()
        def dump():
            c=sqlite3.connect(self.store.path)
            try:return '\n'.join(c.iterdump())
            finally:c.close()
        before=dump();self.get();self.get('connections');self.assertEqual(before,dump())

    def test_config_metadata_extracts_only_declared_ids_never_secrets_paths_or_urls(self):
        from agent_service.ui_operator import metadata_for_config
        from dataclasses import asdict
        c=ServiceConfig.model_validate(dict(installation_id='acme',environment='prod',state_path='/PRIVATE_STATE',
            publication='dry_run',github=dict(repositories=['ACME/Orders'],repository_ids={'acme/orders':'orders'},
            bot_login='PRIVATE_BOT',webhook_secret_env='PRIVATE_WEBHOOK',auth=dict(kind='token',token_env='PRIVATE_TOKEN')),
            jira=dict(base_url='https://PRIVATE_SITE',project_keys=['KAN'],bot_account_id='PRIVATE_BOT',webhook_secret_env='PRIVATE_HOOK',
                      auth=dict(kind='bearer',token_env='PRIVATE_JIRA'))))
        meta=metadata_for_config(c);text=json.dumps(asdict(meta))
        self.assertIn('orders',text);self.assertIn('KAN',text);self.assertNotIn('PRIVATE_',text)

    def test_jira_multiple_links_conflict_only_inside_configured_project(self):
        from agent_service.ui_operator import OperatorMetadata
        self.finish()
        meta=OperatorMetadata('live',('bitbucket',),(('orders','bitbucket'),), (('jira',('KAN',),'bitbucket'),),())
        with self.store._connect() as c:c.execute('UPDATE resources SET snapshot=?',(json.dumps({'linked_jira_keys':['KAN-1','KAN-2']}),))
        b=self.store.ui_operator(self.scope,meta,'connections')['bindings'][0]
        self.assertEqual(b['state'],'CONFLICT');self.assertEqual(b['targets'],['KAN-1','KAN-2'])
        with self.store._connect() as c:c.execute('UPDATE resources SET snapshot=?',(json.dumps({'linked_jira_keys':['KAN-1','FOREIGN-1']}),))
        b=self.store.ui_operator(self.scope,meta,'connections')['bindings'][0]
        self.assertEqual(b['state'],'CONFLICT');self.assertEqual(b['targets'],['KAN-1'])
        text=json.dumps(self.store.ui_operator(self.scope,meta,'connections'))
        self.assertNotIn('FOREIGN',text)

    def test_legacy_and_old_scope_notices_do_not_authorize_current_counts(self):
        from dataclasses import replace
        self.finish();old=replace(self.scope,view_id='7'*64)
        self.store.note('connection_unauthorized','bitbucket','PRIVATE_OLD')
        self.assertEqual(self.get()['notices'],[])
        self.store.note('connection_unauthorized','bitbucket','PRIVATE_OLD',ui_scope=old)
        self.assertEqual(self.get()['notices'],[])
        self.store.note('connection_unauthorized','bitbucket','PRIVATE_CURRENT',ui_scope=self.scope)
        self.assertEqual(self.get()['notices'][0]['count'],1)
        self.store.clear_notice('connection_unauthorized','bitbucket',ui_scope=self.scope)
        self.assertEqual(self.get()['notices'],[])

    def test_outbox_limit_is_applied_after_generation_scope_and_published_pin_is_hidden(self):
        self.finish()
        before=self.get()['items'][0]['outbox']
        with self.store._connect() as c:
            original=dict(c.execute('SELECT * FROM intents').fetchone())
            for n in range(20):
                row={**original,'intent_id':f'foreign-intent-{n}','generation':n+10}
                c.execute('INSERT INTO intents VALUES('+','.join('?' for _ in row)+')',tuple(row.values()))
            c.execute('UPDATE resources SET published_generation=888')
        row=self.get()['items'][0]
        self.assertEqual(row['outbox'],before)
        self.assertNotIn('published_generation',row['resource'])

    def test_kaiten_config_binding_requires_matching_workspace_and_repository(self):
        from agent_service.ui_operator import metadata_for_config
        workspace='11111111-1111-4111-8111-111111111111';repo='22222222-2222-4222-8222-222222222222'
        rid=f'bitbucket:33333333-3333-4333-8333-333333333333/{repo}#1'
        c=ServiceConfig.model_validate(dict(installation_id='acme',environment='prod',state_path='/state',publication='dry_run',
            bitbucket=dict(mode='kaiten_delivery',workspace='author',workspace_uuid=workspace,repositories={'orders':dict(uuid=repo,repository_id='orders')},
                           auth=dict(email_env='EMAIL',token_env='TOKEN')),
            kaiten=dict(base_url='https://author.invalid',board_ids=['10'],bot_id='1',token_env='TOKEN',bindings={rid:'20'})))
        self.assertEqual(metadata_for_config(c).bindings,())
        c.kaiten.bindings={f'bitbucket:{workspace}/{repo}#1':'20'}
        self.assertEqual(len(metadata_for_config(c).bindings),1)

    def test_service_and_publisher_notice_writers_stamp_actual_loaded_policy_scope(self):
        from types import SimpleNamespace
        from agent_service.service import Service
        from agent_graph.contracts import Policy
        from agent_service.ui_scope import scope_for_service
        policy=Policy.model_validate(dict(installation_id='acme',environment='prod',subject='author',capabilities=['read_context'],
            repositories=[dict(id=r,service=r,root=str(Path(self.tmp.name)/r),revision='main') for r in self.scope.repositories],addresses=[]))
        service=Service(store=self.store,connectors={},analyzer=SimpleNamespace(policy=policy,runtime_sources=[]),installation_id='acme',environment='prod')
        self.scope=scope_for_service(service)
        service._note('connection_unauthorized','bitbucket','PRIVATE_SERVICE')
        service.publisher._note('connection_unauthorized','bitbucket','PRIVATE_PUBLISHER')
        self.assertEqual(self.get()['notices'][0]['count'],2)
        service.publisher._clear_notice('connection_unauthorized','bitbucket')
        self.assertEqual(self.get()['notices'],[])
        Service(store=self.store,connectors={'bitbucket':SimpleNamespace(analysis_ready=False)},analyzer=service.analyzer,
                installation_id='acme',environment='prod')
        self.assertEqual(self.get()['notices'][0]['kind'],'analysis_not_connected')
