import unittest
from network_diagnosis import rule_match,safe_network,public_rule
class NetworkTests(unittest.TestCase):
 def test_runner_source_port_and_direction_are_distinct(self):
  r={'direction':'ingress','ip_protocol':'tcp','port_range':'22:22','remote_ip_prefix':'192.0.2.1/32'}
  self.assertTrue(rule_match(r,'192.0.2.1',22));self.assertFalse(rule_match(r,'192.0.2.2',22));self.assertFalse(rule_match(r,'192.0.2.1',443));self.assertFalse(rule_match({**r,'direction':'egress'},'192.0.2.1',22))
 def test_group_selector_is_not_proof_of_public_access(self):
  self.assertIsNone(rule_match({'direction':'ingress','ip_protocol':'tcp','port_range':'22:22','remote_security_group':{'id':'other'}},'192.0.2.1',22))
 def test_actual_floating_ip_interface_schema_and_secret_exclusion(self):
  d=safe_network({'interface':{'id':'expected'},'ip_address':'192.0.2.2','remote_console_url':'TOKEN','metadata_fields':{'private':'SECRET'}})
  self.assertEqual(d['interface']['id'],'expected');self.assertNotIn('TOKEN',str(d));self.assertNotIn('SECRET',str(d))
if __name__=='__main__':unittest.main()
