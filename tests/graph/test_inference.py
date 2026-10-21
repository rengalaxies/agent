from contextlib import contextmanager
import http.server
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from agent_graph.contracts import GraphError, ModelConfig, ModelReply
from agent_graph.engine import Graph
from agent_graph.inference import ChatModel, investigate
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/agent_graph"))
from fixture import create_fixture


def finish():
    return dict(action="finish", source_id=None, start_line=None, end_line=None, proposals=[])


@contextmanager
def server(reply=None, status=200, finish_reason="stop", *, raw=None, delay=0, headers=None, drip=0):
    requests = []
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            data = self.rfile.read(int(self.headers["Content-Length"]))
            requests.append(dict(body=json.loads(data), authorization=self.headers.get("Authorization")))
            if delay:
                time.sleep(delay)
            body = raw if raw is not None else json.dumps(dict(
                choices=[dict(message=dict(content=json.dumps(reply or finish())), finish_reason=finish_reason)],
                usage=dict(prompt_tokens=20, completion_tokens=30))).encode()
            try:
                self.send_response(status)
                self.send_header("Content-Length", str(len(body)))
                for key, value in (headers or {}).items():
                    self.send_header(key, value)
                self.end_headers()
                if drip:
                    for chunk in (body[:1], body[1:2], body[2:]):
                        self.wfile.write(chunk)
                        self.wfile.flush()
                        time.sleep(drip)
                else:
                    self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass
        def log_message(self, *args):
            pass
    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_port}/v1/chat/completions", requests
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join()


def config(url, **kwargs):
    return ModelConfig(endpoint=url, allowed_endpoints=[url], model="test-only-stub",
                       configuration_id="stub-not-quality", allow_source_transfer=True, **kwargs)


class TransportTests(unittest.TestCase):
    def test_real_http_and_schema_request_but_no_real_model(self):
        with server() as (url, requests):
            with patch.dict(os.environ, {"HTTP_PROXY": "http://127.0.0.1:1", "GRAPH_LLM_API_KEY": "test-only-secret"}):
                reply, usage = ChatModel(config(url)).complete([dict(role="user", content="test")])
            self.assertEqual(reply.action, "finish")
            self.assertEqual(usage["completion_tokens"], 30)
            self.assertEqual(requests[0]["authorization"], "Bearer test-only-secret")
            self.assertEqual(requests[0]["body"]["response_format"]["type"], "json_schema")
            schema = requests[0]["body"]["response_format"]["json_schema"]["schema"]
            self.assertIn("supersedes", schema["$defs"]["Proposal"]["required"])
            self.assertFalse(requests[0]["body"]["stream"])

    def test_no_redirect_fallback_or_automatic_retry(self):
        with server(status=307, headers={"Location": "https://unapproved.invalid/steal"}) as (url, requests):
            with self.assertRaisesRegex(GraphError, "model_http_error"):
                ChatModel(config(url)).complete([])
            self.assertEqual(len(requests), 1)

    def test_truncated_invalid_and_privilege_escalating_replies_rejected(self):
        cases = [dict(finish_reason="length"), dict(raw=b'{"choices":'),
                 dict(reply={**finish(), "action": "shell"}),
                 dict(reply={**finish(), "approved": True}),
                 dict(raw=b'{"choices":[],"choices":[]}'), dict(raw=b'x'*131073)]
        for kwargs in cases:
            with self.subTest(kwargs=list(kwargs)):
                with server(**kwargs) as (url, requests):
                    with self.assertRaises(GraphError):
                        ChatModel(config(url)).complete([])
                    self.assertEqual(len(requests), 1)

    def test_timeout_and_pre_cancel_are_bounded(self):
        with server(delay=0.3) as (url, requests):
            start = time.monotonic()
            with self.assertRaises(GraphError):
                ChatModel(config(url, timeout_seconds=0.1)).complete([])
            self.assertLess(time.monotonic() - start, 1)
            cancel = threading.Event()
            cancel.set()
            with self.assertRaisesRegex(GraphError, "cancelled"):
                ChatModel(config(url)).complete([], cancel=cancel)

    def test_body_deadline_with_http10_closed_connection(self):
        with server(drip=0.45) as (url, requests):
            started = time.monotonic()
            with self.assertRaises(GraphError):
                ChatModel(config(url, timeout_seconds=0.6)).complete([])
            self.assertLess(time.monotonic() - started, 0.85)

    def test_source_transfer_https_allowlist_and_plaintext_rules(self):
        for changes in (dict(allow_source_transfer=False), dict(allowed_endpoints=[]),
                        dict(endpoint="https://user:secret@llm.invalid/v1/chat/completions"),
                        dict(endpoint="http://outside.invalid/v1/chat/completions")):
            values = dict(endpoint="http://127.0.0.1:8000/v1/chat/completions",
                          allowed_endpoints=["http://127.0.0.1:8000/v1/chat/completions"],
                          model="test", configuration_id="test", allow_source_transfer=True)
            values.update(changes)
            with self.assertRaises(ValidationError):
                ModelConfig.model_validate(values)


class LoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.policy = create_fixture(self.tmp.name)
        self.store = Store(Path(self.tmp.name) / "state")
        self.graph = Graph(self.policy, self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_loop_uses_source_tool_and_stores_only_candidate(self):
        c = self.graph.prepare_context()
        source = next(s for s in c["sources"].values() if s["repository"] == "reporting" and s["path"] == "sampling.md")
        quote = source["text"].splitlines()[0]
        actions = [dict(action="read_source", source_id=source["id"], start_line=1, end_line=3, proposals=[]),
                   dict(action="propose", source_id=None, start_line=None, end_line=None, proposals=[dict(
                       key="sampling", kind="requirement_candidate", statement="Sample report may permit a subset",
                       citations=[dict(source_id=source["id"], start_line=1, end_line=1, quote=quote)])]), finish()]
        class Fake:
            def complete(self, messages, **kwargs):
                return ModelReply.model_validate(actions.pop(0)), dict(prompt_tokens=20, completion_tokens=30)
        self.policy.model = config("http://127.0.0.1:8000/v1/chat/completions")
        r = investigate(self.graph, c["id"], model=Fake())
        self.assertEqual(r["status"], "COMPLETED")
        self.assertEqual(len(r["candidate_ids"]), 1)
        self.assertFalse(r["model_quality_established"])
        self.assertEqual(self.graph.proposals(c)[0]["trust"], "UNAPPROVED_CANDIDATE")
        self.assertEqual(len(self.graph.context(c["id"])["graph"]["requirements"]), 1)

    def test_installation_budget_survives_new_run_revision_and_restart(self):
        cfg = config("http://127.0.0.1:8000/v1/chat/completions", installation_token_cap=50, run_token_cap=50)
        id = self.store.reserve("install", "run1", 40, cfg)
        self.store.finish_reservation(id)
        other = Store(Path(self.tmp.name) / "state")
        try:
            with self.assertRaisesRegex(GraphError, "budget_exhausted"):
                other.reserve("install", "brand-new-revision", 20, cfg)
            self.assertEqual(other.budget_totals("install")["reserved_token_units"], 40)
        finally:
            other.close()

    def test_only_one_inflight_and_unknown_outcome_charged(self):
        cfg = config("http://127.0.0.1:8000/v1/chat/completions")
        self.store.reserve("install", "first", 50, cfg)
        with self.assertRaisesRegex(GraphError, "model_busy"):
            self.store.reserve("install", "parallel", 50, cfg)
        self.assertEqual(self.store.budget_totals("install")["attempts"], 1)

    def test_http_failure_charges_budget_and_returns_partial_without_secret_log(self):
        with server(status=500, raw=b'test-only-secret') as (url, requests):
            self.policy.model = config(url)
            c = self.graph.prepare_context()
            r = investigate(self.graph, c["id"])
            self.assertEqual(r["status"], "PARTIAL")
            self.assertEqual(r["reason"], "model_http_error")
            self.assertEqual(r["budget"]["attempts"], 1)
            self.assertNotIn("test-only-secret", json.dumps(r))

    def test_uncited_out_of_scope_and_human_correction_model_writes_rejected(self):
        c = self.graph.prepare_context()
        self.policy.model = config("http://127.0.0.1:8000/v1/chat/completions")
        class Fake:
            def complete(self, messages, **kwargs):
                return ModelReply.model_validate(dict(action="read_source", source_id="unknown", start_line=1, end_line=1, proposals=[])), {}
        r = investigate(self.graph, c["id"], model=Fake())
        self.assertEqual(r["reason"], "not_found")
        self.assertEqual(r["candidate_ids"], [])
