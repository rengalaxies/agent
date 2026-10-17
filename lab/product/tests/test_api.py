import tempfile
import unittest
from pathlib import Path
from fastapi.testclient import TestClient
from lab.product.api import create_app
from lab.product.tests.test_store import change

class APITests(unittest.TestCase):
    def test_server_gate_and_async_queue(self):
        with tempfile.TemporaryDirectory() as d:
            app=create_app(Path(d)/'state.db',Path(d)/'artifacts',start_worker=False)
            with TestClient(app) as client:
                self.assertEqual(client.post('/api/lab/changes',json=change()).status_code,200)
                r=client.post('/api/lab/jobs',json=dict(change_id='test',operation='snapshot',mode='LIVE RUN',idempotency_key='one'))
                self.assertEqual(r.status_code,202);self.assertEqual(r.json()['status'],'QUEUED')
                self.assertEqual(client.post('/api/lab/apply',json={'role':'initiator','approved':True}).status_code,403)
                self.assertFalse(client.get('/api/lab/state').json()['execution_permission'])
                self.assertTrue(client.get('/api/lab/healthz').json()['demo_roles'])
