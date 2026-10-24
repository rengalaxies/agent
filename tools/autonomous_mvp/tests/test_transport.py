import json
import time
import unittest
from unittest import mock

from tools.autonomous_mvp.transport import CloudRuTransport, interpret


def body(**choice):
    message = choice.pop("message", dict(role="assistant", content='{"action":"finish"}'))
    return json.dumps(dict(model="m", choices=[dict(index=0, finish_reason="stop", message=message, **choice)],
                           usage=dict(prompt_tokens=10, completion_tokens=2))).encode()


class Classification(unittest.TestCase):
    def test_http_200_with_one_string_choice_is_transport_success(self):
        r = interpret(200, body())
        self.assertEqual((r.ok, r.code, r.usage), (True, "ok", dict(prompt_tokens=10, completion_tokens=2)))

    def test_status_codes_map_to_distinct_transport_failures(self):
        self.assertEqual(interpret(429, b"").code, "http_rate_limited")
        self.assertEqual(interpret(401, b"").code, "http_unauthorized")
        self.assertEqual(interpret(403, b"").code, "http_unauthorized")
        self.assertEqual(interpret(502, b"").code, "http_server_error")
        self.assertEqual(interpret(400, b"").code, "http_error")

    def test_malformed_bodies_are_transport_failures_not_model_actions(self):
        self.assertEqual(interpret(200, b"<html>").code, "body_not_json")
        two = json.dumps(dict(choices=[{}, {}])).encode()
        self.assertEqual(interpret(200, two).code, "no_single_choice")

    def test_tool_call_without_content_is_reported_as_such(self):
        r = interpret(200, body(message=dict(role="assistant", content=None, tool_calls=[dict(id="1")])))
        self.assertEqual((r.ok, r.code, r.has_tool_calls), (False, "no_string_content", True))

    def test_truncated_output_is_delivered_with_its_finish_reason(self):
        raw = json.loads(body())
        raw["choices"][0]["finish_reason"] = "length"
        r = interpret(200, json.dumps(raw).encode())
        self.assertEqual((r.ok, r.finish_reason), (True, "length"))

    def test_safe_record_excludes_content(self):
        self.assertNotIn("content", interpret(200, body()).safe())

    def test_invalid_usage_is_unknown_not_zero(self):
        raw = json.loads(body())
        raw["usage"] = dict(prompt_tokens=-1, completion_tokens="2")
        self.assertIsNone(interpret(200, json.dumps(raw).encode()).usage)


class Guards(unittest.TestCase):
    def test_only_the_cloudru_https_endpoint_is_accepted(self):
        for url in ("http://foundation-models.api.cloud.ru/v1/chat/completions",
                    "https://evil.example/v1/chat/completions",
                    "https://user@foundation-models.api.cloud.ru/v1/chat/completions"):
            with self.assertRaises(ValueError):
                CloudRuTransport(endpoint=url)

    def test_missing_secret_fails_before_any_network_activity(self):
        t = CloudRuTransport()
        with mock.patch.dict("os.environ", {}, clear=True), \
                mock.patch("http.client.HTTPSConnection", side_effect=AssertionError("network")):
            r = t.complete(dict(model="m"), deadline=time.monotonic() + 5)
        self.assertEqual(r.code, "missing_secret")

    def test_secret_with_header_injection_is_refused(self):
        t = CloudRuTransport()
        with mock.patch.dict("os.environ", {"CLOUDRU_FOUNDATION_API_KEY": "abc\r\nX-Evil: 1"}), \
                mock.patch("http.client.HTTPSConnection", side_effect=AssertionError("network")):
            self.assertEqual(t.complete({}, deadline=time.monotonic() + 5).code, "missing_secret")

    def test_expired_deadline_sends_nothing(self):
        t = CloudRuTransport()
        with mock.patch.dict("os.environ", {"CLOUDRU_FOUNDATION_API_KEY": "k" * 20}), \
                mock.patch("http.client.HTTPSConnection", side_effect=AssertionError("network")):
            self.assertEqual(t.complete({}, deadline=time.monotonic() - 1).code, "deadline_before_send")


if __name__ == "__main__":
    unittest.main()
