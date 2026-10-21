import io
import contextlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import urllib.error
import urllib.response
from email.message import Message
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

    def test_catalog_reports_each_requested_model_independently(self):
        for ids in ([], [probe.TARGET], ["openai/gpt-oss-120b"], list(probe.CATALOG_MODELS)):
            with self.subTest(ids=ids):
                transport = MagicMock(return_value=({"http_status": 200}, {
                    "data": [{"id": model} for model in ids]}))
                # Catalog must not generate even if approval vars are already set.
                env = dict(self.env, FM_BUDGET_APPROVED="true", FM_GRANT_CONFIRMED="true")
                result = probe.probe("catalog", env, transport)
                self.assertEqual(result["catalog"]["models_available"],
                                 {model: model in ids for model in probe.CATALOG_MODELS})
                self.assertEqual(result["catalog"]["http_status"], 200)
                self.assertEqual(result["generation"]["result"], "NOT_RUN")
                transport.assert_called_once_with("/models", "DO-NOT-EMIT-KEY")

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

    def test_real_opener_rejects_redirects_before_sending_key_elsewhere(self):
        # Keep the real opener/error/redirect chain; replace only HTTPS I/O.
        for status in (301, 302, 303, 307, 308):
            requests = []

            def reply(handler, request):
                requests.append(request)
                headers = Message()
                headers["Location"] = "https://third-party.invalid/DO-NOT-EMIT-KEY"
                response = urllib.response.addinfourl(
                    io.BytesIO(b"DO-NOT-EMIT-KEY"), headers, request.full_url, status)
                response.msg = "fixture"
                return response

            with self.subTest(status=status), patch.object(
                urllib.request.HTTPSHandler, "https_open", reply
            ), patch("socket.create_connection", side_effect=AssertionError("real network")):
                row, data = probe.request_json("/models", "DO-NOT-EMIT-KEY")
                self.assertEqual(row, {"result": "HTTP_ERROR", "http_status": status})
                self.assertIsNone(data)
                self.assertEqual(len(requests), 1)
                self.assertEqual(requests[0].full_url,
                                 "https://foundation-models.api.cloud.ru/v1/models")
                self.assertEqual(requests[0].get_method(), "GET")
                self.assertIsNone(requests[0].data)

    def test_cli_preflight_and_catalog_outputs_are_safe(self):
        # Exercise actual serialization, exit codes and files with a synthetic key.
        cases = [
            ("preflight", "", None, "BLOCKED_MISSING_FOUNDATION_KEY", 1),
            ("preflight", "DO-NOT-EMIT-KEY", None, "CONFIG_PRESENT_ACCESS_UNTESTED", 0),
            ("catalog", "", None, "BLOCKED_MISSING_FOUNDATION_KEY", 1),
            ("catalog", "DO-NOT-EMIT-KEY",
             b'{"data":[{"id":"Qwen/Qwen3-Coder-Next"},{"id":"DO-NOT-EMIT-KEY"}],"secret":"DO-NOT-EMIT-KEY"}',
             "TARGET_LISTED_INFERENCE_UNTESTED", 0),
            ("catalog", "DO-NOT-EMIT-KEY", b'[]', "BLOCKED_CATALOG", 1),
            ("catalog", "DO-NOT-EMIT-KEY", b'DO-NOT-EMIT-KEY', "BLOCKED_CATALOG", 1),
        ]
        for mode, key, body, result, exit_code in cases:
            requests = []

            def reply(handler, request):
                requests.append(request)
                self.assertEqual(request.full_url,
                                 "https://foundation-models.api.cloud.ru/v1/models")
                self.assertEqual(request.get_method(), "GET")
                self.assertIsNone(request.data)
                self.assertEqual(request.get_header("Authorization"), "Bearer DO-NOT-EMIT-KEY")
                response = urllib.response.addinfourl(
                    io.BytesIO(body), Message(), request.full_url, 200)
                response.msg = "fixture"
                return response

            with self.subTest(mode=mode, result=result), tempfile.TemporaryDirectory() as tmp:
                stdout, stderr = io.StringIO(), io.StringIO()
                env = dict(self.env, CLOUDRU_FOUNDATION_API_KEY=key,
                           FM_BUDGET_APPROVED="true", FM_GRANT_CONFIRMED="true")
                # Windows OpenSSL needs SYSTEMROOT even with mocked HTTPS I/O.
                if "SYSTEMROOT" in os.environ:
                    env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]
                previous = Path.cwd()
                try:
                    os.chdir(tmp)
                    with patch.dict(os.environ, env, clear=True), patch(
                        "sys.argv", ["probe.py", "--mode", mode]
                    ), patch.object(urllib.request.HTTPSHandler, "https_open", reply), patch(
                        "socket.create_connection", side_effect=AssertionError("real network")
                    ), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                        self.assertEqual(probe.main(), exit_code)
                    report_text = Path("foundation-models-report.json").read_text()
                    self.assertEqual(json.loads(report_text)["result"], result)
                    self.assertEqual(stdout.getvalue(), report_text)
                    self.assertNotIn("DO-NOT-EMIT", report_text + stderr.getvalue())
                    self.assertEqual(stderr.getvalue(), "")
                    self.assertEqual(len(requests), int(mode == "catalog" and bool(key)))
                    self.assertEqual([p.name for p in Path(tmp).iterdir()],
                                     ["foundation-models-report.json"])
                finally:
                    os.chdir(previous)

    @patch("probe.urllib.request.build_opener")
    def test_transport_exceptions_do_not_disclose_credentials(self, build):
        for error in (TimeoutError("DO-NOT-EMIT-KEY"),
                      urllib.error.URLError("DO-NOT-EMIT-KEY"),
                      UnicodeError("DO-NOT-EMIT-KEY")):
            with self.subTest(error=type(error).__name__):
                build.return_value.open.side_effect = error
                row, data = probe.request_json("/models", "DO-NOT-EMIT-KEY")
                self.assertIsNone(data)
                self.assertNotIn("DO-NOT-EMIT", json.dumps(row))


if __name__ == "__main__":
    unittest.main()
