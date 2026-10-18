import copy,unittest
from reconcile_access import guard_admin,ADMIN,GROUP
class ReconcileTests(unittest.TestCase):
 def plan(self):
  before={'security_group_id':GROUP,'port_range':'22:22','direction':'TRAFFIC_DIRECTION_INGRESS','ip_protocol':'IP_PROTOCOL_TCP','ether_type':'ETHER_TYPE_IPV4','remote_ip_prefix':'0.0.0.0/0'}
  return {'resource_changes':[{'address':ADMIN,'change':{'actions':['update'],'before':before,'after':{**before,'remote_ip_prefix':'192.0.2.1/32'}}}]}
 def test_exact_narrow_correction(self):self.assertEqual(guard_admin(self.plan(),'192.0.2.1/32')['after'],'EXISTING_STATE_PINNED_OPERATOR_/32')
 def test_vm_or_other_rule_is_never_allowed(self):
  p=self.plan();p['resource_changes'][0]['address']='cloudru_evolution_compute_vm.ui_vm'
  with self.assertRaises(ValueError):guard_admin(p,'192.0.2.1/32')
 def test_wide_wrong_operator_or_port_is_denied(self):
  for field,value in [('remote_ip_prefix','0.0.0.0/0'),('remote_ip_prefix','192.0.2.2/32'),('port_range','80:80')]:
   p=self.plan();p['resource_changes'][0]['change']['after'][field]=value
   with self.assertRaises(ValueError):guard_admin(p,'192.0.2.1/32')
if __name__=='__main__':unittest.main()
