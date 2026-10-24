from contextlib import closing
import json
import logging
from pathlib import Path
import sqlite3
import sys
import tempfile
import threading
import time
import unittest

import yaml

from agent_graph.actions import (ACTION_NAMES, EXAMPLES, Rejection, action_schema, parse, system_prompt)
from agent_graph.constitution import ACTIONS, DEFAULT_PATH, load
from agent_graph.contracts import GraphError, Policy
from agent_graph.engine import Graph
from agent_graph.executor import Investigation, run_investigation
from agent_graph.inference import investigate
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/orders_reporting"))
from stand import build_stand  # noqa: E402

SECRET = "sk-canary-5c1e0b7d9a"
ENDPOINT = "http://127.0.0.1:9/v1/chat/completions"


def act(**action):
    return json.dumps(dict(action=action))


def rejection(content):
    with self_raises() as box:
        parse(content)
    return box.record


class self_raises:
    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        if not isinstance(value, Rejection):
            raise AssertionError(f"expected Rejection, got {value!r}")
        self.record = value.record
        return True


class LayerTests(unittest.TestCase):
    def assert_layer(self, content, layer, reason, path=None, expected=None, action=None):
        record = rejection(content)
        self.assertEqual((record["layer"], record["reason_code"]), (layer, reason))
        if path is not None:
            self.assertEqual(record["field_path"], path)
        if expected is not None:
            self.assertEqual(record["expected"], expected)
        if action is not None:
            self.assertEqual(record["action"], action)
        self.assertEqual(len(record["content_sha256"]), 64)

    def test_each_layer_has_its_own_reason(self):
        self.assert_layer("{not json", "json", "json_syntax")
        self.assert_layer('{"action": {}, "action": {}}', "json", "duplicate_json_key")
        self.assert_layer("[1]", "json", "not_an_object")
        self.assert_layer(act(source_id="x"), "schema", "missing_action_name")
        self.assert_layer(act(name="shell", command="rm -rf /"), "schema", "unknown_action", action="unknown")
        self.assert_layer(act(name="read_source", source_id="s", start_line="3", end_line=4), "schema",
                          "wrong_type", path="action.read_source.start_line", expected="integer",
                          action="read_source")
        self.assert_layer(act(name="finish", outcome="complete", reason="done", proposals=[]), "schema",
                          "unexpected_field", path="action.finish.*", action="finish")
        self.assert_layer(act(name="read_source", source_id="s", start_line=9, end_line=3), "combination",
                          "range_inverted", action="read_source")
        self.assert_layer(act(name="propose_hypothesis", evidence_refs=["r"], unknowns=["owner_unknown"],
                              claim=dict(consumer_service="a", provider_service=None, method="GET", route=None,
                                         statement="s")), "combination", "incomplete_operation")

    def test_flat_legacy_reply_is_a_schema_error_not_an_opaque_failure(self):
        legacy = json.dumps(dict(action="propose", source_id="x", start_line=None, end_line=None, proposals=[]))
        self.assert_layer(legacy, "schema", "wrong_type", path="action", expected="object")

    def test_unknown_keys_and_values_never_reach_the_record(self):
        for content in (act(name=SECRET), act(name="finish", outcome="complete", reason="done", **{SECRET: 1}),
                        act(name="search", query=SECRET * 100, repository=None), "{" + SECRET,
                        act(name="read_source", source_id=SECRET, start_line=SECRET, end_line=1)):
            with self.subTest(content=content[:30]):
                self.assertNotIn(SECRET, json.dumps(rejection(content)))


