import unittest
try:
    import httpx
    from datamesh_release_protocol.knowledge_api import create_knowledge_app
    API=True
except ImportError:
    API=False
from tests.test_knowledge import fixture

@unittest.skipUnless(API,'install project api extra and httpx for API tests')
class KnowledgeAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.store,self.old,self.new=fixture()
        self.client=httpx.AsyncClient(transport=httpx.ASGITransport(app=create_knowledge_app(self.store,{'producer-token':'producer','consumer-token':'consumer'})),base_url='http://test')
        self.p={'Authorization':'Bearer producer-token'};self.c={'Authorization':'Bearer consumer-token'}
    async def test_authentication_required(self):
        self.assertEqual((await self.client.get('/snapshots/absent')).status_code,401)
    async def test_domain_authority(self):
        r=await self.client.post('/records/obligation/confirm',headers=self.p,json={'evidence_ref':'fake'})
        self.assertEqual(r.status_code,403)
    async def test_snapshot_release_and_replay(self):
        r=await self.client.post('/snapshots',headers=self.p,json={'proposal_id':'p','old_contract':self.old.model_dump(mode='json'),'new_contract':self.new.model_dump(mode='json')})
        self.assertEqual(r.status_code,200);sid=r.json()['snapshot_id']
        body={'snapshot_id':sid,'run_id':'run'}
        r=await self.client.post('/release',headers=self.p,json=body);self.assertEqual(r.status_code,200)
        self.assertEqual(r.json()['terminal_state'],'COMMITTED')
        self.assertEqual(r.json(),(await self.client.post('/release',headers=self.p,json=body)).json())
        self.assertEqual((await self.client.post('/release',headers=self.c,json=body)).status_code,403)
    async def test_spoofed_actor_forbidden(self):
        r=await self.client.post('/records/obligation/confirm',headers=self.c,json={'evidence_ref':'x','actor':'producer'})
        self.assertEqual(r.status_code,422)
    async def test_revocation_fences_release(self):
        r=await self.client.post('/snapshots',headers=self.p,json={'proposal_id':'p','old_contract':self.old.model_dump(mode='json'),'new_contract':self.new.model_dump(mode='json')})
        sid=r.json()['snapshot_id']
        self.assertEqual((await self.client.post('/records/obligation/revoke',headers=self.c,json={'evidence_ref':'revoked'})).status_code,200)
        r=await self.client.post('/release',headers=self.p,json={'snapshot_id':sid,'run_id':'run'})
        self.assertEqual(r.json()['terminal_state'],'ABORTED');self.assertIsNone(r.json()['release_id'])

    async def asyncTearDown(self):
        await self.client.aclose()

    async def test_journal_pending_ack_routes(self):
        r=await self.client.post('/snapshots',headers=self.p,json={'proposal_id':'p','old_contract':self.old.model_dump(mode='json'),'new_contract':self.new.model_dump(mode='json')})
        sid=r.json()['snapshot_id'];r=await self.client.post('/release',headers=self.p,json={'snapshot_id':sid,'run_id':'durable'})
        rid=r.json()['release_id']
        self.assertEqual(len((await self.client.get('/publications/pending',headers=self.p)).json()),1)
        self.assertEqual((await self.client.post(f'/publications/{rid}/ack',headers=self.c,json={'evidence_ref':'receipt'})).status_code,403)
        self.assertEqual((await self.client.post(f'/publications/{rid}/ack',headers=self.p,json={'evidence_ref':'receipt'})).status_code,200)
        self.assertEqual((await self.client.get('/publications/pending',headers=self.p)).json(),[])
        self.assertEqual((await self.client.get('/runs/durable',headers=self.p)).json()['release_id'],rid)
        self.assertEqual(len((await self.client.get('/release-journal',headers=self.p)).json()),2)
