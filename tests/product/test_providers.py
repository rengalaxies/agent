import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import unittest

from change_completion.providers import ClientPatchProvider


class ProviderTest(unittest.TestCase):
    def setUp(self):
        self.requests = []
        self.response = {"candidate": "SELECT SUM(amount) AS total FROM events WHERE age_days < 90;"}
        self.redirect = False
        owner = self
        class Gateway(BaseHTTPRequestHandler):
            def do_POST(inner):
                owner.requests.append(json.loads(inner.rfile.read(int(inner.headers["Content-Length"]))))
                if owner.redirect:
                    inner.send_response(302)
                    inner.send_header("Location", "/other")
                    inner.end_headers()
                    return
                payload = json.dumps(owner.response).encode()
                inner.send_response(200)
                inner.send_header("Content-Length", str(len(payload)))
                inner.end_headers()
                inner.wfile.write(payload)
            def log_message(self, *args):
                pass
        self.server = HTTPServer(("127.0.0.1", 0), Gateway)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.endpoint = f"http://127.0.0.1:{self.server.server_port}/patch"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

    def provider(self, **changes):
        data = dict(endpoint=self.endpoint, model="fixture-gateway", allowed_endpoints=frozenset({self.endpoint}),
                    allow_source_transfer=True, allow_loopback_http=True)
        data.update(changes)
        return ClientPatchProvider(**data)

    def test_route_requires_consent_and_allowlist(self):
        for changes in ({"allow_source_transfer": False}, {"allowed_endpoints": frozenset()}, {"allow_loopback_http": False}):
            with self.assertRaises(ValueError):
                self.provider(**changes)
        self.assertFalse(self.requests)

    def test_only_source_and_intent_leave_process(self):
        result = self.provider().propose("SELECT amount FROM events WHERE age_days < 30;", old_window=30, new_window=90)
        self.assertEqual(result["status"], "prepared")
        self.assertEqual(set(self.requests[0]), {"model", "source", "intent"})
        self.assertEqual(set(self.requests[0]["intent"]), {"old_window", "new_window"})

    def test_forged_observation_or_expected_payload_rejected(self):
        self.response = {"candidate": "SELECT 1", "actual": [[999]], "expected": [[999]], "status": "PASS"}
        result = self.provider().propose("SELECT 1", old_window=30, new_window=90)
        self.assertEqual(result["status"], "unsupported")

    def test_redirect_not_followed(self):
        self.redirect = True
        result = self.provider().propose("SELECT 1", old_window=30, new_window=90)
        self.assertEqual(result["status"], "unsupported")
        self.assertEqual(len(self.requests), 1)