class AgreementTests(unittest.TestCase):
    def setUp(self):
        self.constitution, self.version = load()

    def test_template_schema_executor_and_constitution_name_the_same_actions(self):
        schema = action_schema()
        variants = schema["properties"]["action"]["anyOf"]
        names = {schema["$defs"][v["$ref"].split("/")[-1]]["properties"]["name"]["enum"][0] for v in variants}
        self.assertEqual(names, set(ACTION_NAMES))
        self.assertEqual(set(ACTION_NAMES), set(ACTIONS))
        self.assertEqual(set(self.constitution.actions), set(ACTIONS))
        self.assertTrue(all(callable(getattr(Investigation, n, None)) for n in ACTION_NAMES))
        prompt = system_prompt(self.constitution)
        self.assertEqual(sum(f'"name":"{n}"' in prompt for n in ACTION_NAMES), len(ACTION_NAMES))

    def test_every_template_example_passes_the_executor_parser(self):
        for example in EXAMPLES:
            with self.subTest(action=example["name"]):
                self.assertEqual(parse(json.dumps(dict(action=example))).name, example["name"])

    def test_portable_schema_is_strict_and_has_no_unsupported_keywords(self):
        allowed = {"type", "properties", "required", "additionalProperties", "enum", "anyOf", "items", "$defs",
                   "$ref", "description"}

        def visit(node, inside_properties=False):
            if isinstance(node, dict):
                if not inside_properties:
                    self.assertLessEqual(set(node), allowed)
                    if node.get("type") == "object":
                        self.assertIs(node.get("additionalProperties"), False)
                        self.assertEqual(set(node["required"]), set(node["properties"]))
                for key, child in node.items():
                    if key in ("properties", "$defs"):
                        for sub in child.values():
                            visit(sub)
                    else:
                        visit(child)
            elif isinstance(node, list):
                for child in node:
                    visit(child)
        visit(action_schema())
        self.assertNotIn("human_correction", json.dumps(action_schema()))

    def test_constitution_cannot_drop_rules_or_add_tools(self):
        base = yaml.safe_load(DEFAULT_PATH.read_text(encoding="utf-8"))
        broken = [
            {**base, "forbidden": [f for f in base["forbidden"] if f != "shell"]},
            {**base, "actions": {**base["actions"], "shell": {}}},
            {**base, "publication": {"model_may_publish": True}},
            {**base, "outcomes": {**base["outcomes"], "abstained": {"status": "USEFUL",
                                                                   "reason": "impact_found_within_profile"}}},
            {**base, "outcomes": {**base["outcomes"], "step_limit": {"status": "PARTIAL", "reason": "great"}}},
            {**base, "limits": {**base["limits"], "max_steps": 10_000}},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            for number, value in enumerate(broken):
                path = Path(tmp) / f"c{number}.yaml"
                path.write_text(yaml.safe_dump(value), encoding="utf-8")
                with self.subTest(case=number):
                    with self.assertRaises(GraphError) as caught:
                        load(path)
                    self.assertEqual(caught.exception.code, "invalid_constitution")


class Script:
    """Offline scripted model. Each step is a reply string or a function of the messages."""

    def __init__(self, steps, on_call=None):
        self.steps, self.calls, self.on_call = list(steps), 0, on_call

    def complete_raw(self, messages, schema, *, cancel=None, deadline_epoch=None):
        self.calls += 1
        if self.on_call:
            self.on_call(self.calls, cancel)
        step = self.steps[min(self.calls, len(self.steps)) - 1]
        content = step(messages) if callable(step) else step
        if isinstance(content, Exception):
            raise content
        return content, dict(prompt_tokens=10, completion_tokens=5)


def last_result(messages):
    return json.loads(messages[-1]["content"])["tool_result"]


def refs(messages):
    found = []
    for m in messages:
        if m["role"] == "user" and '"untrusted_source"' in m["content"]:
            found.append(json.loads(m["content"])["tool_result"]["untrusted_source"]["evidence_ref"])
    return found


class ExecutorCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.stand = build_stand(Path(cls.tmp.name) / "stand")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        policy = self.stand.policy(model=dict(
            endpoint=ENDPOINT, allowed_endpoints=[ENDPOINT], model="OFFLINE-SCRIPT", configuration_id="script-v3",
            protocol="actions-v3", allow_source_transfer=True, max_prompt_bytes=60000, context_tokens=131072,
            run_token_cap=10_000_000, installation_token_cap=10_000_000))
        self.policy = Policy.model_validate(policy)
        self.store = Store(Path(self.work.name) / "state")
        self.graph = Graph(self.policy, self.store)
        self.context = self.graph.prepare_context("ORD-12", revisions=self.stand.revisions(orders="hazards"))

    def tearDown(self):
        self.store.close()
        self.work.cleanup()

    def source(self, repository, path):
        return next(s["id"] for s in self.context["sources"].values()
                    if s["repository"] == repository and s["path"] == path)

    def read(self, repository, path, first, last):
        return act(name="read_source", source_id=self.source(repository, path), start_line=first, end_line=last)

    def run_script(self, script, **kwargs):
        return run_investigation(self.graph, self.context["id"], model=script, **kwargs)

    def active_reservations(self):
        with closing(sqlite3.connect(self.store.path)) as db:
            return db.execute("SELECT count(*) FROM reservations WHERE active=1").fetchone()[0]


class ExecutorTests(ExecutorCase):
    def propose(self, consumer, provider):
        def step(messages):
            return act(name="propose_dependency", evidence_refs=refs(messages)[-2:], claim=dict(
                consumer_repository=consumer, consumer_service=consumer, provider_service=provider,
                method="GET", path_template="/orders"))
        return step

    def test_supported_dependency_cycle_is_useful_but_unapproved(self):
        script = Script([act(name="list_sources", repository=None), self.read("reporting", "client.py", 1, 9),
                         self.read("orders", "api.py", 6, 9), self.propose("reporting", "orders"),
                         act(name="finish", outcome="complete", reason="done")])
        report = self.run_script(script)
        self.assertEqual((report["outcome"], report["status"], report["reason_code"]),
                         ("supported_dependency", "USEFUL", "impact_found_within_profile"))
        stored = self.graph.proposals(self.graph.context(self.context["id"]))
        self.assertEqual([p["trust"] for p in stored], ["UNAPPROVED_CANDIDATE"])
        self.assertEqual(report["constitution_version"], load()[1])
        self.assertEqual(self.active_reservations(), 0)

    def test_quote_from_same_route_of_another_service_does_not_support_the_claim(self):
        script = Script([self.read("audit", "client.py", 1, 8), self.read("billing", "api.py", 6, 8),
                         self.propose("audit", "orders"),
                         lambda m: (self.assertEqual(last_result(m)["status"], "INSUFFICIENT")
                                    or act(name="finish", outcome="abstain", reason="insufficient_evidence"))])
        report = self.run_script(script)
        self.assertEqual((report["outcome"], report["status"]), ("abstained", "ABSTAINED"))
        self.assertEqual(report["candidate_ids"], [])
        self.assertEqual(len(report["insufficient_claims"]), 1)

    def test_hypothesis_outside_the_grammar_stays_unverified(self):
        script = Script([self.read("orders", "README.md", 1, 3), lambda m: act(
            name="propose_hypothesis", evidence_refs=refs(m), unknowns=["helper_semantics_unknown"],
            claim=dict(consumer_service="reporting", provider_service="orders", method="GET", route="/orders",
                       statement="Order history may be exported through a shared helper.")),
            act(name="finish", outcome="complete", reason="done")])
        report = self.run_script(script)
        self.assertEqual((report["outcome"], report["status"], report["reason_code"]),
                         ("hypotheses_only", "PARTIAL", "hypotheses_only"))
        stored = self.graph.proposals(self.graph.context(self.context["id"]))[0]
        self.assertEqual(stored["trust"], "UNAPPROVED_CANDIDATE")
        self.assertTrue(stored["proposal"]["statement"].startswith("UNVERIFIED HYPOTHESIS"))

    def test_invented_or_foreign_receipts_are_evidence_rejections(self):
        other = Script([self.read("reporting", "client.py", 1, 9), act(name="finish", outcome="abstain",
                                                                         reason="insufficient_evidence")])
        foreign_ref = []
        self.run_script(Script([lambda m: other.steps[0],
                                lambda m: foreign_ref.extend(refs(m)) or other.steps[1]]))
        self.assertEqual(len(foreign_ref), 1)
        script = Script([self.read("orders", "api.py", 6, 9), lambda m: act(
            name="propose_dependency", evidence_refs=[foreign_ref[0], refs(m)[0]],
            claim=dict(consumer_repository="reporting", consumer_service="reporting", provider_service="orders",
                       method="GET", path_template="/orders")),
            act(name="propose_dependency", evidence_refs=["0" * 32], claim=dict(
                consumer_repository="reporting", consumer_service="reporting", provider_service="orders",
                method="GET", path_template="/orders")),
            act(name="read_source", source_id="f" * 64, start_line=1, end_line=2),
            act(name="finish", outcome="abstain", reason="insufficient_evidence")])
        report = self.run_script(script)
        reasons = [(d["layer"], d["reason_code"]) for d in report["diagnostics"]]
        self.assertEqual(reasons, [("evidence", "invalid_evidence_reference")] * 2 + [("evidence", "not_found")])
        self.assertEqual(report["outcome"], "invalid_actions")
        self.assertEqual((report["status"], report["reason_code"]), ("FAILED", "invalid_model_action"))

    def test_rejected_action_gets_safe_feedback_and_the_run_can_continue(self):
        seen = []
        script = Script([act(name="read_source", source_id=SECRET, start_line="1", end_line=2),
                         lambda m: seen.append(m[-1]["content"]) or act(name="finish", outcome="abstain",
                                                                         reason="insufficient_evidence")])
        report = self.run_script(script)
        self.assertEqual(report["outcome"], "abstained")
        feedback = json.loads(seen[0])["tool_result"]
        self.assertEqual((feedback["layer"], feedback["reason_code"], feedback["expected"]),
                         ("schema", "wrong_type", "integer"))
        self.assertNotIn(SECRET, seen[0])

    def test_secret_in_replies_never_reaches_report_logs_or_store(self):
        replies = ["{" + SECRET, act(name=SECRET), act(name="search", query="x", repository=None, note=SECRET)]
        with self.assertLogs("agent_graph.diagnostics", level=logging.INFO) as logs:
            report = self.run_script(Script(replies))
        self.assertEqual(report["outcome"], "invalid_actions")
        self.assertEqual([d["layer"] for d in report["diagnostics"]], ["json", "schema", "schema"])
        self.assertNotIn(SECRET, json.dumps(report))
        self.assertNotIn(SECRET, "\n".join(logs.output))
        with closing(sqlite3.connect(self.store.path)) as db:
            rows = db.execute("SELECT data FROM artifacts WHERE kind='investigation'").fetchall()
        self.assertNotIn(SECRET, json.dumps(rows))

    def test_injection_text_cannot_add_tools(self):
        notes = self.read("orders", "docs/notes.md", 1, 4)
        script = Script([notes, act(name="publish", body="x"), act(name="shell", command="id"),
                         act(name="finish", outcome="abstain", reason="insufficient_evidence")])
        report = self.run_script(script)
        self.assertEqual([d["reason_code"] for d in report["diagnostics"]], ["unknown_action"] * 2)
        self.assertEqual(report["outcome"], "abstained")


class StopTests(ExecutorCase):
    def test_step_limit_stops_calls_and_releases_reservations(self):
        script = Script([act(name="list_sources", repository=None)])
        report = self.run_script(script)
        limit = load()[0].limits.max_steps
        self.assertEqual((script.calls, report["outcome"], report["reason_code"]), (limit, "step_limit",
                                                                                    "model_step_limit"))
        self.assertEqual(self.active_reservations(), 0)

    def test_cancel_during_a_call_discards_its_reply_and_makes_no_further_calls(self):
        cancel = threading.Event()
        script = Script([self.read("reporting", "client.py", 1, 9),
                         lambda m: act(name="propose_hypothesis", evidence_refs=refs(m), unknowns=["owner_unknown"],
                                       claim=dict(consumer_service="reporting", provider_service=None, method=None,
                                                  route=None, statement="s")),
                         act(name="list_sources", repository=None)],
                        on_call=lambda n, c: c.set() if n == 2 else None)
        report = self.run_script(script, cancel=cancel)
        self.assertEqual((script.calls, report["outcome"], report["status"]), (2, "cancelled", "FAILED"))
        self.assertEqual(report["hypothesis_ids"], [])
        self.assertEqual(self.graph.proposals(self.graph.context(self.context["id"])), [])
        self.assertEqual(self.active_reservations(), 0)

    def test_budget_cap_stops_before_the_next_call(self):
        self.graph.policy.model.run_token_cap = 150_000
        script = Script([act(name="list_sources", repository=None)])
        report = self.run_script(script)
        self.assertEqual((report["outcome"], report["reason_code"]), ("budget", "budget_exhausted"))
        self.assertLess(script.calls, load()[0].limits.max_steps)
        self.assertEqual(self.active_reservations(), 0)

    def test_deadline_before_the_first_call_makes_no_call(self):
        script = Script([act(name="list_sources", repository=None)])
        report = self.run_script(script, deadline_epoch=time.time() - 1)
        self.assertEqual((script.calls, report["outcome"], report["reason_code"]), (0, "deadline", "deadline_reached"))

    def test_transport_failure_is_partial_with_a_transport_diagnostic(self):
        script = Script([GraphError("model_http_error")])
        report = self.run_script(script)
        self.assertEqual((report["outcome"], report["status"], report["reason_code"]),
                         ("transport_failure", "PARTIAL", "model_unavailable"))
        self.assertEqual(report["diagnostics"][0]["layer"], "transport")
        self.assertEqual(self.active_reservations(), 0)

    def test_cli_investigate_entry_point_uses_actions_v3(self):
        script = Script([act(name="finish", outcome="abstain", reason="insufficient_evidence")])
        report = investigate(self.graph, self.context["id"], model=script)
        self.assertEqual((report["schema"], report["protocol"]), ("graph-investigation-2", "actions-v3"))


if __name__ == "__main__":
    unittest.main()


class HttpTransportTests(ExecutorCase):
    def test_real_http_path_sends_the_v3_schema_and_parses_in_layers(self):
        from tests.graph.test_inference import server
        reply = dict(action=dict(name="finish", outcome="abstain", reason="insufficient_evidence"))
        with server(reply) as (url, requests):
            self.graph.policy.model.endpoint = url
            self.graph.policy.model.allowed_endpoints = [url]
            report = self.run_script(None)
        self.assertEqual(report["outcome"], "abstained")
        sent = requests[0]["body"]
        self.assertEqual(sent["response_format"]["json_schema"]["schema"], action_schema())
        self.assertIn("UNTRUSTED DATA", sent["messages"][0]["content"])

    def test_schema_invalid_reply_over_http_is_not_a_transport_failure(self):
        from tests.graph.test_inference import server
        with server(dict(action=dict(name="read_source", source_id="x", start_line="1", end_line=1))) as (url, _):
            self.graph.policy.model.endpoint = url
            self.graph.policy.model.allowed_endpoints = [url]
            report = self.run_script(None)
        self.assertEqual({d["layer"] for d in report["diagnostics"]}, {"schema"})
        self.assertEqual(report["outcome"], "invalid_actions")
