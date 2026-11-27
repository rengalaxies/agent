import json
from pathlib import Path
import tempfile
import unittest

from tools.agent_service.kaiten_live_acceptance import validate_isolation, assess_report


class AcceptanceTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name).resolve()
        (self.root/'mirrors').mkdir();(self.root/'mirrors'/'orders.git').mkdir()
        self.policy={'installation_id':'cloud-test','environment':'test','model':None,'repositories':[{'id':'bb.orders','root':str(self.root/'mirrors'/'orders.git')} ]}
        (self.root/'policy.json').write_text(json.dumps(self.policy))
        self.config={'installation_id':'cloud-test','environment':'test','publication':'live','allow_loopback_http':False,'state_path':str(self.root/'state'/'queue.sqlite'),
            'bitbucket':{'mode':'kaiten_delivery','api_base':'https://api.bitbucket.org/2.0','workspace_uuid':'workspace','repositories':{'orders':{'uuid':'repo','repository_id':'bb.orders'}}},
            'core':{'policy_path':str(self.root/'policy.json'),'state_dir':str(self.root/'state'/'core')},
            'kaiten':{'base_url':'https://rengalaxies.kaiten.ru','board_ids':['20'],'bot_id':'7','bindings':{'bitbucket:workspace/repo#5':'12'}}}
        self.scope={'installation_id':'cloud-test','environment':'test','provider_repository':'bb.orders','destination_tip':'d'*40,'head_ref':'impactmap-test','base_ref':'main','consumer_pins':{},'resource_id':'bitbucket:workspace/repo#5','workspace_uuid':'workspace','repository_uuids':['repo'],'kaiten_origin':'https://rengalaxies.kaiten.ru','board_ids':['20'],'card_ids':['12','13'],'bot_id':'7'}

    def test_isolated_real_cloud_config_accepted(self):
        validate_isolation(self.config,self.scope,self.root)

    def test_production_paths_foreign_target_and_mock_source_refused(self):
        import copy
        variants=[]
        c=copy.deepcopy(self.config);c['state_path']='/var/lib/agent-bitbucket/live-acceptance/queue.sqlite';variants.append(c)
        c=copy.deepcopy(self.config);c['kaiten']['bindings'][self.scope['resource_id']]='99';variants.append(c)
        c=copy.deepcopy(self.config);c['bitbucket']['api_base']='http://127.0.0.1:9090/2.0';variants.append(c)
        c=copy.deepcopy(self.config);c['kaiten']['base_url']='https://other.kaiten.ru';variants.append(c)
        c=copy.deepcopy(self.config);c['jira']={'base_url':'https://example.atlassian.net'};variants.append(c)
        for config in variants:
            with self.subTest(config=config),self.assertRaises(ValueError): validate_isolation(config,self.scope,self.root)

    def test_mirror_symlink_escape_and_model_refused(self):
        outside=Path(self.tmp.name).parent
        mirror=self.root/'mirrors'/'orders.git';mirror.rmdir();mirror.symlink_to(outside,target_is_directory=True)
        with self.assertRaises(ValueError): validate_isolation(self.config,self.scope,self.root)
        mirror.unlink();mirror.mkdir()
        self.policy['model']={'endpoint':'http://example.invalid'};(self.root/'policy.json').write_text(json.dumps(self.policy))
        with self.assertRaises(ValueError): validate_isolation(self.config,self.scope,self.root)

    def report(self):
        return {'closed':False,'stored_closed':False,'head':'a'*40,'destination_tip':'d'*40,'provider_repository':'bb.orders',
                'expected_consumer_pins':{},'target_card_id':'12','expected_card_id':'12','history_failures':[],'reconcile_errors':[],
                'published_generation':1,'comment_id':'9','comment_digest':'b'*64,
                'jobs':[{'state':'DONE','generation':1,'status':'USEFUL','reason':'impact_found_within_profile','findings':['POSSIBLE_TRUNCATION'],
                         'snapshots':[{'repository':'bb.orders','role':'base','commit':'d'*40},{'repository':'bb.orders','role':'head','commit':'a'*40}]}],
                'intents':[{'state':'DELIVERED','generation':1,'kind':'result','comment_id':'9','body_digest':'b'*64,'receipt':{'current_at_delivery':True,'wrote':True}}],
                'owned_comments':[{'id':'9','digest':'b'*64,'generation':1}],'generation':1}

    def test_old_generation_failure_cannot_hide_behind_last_success(self):
        report=self.report();report['jobs'].insert(0,{'state':'FAILED','generation':0})
        self.assertIn('failed_job',assess_report(report,expected_head='a'*40,expected_status='USEFUL',expected_finding='POSSIBLE_TRUNCATION'))

    def test_current_delivery_single_comment_and_pinned_head_are_required(self):
        report=self.report();self.assertEqual(assess_report(report,expected_head='a'*40,expected_status='USEFUL',expected_finding='POSSIBLE_TRUNCATION'),[])
        report['owned_comments'].append({'id':'10'});report['head']='b'*40
        errors=assess_report(report,expected_head='a'*40,expected_status='USEFUL',expected_finding='POSSIBLE_TRUNCATION')
        self.assertIn('wrong_head',errors);self.assertIn('not_one_owned_comment',errors)

    def test_closed_target_is_distinct_from_successful_analysis(self):
        report=self.report();report.update(closed=True,stored_closed=True,owned_comments=[])
        self.assertEqual(assess_report(report,expected_head='a'*40,expect_closed=True),[])
        self.assertIn('resource_closed',assess_report(report,expected_head='a'*40,expected_status='USEFUL'))

    def test_false_pass_missing_pins_stale_comment_and_notice_refused(self):
        r=self.report();r['jobs'][0]['snapshots']=[];r['owned_comments'][0].update(digest='c'*64,generation=0);r['intents'][0]['kind']='stale'
        self.assertTrue(assess_report(r,expected_head='a'*40,expected_status='USEFUL'))

    def test_closed_does_not_allow_sending_and_revived_failures_remain_failures(self):
        r=self.report();r.update(closed=True,stored_closed=True);r['intents'][0]['state']='SENDING'
        self.assertTrue(assess_report(r,expected_head='a'*40,expect_closed=True))
        r=self.report();r['history_failures']=[{'entry':'job_failed','generation':1}]
        self.assertTrue(assess_report(r,expected_head='a'*40,expected_status='USEFUL'))

    def test_external_context_and_identity_are_refused(self):
        self.config['core']['constitution_path']='/opt/agent-bitbucket/current/app/constitutions/agent-service-v1.yaml'
        with self.assertRaises(ValueError):validate_isolation(self.config,self.scope,self.root)
        del self.config['core']['constitution_path'];self.policy['installation_id']='another'
        (self.root/'policy.json').write_text(json.dumps(self.policy))
        with self.assertRaises(ValueError):validate_isolation(self.config,self.scope,self.root)

    def test_controller_rejects_raw_secret_reads_and_path_runids(self):
        from tools.agent_service.kaiten_live_acceptance import validate_control_request
        for action,name in (('read','secrets.json'),('read','service.json'),('run','/etc/outside'),('run','../outside')):
            with self.assertRaises(ValueError):validate_control_request(action,name)
        validate_control_request('run','change-killed');validate_control_request('fault-ready',None)

    def test_safe_test_summary_never_returns_raw_log_or_secret(self):
        from tools.agent_service.kaiten_live_acceptance import safe_test_summary
        r=safe_test_summary('private_key=SECRET\ntest_ok (tests.service.Foo.test_ok) ... ok\nRan 4 tests in 1.1s\n\nOK\n')
        self.assertEqual(r['run'],4);self.assertTrue(r['success']);self.assertNotIn('SECRET',json.dumps(r))

    def test_recovery_requires_killed_process_same_database_and_no_second_write(self):
        from tools.agent_service.kaiten_live_acceptance import recovery_errors
        ready={'run_id':'first','pid':10,'start_ticks':'123','state':'SENDING','comment_id':'9','digest':'b'*64,'db_device':1,'db_inode':2}
        killed={'run_id':'first','killed_pid':10,'start_ticks':'123','signal':9,'not_running':True}
        report=self.report();report.update(pid=11,db_device=1,db_inode=2,recovered={'sending':1})
        report['intents'][0]['receipt']['wrote']=False
        self.assertEqual(recovery_errors(ready,killed,report),[])
        report['pid']=10;report['intents'][0]['receipt']['wrote']=True
        self.assertTrue(recovery_errors(ready,killed,report))
