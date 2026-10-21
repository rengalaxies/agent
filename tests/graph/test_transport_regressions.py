"""R1/R5 regressions: synthetic HTTP only, no real model or paid endpoint."""
from contextlib import contextmanager
import http.server
import json
import http.client
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import socket
import ssl
from unittest.mock import patch

from agent_graph.contracts import GraphError, ModelConfig
from agent_graph.engine import Graph
from agent_graph.inference import ChatModel, investigate
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/agent_graph"))
from fixture import create_fixture


def config(url, **kwargs):
    return ModelConfig(endpoint=url, allowed_endpoints=[url], model="regression-stub",
                       configuration_id="not-a-qualified-model", allow_source_transfer=True, **kwargs)


def envelope(reply=None):
    return dict(choices=[dict(finish_reason="stop", message=dict(content=json.dumps(reply or dict(
        action="finish", source_id=None, start_line=None, end_line=None, proposals=[]))))],
        usage=dict(prompt_tokens=20, completion_tokens=20))


@contextmanager
def http_stub(bodies=None, *, headers_drip=0, body_pause=0):
    bodies = list(bodies or [envelope()])
    seen = threading.Event()
    stop = threading.Event()
    calls = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            calls.append(1)
            seen.set()
            body = json.dumps(bodies[min(len(calls)-1, len(bodies)-1)]).encode()
            try:
                self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                if headers_drip:
                    for i in range(20):
                        self.wfile.write(f"X-Drip-{i}: test\r\n".encode())
                        self.wfile.flush()
                        if stop.wait(headers_drip):
                            break
                self.wfile.write(f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body[:1])
                self.wfile.flush()
                if body_pause:
                    stop.wait(body_pause)
                self.wfile.write(body[1:])
                self.wfile.flush()
            except OSError:
                pass
        def log_message(self, *args):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_port}/v1/chat/completions", seen, calls
    finally:
        stop.set()
        srv.shutdown()
        srv.server_close()
        t.join()


