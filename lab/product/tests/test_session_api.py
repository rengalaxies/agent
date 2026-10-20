import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from lab.product.api import create_app
from lab.product.sessions import CONSENT_VERSION
from lab.product.tests.test_store import change

class SessionAPITests(unittest.TestCase):
    def test_isolation_reset_consent_delete_and_gate(self):
        with tempfile.TemporaryDirectory() as d:
            app=create_app(Path(d)/'state.db',start_worker=False)
            with TestClient(app) as a,TestClient(app) as b:
                first=a.post('/api/lab/sessions',json={'scenario':'confirmed'}).json()
                second=b.post('/api/lab/sessions',json={'scenario':'unknown-owner'}).json()
                self.assertNotEqual(first['session_id'],second['session_id'])
                self.assertIn('HttpOnly',a.cookies.get('lab_session') and a.post('/api/lab/sessions',json={'scenario':'confirmed'}).headers['set-cookie'])
                payload={**change(),'source_commit':a.get('/api/lab/state').json()['source_commit']}
                self.assertEqual(a.post('/api/lab/changes',json=payload).status_code,200)
                self.assertEqual(b.get('/api/lab/state').json()['changes'],[])
                self.assertEqual(a.get('/api/lab/sessions/export').json()['observations'],[])
                self.assertEqual(a.post('/api/lab/sessions/consent',json={'enabled':True,'notice_version':CONSENT_VERSION}).status_code,200)
                self.assertEqual(a.post('/api/lab/sessions/help',json={'category':'navigation'}).status_code,200)
                export=a.get('/api/lab/sessions/export').json()
                self.assertEqual(export['observations'][0]['moderator_help'],'navigation')
                self.assertNotIn('actor',export['observations'][0])
                self.assertEqual(a.post('/api/lab/sessions/help',json={'category':'arbitrary-private-note'}).status_code,409)
                self.assertEqual(a.post('/api/lab/apply',json={}).status_code,403)
                self.assertEqual(a.post('/api/lab/sessions/reset',json={}).json()['generation'],2)
                self.assertEqual(a.get('/api/lab/state').json()['changes'],[])
                self.assertEqual(b.get('/api/lab/sessions/current').json()['session']['generation'],1)
                self.assertTrue(a.post('/api/lab/sessions/delete-research',json={}).json()['technical_audit_retained'])
                self.assertEqual(a.get('/api/lab/sessions/export').json()['observations'],[])
                self.assertEqual(a.post('/api/lab/sessions/end',json={}).json()['status'],'ENDED')
                self.assertEqual(a.get('/api/lab/state').status_code,409)
                self.assertEqual(a.get('/api/lab/state',headers={'x-lab-session':'../bad'}).status_code,409)
    def test_sequential_switch_rejects_pending_work(self):
        with tempfile.TemporaryDirectory() as d:
            app=create_app(Path(d)/'state.db',start_worker=False)
            with TestClient(app) as client:
                client.post('/api/lab/sessions',json={'scenario':'confirmed'})
                source=client.get('/api/lab/state').json()['source_commit']
                client.post('/api/lab/changes',json={**change(),'source_commit':source})
                self.assertEqual(client.post('/api/lab/jobs',json={'change_id':'test','operation':'snapshot','mode':'LIVE RUN','idempotency_key':'one'}).status_code,202)
                self.assertEqual(client.post('/api/lab/sessions',json={'scenario':'stale'}).status_code,409)
                self.assertEqual(client.post('/api/lab/sessions/reset',json={}).status_code,409)
                self.assertEqual(client.post('/api/lab/sessions/end',json={}).status_code,409)

    def test_protected_mode_fails_closed(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'LAB_REQUIRE_AUTH':'true','LAB_AUTH_USERNAME':'operator','LAB_AUTH_PASSWORD':'test-only-password'}):
            with TestClient(create_app(Path(d)/'state.db',start_worker=False)) as client:
                self.assertEqual(client.get('/').status_code,401)
                self.assertEqual(client.get('/api/lab/state').status_code,401)
                self.assertEqual(client.get('/api/lab/state',auth=('operator','wrong')).status_code,401)
                import base64
                invalid=base64.b64encode('юзер:wrong'.encode()).decode()
                self.assertEqual(client.get('/api/lab/state',headers={'Authorization':'Basic '+invalid}).status_code,401)
                self.assertEqual(client.get('/api/lab/state',auth=('operator','test-only-password')).status_code,409)
                self.assertEqual(client.post('/api/lab/sessions',json={'scenario':'confirmed'},auth=('operator','test-only-password'),headers={'Origin':'https://other.invalid'}).status_code,403)
                self.assertEqual(client.post('/api/lab/sessions',json={'scenario':'confirmed'},auth=('operator','test-only-password')).status_code,200)
                self.assertEqual(client.get('/api/lab/state',auth=('operator','test-only-password')).status_code,200)
                os.environ['LAB_AUTH_PASSWORD']=''
                self.assertEqual(client.get('/api/lab/state',auth=('operator','')).status_code,401)
