import copy
import json
import unittest
import tempfile
from lab.runtime.core import now
from unittest.mock import patch
from lab.product.collectors import basis_digest, collect, rabbit_snapshot, repository_snapshot
from lab.runtime.core import Stop
from pathlib import Path


class CollectorTests(unittest.TestCase):
    def material(self):
        return ({'schemas':[{'name':'public'}],'columns':[], 'views':[], 'dependencies':[]},
                {'exchanges':[{'name':'orders.events'}],'queues':[{'name':'billing'}],
                 'bindings':[{'source':'orders.events','destination':'billing','routing_key':'order.created.v1'}]},
                {'snapshot_digest':'repository-hash'}, {'bindings':[]})

    def test_digest_stable_collection_time_and_runtime_statistics(self):
        material = self.material()
        before = basis_digest(*material)
        changed = copy.deepcopy(material)
        changed[0]['collected_at']='tomorrow'
        changed[1]['collected_at']='tomorrow'
        changed[1]['messages']=1234
        self.assertEqual(before,basis_digest(*changed))

    def test_binding_schema_repository_or_owner_change_invalidates_basis(self):
        material = self.material()
        before = basis_digest(*material)
        for index,key,value in [(0,'columns',[{'column':'amount_minor'}]),(1,'bindings',[]),
                                 (2,'snapshot_digest','new-code'),(3,'bindings',[{'team_id':'new-team'}])]:
            changed = copy.deepcopy(material)
            changed[index][key]=value
            self.assertNotEqual(before,basis_digest(*changed))

    def test_missing_live_credentials_blocks_instead_of_fixture(self):
        with patch.dict('os.environ',{},clear=True), self.assertRaisesRegex(Stop,'BLOCKED'):
            collect()

    def test_bad_endpoint_refuses_credentials_in_url(self):
        with self.assertRaises(Stop):
            rabbit_snapshot('http://user:secret@rabbit:15672','u','p')

    def test_repository_references_are_static_and_declared(self):
        repo = repository_snapshot(Path(__file__).resolve().parents[3])
        self.assertTrue(repo['evidence'])
        self.assertTrue(any(dep['relation_type']=='BROKER_CODE_REFERENCE' for dep in repo['dependencies']))
        self.assertTrue(all(dep['confirmation']!='OBSERVED_INTERACTION' for dep in repo['dependencies']))
        self.assertTrue(all('content' not in evidence for evidence in repo['evidence']))

    def test_monitor_cannot_collect_without_independent_permission_attestation(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return b'{"name":"reader","tags":["monitoring"]}'
        class Opener:
            def open(self,*args,**kwargs): return Response()
        with patch('urllib.request.build_opener',return_value=Opener()), patch.dict('os.environ',{},clear=True):
            with self.assertRaisesRegex(Stop,'attestation missing'):
                rabbit_snapshot('http://rabbit:15672','reader','secret')

    def test_http_is_only_get_and_volatile_broker_stats_are_removed(self):
        calls=[]
        class Response:
            def __init__(self,value): self.value=value
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def read(self,*args): return json.dumps(self.value).encode()
        class Opener:
            def open(self,request,timeout):
                calls.append(request)
                if '/whoami' in request.full_url: return Response({'name':'reader','tags':['monitoring']})
                if '/overview' in request.full_url: return Response({'node':'rabbit@test'})
                return Response([{'name':'billing','messages':19,'message_stats':{'publish':99}}])
        with tempfile.TemporaryDirectory() as directory:
            attestation=Path(directory)/'permission.json'
            attestation.write_text(json.dumps({'username':'reader','vhost':'/','configure':'^$','write':'^$','read':'^$',
                'broker_identity':'rabbit@test','collected_at':now(),'source':'trusted CI rabbitmqctl list_user_permissions'}))
            with patch('urllib.request.build_opener',return_value=Opener()), patch.dict('os.environ',{'RABBIT_PERMISSION_ATTESTATION_FILE':str(attestation)}):
                result=rabbit_snapshot('http://rabbit:15672','reader','secret')
        self.assertTrue(all(call.get_method()=='GET' for call in calls))
        self.assertNotIn('messages',json.dumps(result))
        self.assertNotIn('secret',json.dumps(result))


if __name__=='__main__': unittest.main()