class TransportRegressions(unittest.TestCase):
    def test_r1_cancel_interrupts_body(self):
        with http_stub(body_pause=1.2) as (url, seen, calls):
            cancel = threading.Event()
            timer = threading.Timer(0.15, cancel.set)
            timer.start()
            try:
                start = time.monotonic()
                with self.assertRaisesRegex(GraphError, "cancelled"):
                    ChatModel(config(url, timeout_seconds=5)).complete([], cancel=cancel)
                self.assertLess(time.monotonic()-start, 0.65)
            finally:
                timer.cancel()
                timer.join()

    def test_r1_connect_tls_and_send_obey_deadline(self):
        phases = [(socket.socket, "connect"), (ssl.SSLSocket, "do_handshake"), (http.client.HTTPConnection, "send")]
        for owner, name in phases:
            for cancelled in (False, True):
                with self.subTest(phase=name, cancelled=cancelled):
                    release, ended, cancel = threading.Event(), threading.Event(), threading.Event()
                    original = getattr(owner, name)
                    def paused(*args, _original=original, _release=release, _ended=ended, **kwargs):
                        try:
                            _release.wait(1.2)
                            return _original(*args, **kwargs)
                        finally:
                            _ended.set()
                    with http_stub() as (url, seen, calls):
                        options = dict(timeout_seconds=5 if cancelled else 0.15)
                        if name == "do_handshake":
                            url = url.replace("http:", "https:")
                            options.update(route="corporate", micro_per_million_tokens=1,
                                           installation_micro_cap=100000, run_micro_cap=100000)
                        timer = threading.Timer(0.15, cancel.set)
                        if cancelled:
                            timer.start()
                        try:
                            with patch.object(owner, name, paused), patch.dict("os.environ", {"GRAPH_LLM_API_KEY": "regression-only"}):
                                start = time.monotonic()
                                with self.assertRaisesRegex(GraphError, "cancelled" if cancelled else "model_timeout"):
                                    ChatModel(config(url, **options)).complete([], cancel=cancel)
                                self.assertLess(time.monotonic()-start, 0.65)
                        finally:
                            timer.cancel()
                            if cancelled:
                                timer.join()
                            release.set()
                            self.assertTrue(ended.wait(2))
                        self.assertEqual(calls, [])

    def test_r1_headers_obey_wall_deadline(self):
        with http_stub(headers_drip=0.06) as (url, seen, calls):
            start = time.monotonic()
            with self.assertRaises(GraphError):
                ChatModel(config(url, timeout_seconds=0.15)).complete([])
            self.assertLess(time.monotonic()-start, 0.65)
            self.assertEqual(len(calls), 1)

    def test_r1_cancel_interrupts_headers(self):
        with http_stub(headers_drip=0.06) as (url, seen, calls):
            cancel = threading.Event()
            timer = threading.Timer(0.15, cancel.set)
            timer.start()
            start = time.monotonic()
            try:
                with self.assertRaisesRegex(GraphError, "cancelled"):
                    ChatModel(config(url, timeout_seconds=5)).complete([], cancel=cancel)
                self.assertLess(time.monotonic()-start, 0.65)
            finally:
                timer.cancel()
                timer.join()

    def test_r1_dns_wait_is_bounded_and_no_late_request(self):
        release = threading.Event()
        entered = threading.Event()
        original = __import__("socket").getaddrinfo
        def resolver(*args, **kwargs):
            entered.set()
            release.wait(1)
            return original(*args, **kwargs)
        with http_stub() as (url, seen, calls):
            try:
                with patch("socket.getaddrinfo", resolver):
                    start = time.monotonic()
                    with self.assertRaises(GraphError):
                        ChatModel(config(url, timeout_seconds=0.15)).complete([])
                    self.assertLess(time.monotonic()-start, 0.65)
                    self.assertTrue(entered.is_set())
            finally:
                release.set()
            self.assertFalse(seen.wait(0.15))

    def test_r1_cancel_interrupts_dns_without_late_connection(self):
        release, ended, cancel = threading.Event(), threading.Event(), threading.Event()
        original = socket.getaddrinfo
        def resolver(*args, **kwargs):
            try:
                release.wait(1.2)
                return original(*args, **kwargs)
            finally:
                ended.set()
        timer = threading.Timer(0.15, cancel.set)
        with http_stub() as (url, seen, calls):
            timer.start()
            try:
                with patch("socket.getaddrinfo", resolver):
                    start = time.monotonic()
                    with self.assertRaisesRegex(GraphError, "cancelled"):
                        ChatModel(config(url, timeout_seconds=5)).complete([], cancel=cancel)
                    self.assertLess(time.monotonic()-start, 0.65)
            finally:
                release.set()
                timer.cancel()
                timer.join()
                self.assertTrue(ended.wait(2))
            self.assertFalse(seen.wait(0.15))

    def test_r1_expired_lease_does_not_unlock_a_live_owner(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = Store(Path(directory)/"state"), Store(Path(directory)/"state")
            try:
                cfg = config("http://127.0.0.1:1/v1/chat/completions")
                token = first.reserve("install", "first", 10, cfg)
                first.db.execute("UPDATE reservations SET until=0 WHERE id=?", (token,))
                with self.assertRaisesRegex(GraphError, "model_busy"):
                    second.reserve("install", "second", 10, cfg)
                first.finish_reservation(token)
                token2 = second.reserve("install", "second", 10, cfg)
                second.finish_reservation(token2)
                self.assertEqual(second.budget_totals("install")["reserved_token_units"], 20)
            finally:
                first.close()
                second.close()

    def test_r1_process_crash_releases_owner_without_refunding_charge(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = create_fixture(root)
            store = Store(root/"state")
            child = None
            try:
                with http_stub(headers_drip=0.06) as (url, seen, calls):
                    policy.model = config(url, timeout_seconds=5)
                    c = Graph(policy, store).prepare_context()
                    path = root/"policy.json"
                    path.write_text(policy.model_dump_json())
                    child = subprocess.Popen([sys.executable, "-m", "agent_graph", "--policy", str(path),
                                              "--state", str(root/"state"), "investigate", "--context", c["id"]],
                                             stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    self.assertTrue(seen.wait(5))
                    child.kill()
                    child.communicate(timeout=5)
                    before = store.budget_totals(policy.installation_id)
                    self.assertEqual(before["attempts"], 1)
                    with self.assertRaisesRegex(GraphError, "model_busy"):
                        store.reserve(policy.installation_id, "restart", 10, policy.model)
                    # Simulate passage of the crash lease without a long sleep.
                    store.db.execute("UPDATE reservations SET until=0")
                    token = store.reserve(policy.installation_id, "restart", 10, policy.model)
                    store.finish_reservation(token)
                    self.assertEqual(store.budget_totals(policy.installation_id)["reserved_token_units"],
                                     before["reserved_token_units"]+10)
            finally:
                if child and child.poll() is None:
                    child.kill()
                    child.communicate(timeout=5)
                store.close()

    def test_r1_pending_resolver_keeps_lock_after_partial_and_store_close(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = create_fixture(root)
            store = Store(root/"state")
            other = Store(root/"state")
            release, ended = threading.Event(), threading.Event()
            original = socket.getaddrinfo
            def resolver(*args, **kwargs):
                try:
                    release.wait(1.2)
                    return original(*args, **kwargs)
                finally:
                    ended.set()
            try:
                with http_stub() as (url, seen, calls):
                    policy.model = config(url, timeout_seconds=0.15)
                    g = Graph(policy, store)
                    context = g.prepare_context()
                    with patch("socket.getaddrinfo", resolver):
                        report = investigate(g, context["id"])
                    self.assertEqual(report["status"], "PARTIAL")
                    store.close()
                    store = None
                    other.db.execute("UPDATE reservations SET until=0")
                    with self.assertRaisesRegex(GraphError, "model_busy"):
                        other.reserve(policy.installation_id, "next", 10, policy.model)
                    release.set()
                    self.assertTrue(ended.wait(2))
                    deadline = time.monotonic()+2
                    while other.db.execute("SELECT sum(active) FROM reservations").fetchone()[0]:
                        self.assertLess(time.monotonic(), deadline)
                        threading.Event().wait(0.01)
                    self.assertEqual(calls, [])
                    self.assertEqual(other.budget_totals(policy.installation_id)["attempts"], 1)
            finally:
                release.set()
                if store:
                    store.close()
                other.close()

    def test_r5_envelope_shapes_are_structured_errors(self):
        valid = envelope()
        cases = [None, [], {**valid, "choices": None},
                 {**valid, "choices": [None]},
                 {**valid, "choices": [dict(finish_reason="stop", message=None)]},
                 {**valid, "choices": [dict(finish_reason="stop", message="bad")]},
                 {**valid, "usage": None}, {**valid, "usage": []}]
        for value in cases:
            with self.subTest(value=value):
                with http_stub([value]) as (url, seen, calls):
                    with self.assertRaises(GraphError):
                        ChatModel(config(url)).complete([])

    def test_r5_cli_partial_preserves_candidates_and_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            policy = create_fixture(root)
            store = Store(root/"state")
            try:
                g = Graph(policy, store)
                context = g.prepare_context()
                s = next(s for s in context["sources"].values() if s["path"] == "sampling.md")
                proposal = dict(key="r5-candidate", kind="hypothesis", statement="Needs owner review",
                                citations=[dict(source_id=s["id"], start_line=1, end_line=1,
                                                quote=s["text"].splitlines()[0])])
                good = envelope(dict(action="propose", source_id=None, start_line=None, end_line=None, proposals=[proposal]))
                bad = {**envelope(), "usage": None}
                with http_stub([good, bad]) as (url, seen, calls):
                    policy.model = config(url)
                    path = root/"policy.json"
                    path.write_text(policy.model_dump_json())
                    result = subprocess.run([sys.executable, "-m", "agent_graph", "--policy", str(path),
                                             "--state", str(root/"state"), "investigate", "--context", context["id"]],
                                            capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                report = json.loads(result.stdout)
                self.assertEqual(report["status"], "PARTIAL")
                self.assertEqual(len(report["candidate_ids"]), 1)
                self.assertEqual(report["budget"]["attempts"], 2)
                self.assertGreater(report["budget"]["reserved_token_units"], 0)
                self.assertNotIn("Traceback", result.stderr)
                self.assertEqual(len(g.proposals(context)), 1)
            finally:
                store.close()
