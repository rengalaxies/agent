import os,unittest
from unittest.mock import MagicMock,patch
from preflight import open_ssh_socket
class ProxyTests(unittest.TestCase):
 def fake(self,response):
  sock=MagicMock();sock.recv.side_effect=[bytes([x]) for x in response];return sock
 def test_connect_rejection_stops_before_ssh_and_closes_socket(self):
  sock=self.fake(b'HTTP/1.1 403 Forbidden\r\n\r\n')
  with patch.dict(os.environ,{'CLOUDRU_SSH_USE_PROXY':'1'}),patch('urllib.request.getproxies',return_value={'https':'http://test-user:test-pass@proxy.invalid:3128'}),patch('preflight.socket.create_connection',return_value=sock):
   with self.assertRaisesRegex(ValueError,'HOST_PROXY_CONNECT_REJECTED_403'):open_ssh_socket('192.0.2.1')
  sock.close.assert_called_once();self.assertIn(b'CONNECT 192.0.2.1:22',sock.sendall.call_args[0][0])
 def test_headers_do_not_consume_the_ssh_banner(self):
  header=b'HTTP/1.1 200 Connection Established\r\n\r\n';sock=self.fake(header+b'SSH-2.0-test')
  with patch.dict(os.environ,{'CLOUDRU_SSH_USE_PROXY':'1'}),patch('urllib.request.getproxies',return_value={'https':'http://proxy.invalid:3128'}),patch('preflight.socket.create_connection',return_value=sock):
   self.assertIs(open_ssh_socket('192.0.2.1'),sock)
  self.assertEqual(sock.recv.call_count,len(header));self.assertEqual(sock.recv(1),b'S')
if __name__=='__main__':unittest.main()
