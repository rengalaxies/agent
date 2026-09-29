import unittest
import copy
try:
    import cryptography
except ImportError:
    cryptography=None

@unittest.skipUnless(cryptography,'install distributed extra for signed-domain tests')
class DistributedPolicyTests(unittest.TestCase):
    def setUp(self):
        from datamesh_release_protocol.stand.fixtures import catalog,ROUTES
        from datamesh_release_protocol.stand.protocol import keypair,WorkItem,make_vote,owned_records,sign
        self.store,self.snapshots=catalog();self.snapshot=self.snapshots['ACCEPT'];self.routes=ROUTES;self.private={};self.public={};self.messages=[]
        for domain in ('sales','risk','analytics'):
            private,public=keypair();self.private[domain]=private;self.public[domain]=public
            work=WorkItem(event_id=domain,run_id='test',snapshot=self.snapshot)
            for kind in ('VERDICT','FENCE'):
                vote=make_vote(work,domain,ROUTES,owned_records(self.snapshot,domain,ROUTES),kind)
                from datamesh_release_protocol.knowledge import digest
                vote.event_id=digest(vote.model_dump(mode='json',exclude={'event_id'}))
                self.messages.append(sign(vote,private).model_dump(mode='json'))
    def projection(self,messages):
        from datamesh_release_protocol.stand.policy import project
        return project(self.snapshot,'test',[],messages,self.public,self.routes,True)
    def test_complete_accept_and_duplicate_invariance(self):
        a=self.projection(self.messages);b=self.projection(self.messages*5);self.assertEqual(a,b);self.assertEqual(a['decision'].value,'ACCEPT')
    def test_missing_mandatory_reply_never_accepts(self):
        p=self.projection([m for m in self.messages if m['vote']['domain_id']!='risk']);self.assertEqual(p['decision'].value,'NEEDS_REVIEW');self.assertIn('deadline_expired',p['reasons'])
    def test_accept_requires_all_revision_fences(self):
        p=self.projection([m for m in self.messages if not(m['vote']['domain_id']=='risk' and m['vote']['kind']=='FENCE')]);self.assertEqual(p['decision'].value,'NEEDS_REVIEW')
    def test_signature_tamper_cannot_supply_mandatory_vote(self):
        messages=copy.deepcopy(self.messages)
        for m in messages:
            if m['vote']['domain_id']=='risk':m['signature']='00'*64
        self.assertEqual(self.projection(messages)['decision'].value,'NEEDS_REVIEW')
    def test_signed_wrong_binding_is_ignored(self):
        from datamesh_release_protocol.stand.protocol import SignedMessage,sign
        from datamesh_release_protocol.knowledge import digest
        for field,value in (('run_id','other'),('snapshot_id','other'),('new_contract_version','wrong'),('membership_epoch',77)):
            with self.subTest(field=field):
                messages=copy.deepcopy(self.messages)
                for index,m in enumerate(messages):
                    if m['vote']['domain_id']=='risk':
                        vote=SignedMessage.model_validate(m).vote;setattr(vote,field,value);vote.event_id=digest(vote.model_dump(mode='json',exclude={'event_id'}));messages[index]=sign(vote,self.private['risk']).model_dump(mode='json')
                self.assertEqual(self.projection(messages)['decision'].value,'NEEDS_REVIEW')
    def test_signed_revision_change_aborts(self):
        from datamesh_release_protocol.stand.protocol import SignedMessage,sign
        from datamesh_release_protocol.knowledge import digest
        messages=copy.deepcopy(self.messages)
        vote=SignedMessage.model_validate(messages[3]).vote;vote.revision='changed';vote.event_id=digest(vote.model_dump(mode='json',exclude={'event_id'}));messages[3]=sign(vote,self.private['risk']).model_dump(mode='json')
        self.assertTrue(self.projection(messages)['abort'])
