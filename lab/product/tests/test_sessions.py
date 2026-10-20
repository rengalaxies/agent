import tempfile
import unittest
import uuid
from pathlib import Path
from lab.product.sessions import Sessions, CONSENT_VERSION
from lab.runtime.core import Stop


def change():
    return dict(change_id='same-example',revision=1,title='PRIVATE TITLE',intent='PRIVATE INTENT',
                proposed_diff='PRIVATE DIFF',source_commit='test',proposed_files={})

class SessionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.manager=Sessions(Path(self.tmp.name))
    def tearDown(self):self.tmp.cleanup()
    def test_two_sequential_sessions_no_state_carry_and_selected_reset(self):
        m=self.manager;a=m.create('confirmed');sa=m.workspace(a['session_id']);ca=sa.create_change(change())
        sa.log(ca,'TEAM_DECISION',decision_id='private')
        (m.paths(a['session_id'])[1]/'evidence.json').write_text('{"first":true}')
        m.end(a['session_id']);b=m.create('confirmed');sb=m.workspace(b['session_id'])
        self.assertNotEqual(a['session_id'],b['session_id']);self.assertEqual(sb.rows('changes'),[])
        self.assertEqual(sb.rows('decisions'),[]);self.assertEqual(list(m.paths(b['session_id'])[1].iterdir()),[])
        sb.create_change(change());m.reset(b['session_id'])
        self.assertEqual(m.workspace(b['session_id']).rows('changes'),[])
        self.assertEqual(len(sa.rows('changes')),1)
        self.assertTrue((m.paths(a['session_id'])[1]/'evidence.json').exists())
    def test_two_business_passes_reuse_worker_no_decision_transfer(self):
        from lab.product.worker import Worker
        m=self.manager
        first_decision=None
        for index in range(2):
            session=m.create('confirmed');sid=session['session_id'];store=m.workspace(sid)
            self.assertEqual(store.rows('decisions'),[])
            c=store.create_change(change())
            worker=Worker(store,m.paths(sid)[1],collector=lambda:{'mode':'LIVE RUN','basis_digest':'same-synthetic-test-basis','edges':[]})
            for operation,mode in [('snapshot','LIVE RUN'),('analysis','FIXTURE / CONTROL')]:
                job=store.enqueue(dict(change_id=c['change_id'],operation=operation,mode=mode,idempotency_key=operation))
                worker.run_once();self.assertEqual(store.entity('jobs',job['id'])['status'],'SUCCEEDED')
            self.assertEqual({x['team'] for x in store.rows('cards')},{'billing','analytics'})
            card=store.rows('cards')[0]
            decision=store.decide(dict(card_id=card['id'],revision=1,assessment_digest=card['assessment_digest'],team=card['team'],actor='synthetic',decision='acknowledged'))
            self.assertFalse(decision['grants_execution'])
            if index==0:first_decision=decision['id']
            else:self.assertNotIn(first_decision,[d['id'] for d in store.rows('decisions')])
            m.end(sid)
    def test_consent_allowlist_delete_keeps_technical_records(self):
        m=self.manager;s=m.create('confirmed');sid=s['session_id'];store=m.workspace(sid)
        store.create_change(change())
        self.assertFalse(m.record(sid,uuid.uuid4().hex,'CHANGE_CREATED')['recorded'])
        m.consent(sid,True,CONSENT_VERSION)
        c=store.rows('changes')[0];store.log(c,'JOB_STOPPED',error='SECRET password and participant email')
        m.record(sid,uuid.uuid4().hex,'SCENARIO_STARTED',help_category='navigation')
        exported=m.export(sid)
        self.assertEqual(len(exported['observations']),2)
        serialized=str(exported)
        for private in ('SECRET','PRIVATE','password','email'):self.assertNotIn(private,serialized)
        with self.assertRaises(Stop):m.record(sid,uuid.uuid4().hex,'SECRET FREE TEXT')
        self.assertEqual(len(m.export(sid)['observations']),2)
        m.delete_research(sid)
        self.assertEqual(m.export(sid)['observations'],[])
        self.assertTrue(store.rows('journal'))
        self.assertTrue(m.db.execute('SELECT count(*) FROM technical_audit WHERE session_id=?',(sid,)).fetchone()[0])
    def test_unknown_owner_reuses_control_catalog_without_mutating_collector(self):
        from lab.product.sessions import session_options
        from lab.product.worker import Worker
        m=self.manager;session=m.create('unknown-owner');sid=session['session_id']
        original={'mode':'LIVE RUN','basis_digest':'real-original','owners':{'bindings':[
            {'environment_id':'lab','object_ref':'lab/app/service.py#consume','team_id':'billing'}]},'edges':[]}
        options=session_options(m,sid,{'collector':lambda:original})
        snapshot=options['collector']()
        self.assertEqual(len(original['owners']['bindings']),1)
        self.assertEqual(snapshot['owners']['bindings'],[])
        self.assertNotEqual(snapshot['basis_digest'],original['basis_digest'])
        self.assertEqual(snapshot['ownership_control']['mode'],'FIXTURE / CONTROL')
        store=m.workspace(sid);c=store.create_change(change());worker=Worker(store,m.paths(sid)[1],**options)
        for operation,mode in [('snapshot','LIVE RUN'),('analysis','FIXTURE / CONTROL')]:
            job=store.enqueue(dict(change_id=c['change_id'],operation=operation,mode=mode,idempotency_key=operation))
            worker.run_once();self.assertEqual(store.entity('jobs',job['id'])['status'],'SUCCEEDED')
        self.assertEqual({c['team'] for c in store.rows('cards')},{'COORDINATOR'})
        self.assertTrue(all(c['status']=='заблокировано' for c in store.rows('cards')))
    def test_restart_preserves_sessions_and_rejects_traversal(self):
        m=self.manager;s=m.create('stale');sid=s['session_id'];m.workspace(sid).create_change(change())
        reopened=Sessions(Path(self.tmp.name));self.assertEqual(len(reopened.workspace(sid).rows('changes')),1)
        with self.assertRaises(Stop):reopened.workspace('../state')
        self.assertEqual(reopened.scenario(sid)['reuses'],['D','E'])
    def test_reset_refuses_active_job(self):
        m=self.manager;s=m.create('unknown-owner');sid=s['session_id'];store=m.workspace(sid);store.create_change(change())
        store.enqueue(dict(change_id='same-example',operation='snapshot',mode='LIVE RUN',idempotency_key='1'))
        with self.assertRaises(Stop):m.reset(sid)
    def test_no_retroactive_capture_and_explicit_notice(self):
        m=self.manager;s=m.create('confirmed');sid=s['session_id'];m.workspace(sid).create_change(change())
        with self.assertRaises(Stop):m.consent(sid,True,'outdated')
        m.consent(sid,True,CONSENT_VERSION);self.assertEqual(m.export(sid)['observations'],[])

if __name__=='__main__':unittest.main()
