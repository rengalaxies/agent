import copy
import unittest
from scoped_ssh import ADDRESS, GROUP, guard

class PlanGuardTests(unittest.TestCase):
    def plan(self):
        return {'resource_changes':[{'address':ADDRESS,'change':{'actions':['create'],'after':{
            'security_group_id':GROUP,'remote_ip_prefix':'8.8.8.8/32','port_range':'22:22',
            'direction':'TRAFFIC_DIRECTION_INGRESS','ip_protocol':'IP_PROTOCOL_TCP','ether_type':'ETHER_TYPE_IPV4'}}}]}
    def test_only_new_exact_runner_rule(self):
        self.assertEqual(guard(self.plan(),'8.8.8.8/32',True)['actions'],['create'])
    def test_replacement_other_resource_and_broad_access_rejected(self):
        for kind in ['replace','vm','broad','group']:
            p=copy.deepcopy(self.plan());c=p['resource_changes'][0]
            if kind=='replace':c['change']['actions']=['delete','create']
            if kind=='vm':c['address']='cloudru_evolution_compute_vm.ui_vm'
            if kind=='broad':c['change']['after']['remote_ip_prefix']='0.0.0.0/0'
            if kind=='group':c['change']['after']['security_group_id']='other'
            with self.subTest(kind=kind),self.assertRaises(ValueError):guard(p,'8.8.8.8/32',True)
    def test_cleanup_only_own_rule(self):
        p=self.plan();c=p['resource_changes'][0]['change'];c['before']=c.pop('after');c['actions']=['delete']
        self.assertEqual(guard(p,'8.8.8.8/32',False)['actions'],['delete'])
