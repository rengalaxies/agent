import unittest
from unittest.mock import Mock
from http_client import ReadClient
class ReadBoundary(unittest.TestCase):
 def test_compute_mutation_never_sent_or_retried(self):
  c=ReadClient({});c.session=Mock()
  with self.assertRaisesRegex(ValueError,'MUTATION_RETRY_FORBIDDEN'):c.post('https://compute.api.cloud.ru/api/v1/security-groups',json={})
  c.session.request.assert_not_called()
 def test_foreign_credential_target_never_contacted(self):
  c=ReadClient({});c.session=Mock()
  with self.assertRaisesRegex(ValueError,'UNEXPECTED_READ_SERVICE'):c.post('https://other.example/api/v1/auth/token',json={'secret':'test'})
  c.session.request.assert_not_called()
 def test_token_redirect_does_not_forward_body(self):
  c=ReadClient({});c.session=Mock();c.session.request.return_value.raw.retries.history=()
  c.post('https://iam.api.cloud.ru/api/v1/auth/token',json={'secret':'test'})
  self.assertFalse(c.session.request.call_args.kwargs['allow_redirects'])
