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

class LiveAttachmentGuardTests(unittest.TestCase):
 def test_exact_live_attachment_required_without_provider_refresh(self):
  from scoped_ssh import validate_live_attachment,PROJECT,GROUP
  selected={'ui_nic_id':'nic','ui':{'id':'vm'},'ui_ip':'192.0.2.4'}
  nic={'id':'nic','project':{'id':PROJECT},'vm':{'id':'vm'},'security_groups':[{'id':GROUP}],'floating_ip':{'ip_address':'192.0.2.4'}}
  group={'id':GROUP,'name':'dm-p1-ui','project':{'id':PROJECT},'availability_zone':{'name':'ru.AZ-2'}}
  self.assertEqual(validate_live_attachment(nic,group,selected)['group_id'],GROUP)
  for altered in [{**nic,'security_groups':[]},{**nic,'vm':{'id':'other'}},{**nic,'floating_ip':{'ip_address':'192.0.2.5'}},{**nic,'project':{'id':'other'}}]:
   with self.assertRaisesRegex(ValueError,'LIVE_NIC_GROUP_ATTACHMENT_MISMATCH'):validate_live_attachment(altered,group,selected)
