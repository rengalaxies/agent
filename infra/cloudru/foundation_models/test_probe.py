import io
import json
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import probe


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.env = {"CLOUDRU_FOUNDATION_API_KEY": "DO-NOT-EMIT-KEY"}

    def test_preflight_never_calls_network(self):
        transport = MagicMock(side_effect=AssertionError("network"))
        result = probe.probe("preflight", self.env, transport)
        self.assertEqual(result["result"], "CONFIG_PRESENT_ACCESS_UNTESTED")
        transport.assert_not_called()

    def test_no_infrastructure_or_workflow_key_fallback(self):
        transport = MagicMock()
        result = probe.probe("catalog", {"CLOUDRU_SECRET": "x", "CLOUDRU_WORKFLOW_API_KEY": "x"}, transport)
        self.assertEqual(result["result"], "BLOCKED_MISSING_FOUNDATION_KEY")
        transport.assert_not_called()

    def test_generation_requires_both_confirmations_before_network(self):
        for extra in ({}, {"FM_BUDGET_APPROVED": "true"}, {"FM_GRANT_CONFIRMED": "true"}):
            transport = MagicMock()
            result = probe.probe("generate", dict(self.env, **extra), transport)
            self.assertEqual(result["result"], "BLOCKED_BUDGET_OR_GRANT_UNCONFIRMED")
            transport.assert_not_called()

    def test_catalog_never_generates_or_serializes_arbitrary_content(self):
        transport = MagicMock(return_value=({"http_status": 200, "result": "HTTP_OK"}, {
            "data": [{"id": probe.TARGET}, {"id": self.env["CLOUDRU_FOUNDATION_API_KEY"]}],
            "secret": self.env["CLOUDRU_FOUNDATION_API_KEY"]}))
        result = probe.probe("catalog", self.env, transport)
        self.assertTrue(result["catalog"]["target_available"])
        self.assertEqual(transport.call_count, 1)
        self.assertNotIn("DO-NOT-EMIT", json.dumps(result))

    def test_missing_or_malformed_catalog_blocks_generation(self):
        env = dict(self.env, FM_BUDGET_APPROVED="true", FM_GRANT_CONFIRMED="true")
        for data in ({"data": []}, {"data": "bad"}, {}):
            transport = MagicMock(return_value=({"http_status": 200}, data))
            result = probe.probe("generate", env, transport)
            self.assertEqual(transport.call_count, 1)
            self.assertEqual(result["generation"]["result"], "NOT_RUN")

    def test_generation_is_fixed_and_bounded(self):
        env = dict(self.env, FM_BUDGET_APPROVED="true", FM_GRANT_CONFIRMED="true")
        transport = MagicMock(side_effect=[
            ({"http_status": 200}, {"data": [{"id": probe.TARGET}]}),
            ({"http_status": 200}, {"model": probe.TARGET, "choices": [{"message": "DO-NOT-EMIT-KEY"}]})])
        result = probe.probe("generate", env, transport)
        self.assertEqual(result["result"], "PASS_GENERATION")
        self.assertEqual(transport.call_count, 2)
        payload = transport.call_args.args[2]
        self.assertEqual(payload["max_completion_tokens"], 16)
        self.assertEqual(payload["model"], probe.TARGET)
        self.assertFalse(payload["stream"])
        self.assertNotIn("DO-NOT-EMIT", json.dumps(result))

    @patch("probe.urllib.request.build_opener")
    def test_http_errors_expose_only_status_and_never_retry(self, build):
        build.return_value.open.side_effect = urllib.error.HTTPError(
            probe.BASE, 403, "DO-NOT-EMIT-KEY", {"Authorization": "secret"}, io.BytesIO(b"secret"))
        row, data = probe.request_json("/models", "key")
        self.assertEqual(row, {"result": "HTTP_ERROR", "http_status": 403})
        self.assertIsNone(data)
        self.assertEqual(build.return_value.open.call_count, 1)

    def test_redirect_is_not_followed(self):
        self.assertIsNone(probe.NoRedirect().redirect_request(None, None, 302, "", {}, "https://evil.invalid"))

    @patch("probe.urllib.request.build_opener")
    def test_timeout_and_oversize_are_bounded(self, build):
        response = build.return_value.open.return_value.__enter__.return_value
        response.status = 200
        response.read.return_value = b"x" * (probe.MAX_BYTES + 1)
        row, _ = probe.request_json("/models", "key")
        self.assertEqual(row["result"], "RESPONSE_TOO_LARGE")
        response.read.assert_called_once_with(probe.MAX_BYTES + 1)
        self.assertEqual(build.return_value.open.call_args.kwargs["timeout"], 20)


if __name__ == "__main__":
    unittest.main()
