import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from threading import Thread
import time
import unittest
from unittest.mock import patch

from change_completion.delivery import DeliveryConfig, GatewayDelivery


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.mode = "ok"
        self.key = hashlib.sha256(b"transition/candidate/recipient").hexdigest()
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(inner):
                request = json.loads(inner.rfile.read(int(inner.headers["Content-Length"])))
                owner.calls.append((request, dict(inner.headers)))
                if owner.mode == "timeout":
                    time.sleep(.15)
                if owner.mode == "redirect":
                    inner.send_response(307)
                    inner.send_header("Location", owner.endpoint)
                    inner.end_headers()
                    return
                value = {"idempotency_key": request["idempotency_key"], "receipt": {
                    "url": "https://client.example/pull/1", "external_id": "1"}}
                if owner.mode == "wrong_key":
                    value["idempotency_key"] = "0" * 64
                if owner.mode == "unsafe_url":
                    value["receipt"]["url"] = "javascript:alert(1)"
                raw = json.dumps(value).encode()
                if owner.mode == "oversized":
                    raw = b" " * 65_537
                if owner.mode == "malformed":
                    raw = b"not-json"
                inner.send_response(200)
                inner.send_header("Content-Length", str(len(raw)))
                inner.end_headers()
                try:
                    inner.wfile.write(raw)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/deliver"
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def sender(self, **kwargs):
        settings = dict(endpoint=self.endpoint, allowed_endpoints=frozenset({self.endpoint}),
                        allow_send=True, allow_loopback_http=True)
        settings.update(kwargs)
        return GatewayDelivery(DeliveryConfig(**settings))

    def test_default_is_draft_without_network(self):
        for sender in (GatewayDelivery(DeliveryConfig()), self.sender(allow_send=False),
                       self.sender(endpoint=None)):
            self.assertEqual(sender.send("pull_request", {}, self.key)["status"], "draft")
        self.assertEqual(self.calls, [])

    def test_explicit_send_preserves_key_and_payload(self):
        payload = {"title": "review", "diff": "approved disclosure"}
        sender = self.sender(api_key="explicit-token")
        response = sender.send("pull_request", payload, self.key)
        self.assertEqual(response["status"], "delivered")
        self.assertEqual(response["receipt"]["external_id"], "1")
        body, headers = self.calls[0]
        self.assertEqual(body, {"kind": "pull_request", "idempotency_key": self.key,
                                "payload": payload})
        self.assertEqual(headers["Idempotency-Key"], self.key)
        self.assertEqual(headers["Authorization"], "Bearer explicit-token")
        self.assertNotIn("explicit-token", repr(sender.config))

    def test_no_ambient_proxy_or_credentials(self):
        with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1",
                                     "HTTPS_PROXY": "http://127.0.0.1:1",
                                     "GITHUB_TOKEN": "ambient-secret"}):
            self.assertEqual(self.sender().send("notification", {}, self.key)["status"], "delivered")
        self.assertNotIn("Authorization", self.calls[0][1])
        self.assertNotIn("ambient-secret", json.dumps(self.calls))

    def test_endpoint_scope_and_https_required(self):
        for kwargs in ({"allowed_endpoints": frozenset()}, {"allow_loopback_http": False},
                       {"endpoint": self.endpoint + "/different"}):
            self.assertEqual(self.sender(**kwargs).send("notification", {}, self.key)["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_bad_inputs_block_before_network(self):
        self.assertEqual(self.sender().send("delete", {}, self.key)["status"], "blocked")
        self.assertEqual(self.sender().send("notification", {}, "private-user-name")["status"], "blocked")
        self.assertEqual(self.sender().send("notification", {"n": float("nan")}, self.key)["status"], "blocked")
        self.assertEqual(self.sender().send("notification", {"x": "a" * 1_048_576}, self.key)["status"], "blocked")
        for timeout in (0, 11, float("nan"), True):
            self.assertEqual(self.sender(timeout=timeout).send("notification", {}, self.key)["status"], "blocked")
        self.assertEqual(self.calls, [])

    def test_receipts_and_redirects_are_unknown_without_retry(self):
        for mode in ("wrong_key", "unsafe_url", "oversized", "malformed", "redirect"):
            with self.subTest(mode=mode):
                self.mode = mode
                before = len(self.calls)
                result = self.sender().send("pull_request", {}, self.key)
                self.assertEqual(result["status"], "unknown")
                self.assertIsNone(result["receipt"])
                self.assertEqual(len(self.calls), before + 1)

    def test_timeout_is_unknown_not_retried(self):
        self.mode = "timeout"
        self.assertEqual(self.sender(timeout=.03).send("notification", {}, self.key)["status"], "unknown")
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
