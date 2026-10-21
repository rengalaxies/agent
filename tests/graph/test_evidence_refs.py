"""OFFLINE scripted proposals on synthetic fixtures; no real model qualification."""
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from agent_graph.contracts import GraphError, ModelConfig, Policy, model_action_schema
from agent_graph.engine import Graph
from agent_graph.evidence_refs import EvidenceSession, ReferenceProposal, ReferenceReply
from agent_graph.inference import investigate
from agent_graph.store import Store

FIXTURES = Path(__file__).parent / "fixtures/pr31"
CASES = {
    "reporting": "partial-series/1-reporting-http/corpus",
    "export": "final/1-export-E/corpus",
    "status": "final/1-status-decoy/corpus",
}


def fixture(directory, case="reporting"):
    """Explicit TEST DATA, copied byte-for-byte from saved synthetic PR31 corpus."""
    root = Path(directory)
    shutil.copytree(FIXTURES / CASES[case], root / "corpus")
    repos = sorted(p.name for p in (root / "corpus").iterdir())
    policy = Policy.model_validate(dict(
        installation_id="OFFLINE-TEST-ONLY", environment="synthetic", subject="test-operator",
        capabilities=["read_context", "maintain", "propose"],
        repositories=[dict(id=r, service=r, root=str(root / "corpus" / r), revision="pr31-fixture") for r in repos],
        addresses=[dict(service="orders", base_url="https://orders.test"),
                   dict(service="status", base_url="https://inventory.test")]))
    store = Store(root / "private-state")
    return Graph(policy, store)


def claim(case="reporting", **updates):
    values = dict(consumer_repository=case if case != "status" else "health",
                  consumer_service=case if case != "status" else "health",
                  provider_service="status" if case == "status" else "orders",
                  method="GET", path_template="/orders")
    return {**values, **updates}


def reads(session, context):
    return {s["repository"]: session.read(s["id"], 1, len(s["text"].splitlines()))["evidence_ref"]
            for s in context["sources"].values()}


def proposal(case, refs, **updates):
    return dict(claim=claim(case, **updates), evidence_refs=list(refs))


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.graph = fixture(self.tmp.name)
        self.context = self.graph.prepare_context("OFFLINE scripted test")
        self.session = EvidenceSession(self.graph, self.context["id"])
        self.refs = reads(self.session, self.context)

    def tearDown(self):
        self.graph.store.close()
        self.tmp.cleanup()

    def assert_code(self, code, fn):
        with self.assertRaises(GraphError) as caught:
            fn()
        self.assertEqual(caught.exception.code, code)

    def test_valid_reference_reuses_exact_validator_and_candidate_remains_unapproved(self):
        p = proposal("reporting", self.refs.values())
        with patch.object(self.graph, "get_evidence", wraps=self.graph.get_evidence) as validator:
            outcome = self.session.propose(p)
        self.assertGreater(validator.call_count, 0)
        self.assertEqual(outcome["assessment"]["provenance"]["status"], "AUTHENTIC_AUTHORIZED_CURRENT")
        self.assertEqual(outcome["assessment"]["sufficiency"]["status"], "SUPPORTED_WITHIN_PROFILE")
        self.assertEqual(outcome["candidate"]["trust"], "UNAPPROVED_CANDIDATE")
        c = self.session.resolve(self.refs["reporting"])
        self.assertIn('    response = requests.get(BASE_URL + "/orders", params={"day": day}', c.quote)
        self.assertEqual(c.quote, self.context["sources"][c.source_id]["text"].rstrip('\n'))

    def test_fabricated_reference(self):
        self.assert_code("invalid_evidence_reference", lambda: self.session.resolve("made-up-id"))

    def test_other_session_same_scope_and_snapshot_is_denied(self):
        other = EvidenceSession(self.graph, self.context["id"])
        self.assertNotEqual(other.id, self.session.id)
        self.assert_code("invalid_evidence_reference", lambda: other.resolve(self.refs["reporting"]))

    def test_revoked_read_capability(self):
        self.graph.policy.capabilities.remove("read_context")
        self.assert_code("forbidden", lambda: self.session.resolve(self.refs["reporting"]))

    def test_read_receipt_does_not_grant_propose(self):
        self.graph.policy.capabilities.remove("propose")
        self.assert_code("forbidden", lambda: self.session.propose(proposal("reporting", self.refs.values())))

    def test_changed_subject_or_scope_denied(self):
        self.graph.policy.subject = "another-subject"
        self.assert_code("evidence_scope_changed", lambda: self.session.resolve(self.refs["reporting"]))
        self.graph.policy.subject = "test-operator"
        self.graph.policy.repositories[0].include = ["*.md"]
        self.assert_code("evidence_scope_changed", lambda: self.session.resolve(self.refs["reporting"]))

    def test_snapshot_changed_even_with_same_revision(self):
        path = Path(self.tmp.name) / "corpus/reporting/client.py"
        path.write_text(path.read_text() + "\n# changed bytes\n")
        self.assert_code("stale_context", lambda: self.session.resolve(self.refs["reporting"]))
        new = self.graph.prepare_context()
        other = EvidenceSession(self.graph, new["id"])
        self.assert_code("invalid_evidence_reference", lambda: other.resolve(self.refs["reporting"]))

    def test_new_snapshot_same_bytes_supersedes_session(self):
        self.graph.prepare_context()
        self.assert_code("superseded_context", lambda: self.session.resolve(self.refs["reporting"]))

    def test_expired_snapshot(self):
        with patch("agent_graph.engine.time.time", return_value=self.context["created_epoch"] + 3601):
            self.assert_code("stale_context", lambda: self.session.resolve(self.refs["reporting"]))

    def test_unavailable_current_corpus(self):
        shutil.rmtree(Path(self.tmp.name) / "corpus/reporting")
        self.assert_code("stale_context", lambda: self.session.resolve(self.refs["reporting"]))

    def test_invalid_ranges_issue_no_receipt(self):
        source = next(iter(self.context["sources"]))
        count = len(self.session._reads)
        for first, last in [(0, 1), (-1, 2), (2, 1), (1, 10000), (True, 2)]:
            with self.subTest(first=first, last=last):
                self.assert_code("invalid_evidence_range", lambda: self.session.read(source, first, last))
        self.graph.policy.limits.max_tool_lines = 1
        self.assert_code("evidence_range_limit", lambda: self.session.read(source, 1, 2))
        self.assert_code("not_found", lambda: self.session.read("unreadable-file-id", 1, 1))
        self.assertEqual(len(self.session._reads), count)

    def test_binding_tampering_rejected(self):
        reference = self.refs["reporting"]
        original = self.session._reads[reference]
        for updates in [dict(session="another"), dict(basis="other"), dict(path="other.py"),
                        dict(revision="other"), dict(start_line=2), dict(quote_digest="false")]:
            with self.subTest(updates=updates):
                self.session._reads[reference] = replace(original, **updates)
                self.assert_code("invalid_evidence_reference", lambda: self.session.resolve(reference))
        self.session._reads[reference] = original

    def test_exact_but_irrelevant_evidence_is_not_sufficient(self):
        refs = [self.session.read(s["id"], 1, 1)["evidence_ref"] for s in self.context["sources"].values()]
        assessment = self.session.assess(proposal("reporting", refs, provider_service="status"))
        self.assertEqual(assessment["provenance"]["status"], "AUTHENTIC_AUTHORIZED_CURRENT")
        self.assertEqual(assessment["sufficiency"]["status"], "INSUFFICIENT")
        self.assert_code("insufficient_dependency_evidence", lambda: self.session.propose(proposal("reporting", refs)))
        self.assertEqual(self.graph.store.proposals(self.graph.view), [])

    def test_full_evidence_wrong_direction_service_method_or_path_rejected(self):
        for updates in [dict(consumer_repository="orders", consumer_service="orders", provider_service="reporting"),
                        dict(provider_service="status"), dict(consumer_service="other"),
                        dict(method="POST"), dict(path_template="/different")]:
            with self.subTest(updates=updates):
                self.assert_code("insufficient_dependency_evidence",
                                 lambda: self.session.propose(proposal("reporting", self.refs.values(), **updates)))

    def test_missing_callsite_or_provider_is_insufficient(self):
        for ref in self.refs.values():
            self.assert_code("insufficient_dependency_evidence",
                             lambda: self.session.propose(proposal("reporting", [ref])))

    def test_forged_or_cross_session_assessment_does_not_assess_semantics(self):
        assessment = self.session.assess(proposal("reporting", ["invented"]))
        self.assertEqual(assessment["provenance"]["status"], "REJECTED")
        self.assertEqual(assessment["sufficiency"]["status"], "NOT_ASSESSED")

    def test_quotes_v1_not_repaired_and_v2_rejects_quote_fields(self):
        bad = dict(key="test", kind="hypothesis", statement="test", supersedes=None,
                   citations=[dict(source_id=next(iter(self.context["sources"])), start_line=6,
                                   end_line=6, quote='@app.get(“/orders”)')])
        self.assert_code("evidence_mismatch", lambda: self.graph.propose(self.context["id"], bad, from_model=True))
        with self.assertRaises(ValidationError):
            ReferenceProposal.model_validate({**proposal("reporting", self.refs.values()), "citations": bad["citations"]})

    def test_scripted_investigate_v2_no_network(self):
        self.graph.policy.model = ModelConfig(
            endpoint="http://127.0.0.1:1/v1/chat/completions", allowed_endpoints=["http://127.0.0.1:1/v1/chat/completions"],
            model="OFFLINE-SCRIPT-NOT-REAL-MODEL", configuration_id="test-only", protocol="evidence-refs-v2",
            allow_source_transfer=True, max_prompt_bytes=30000, context_tokens=65536)
        class Script:
            def complete(inner, messages, **kwargs):
                receipts = [json.loads(m["content"])["untrusted_source"]["evidence_ref"] for m in messages
                            if m["role"] == "user" and "untrusted_source" in json.loads(m["content"])]
                sources = list(self.context["sources"].values())
                if len(receipts) < 2:
                    src = sources[len(receipts)]
                    value = dict(action="read_source", source_id=src["id"], start_line=1,
                                 end_line=len(src["text"].splitlines()), proposals=[])
                elif not any(m["role"] == "user" and "stored_candidates" in json.loads(m["content"]) for m in messages):
                    value = dict(action="propose", source_id=None, start_line=None, end_line=None,
                                 proposals=[proposal("reporting", receipts)])
                else:
                    value = dict(action="finish", source_id=None, start_line=None, end_line=None, proposals=[])
                return ReferenceReply.model_validate(value), dict(prompt_tokens=1, completion_tokens=1)
        result = investigate(self.graph, self.context["id"], model=Script())
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(len(result["candidate_ids"]), 1)
        self.assertFalse(result["model_quality_established"])
        schema = model_action_schema(ReferenceReply)
        self.assertNotIn("Citation", schema["$defs"])
        self.assertIn("evidence_refs", schema["$defs"]["ReferenceProposal"]["properties"])


class SavedSeriesTests(unittest.TestCase):
    def test_saved_files_are_byte_identical(self):
        manifest = json.loads((FIXTURES / "provenance.json").read_text())
        for item in manifest["files"]:
            self.assertEqual(hashlib.sha256((FIXTURES / item["path"]).read_bytes()).hexdigest(), item["sha256"])

    def test_scripted_reporting_export_status_and_decoys(self):
        for case in CASES:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                graph = fixture(d, case)
                try:
                    context = graph.prepare_context("TEST DATA: scripted reference proposal")
                    session = EvidenceSession(graph, context["id"])
                    refs = reads(session, context)
                    positive = [refs["health"], refs["status"]] if case == "status" else list(refs.values())
                    self.assertEqual(session.propose(proposal(case, positive))["candidate"]["trust"], "UNAPPROVED_CANDIDATE")
                    if case == "status":
                        for updates in [dict(provider_service="orders"),
                                        dict(consumer_repository="orders", consumer_service="orders", provider_service="health"),
                                        dict(consumer_repository="status", consumer_service="status", provider_service="health")]:
                            assessment = session.assess(proposal(case, refs.values(), **updates))
                            self.assertEqual(assessment["provenance"]["status"], "AUTHENTIC_AUTHORIZED_CURRENT")
                            self.assertEqual(assessment["sufficiency"]["status"], "INSUFFICIENT")
                        # Correct target with a same-path decoy provider is also insufficient.
                        self.assertEqual(session.assess(proposal(case, [refs["health"], refs["orders"]]))["sufficiency"]["status"], "INSUFFICIENT")
                finally:
                    graph.store.close()

    def test_historical_proposals_remain_rejected_without_conversion(self):
        # Rebind ONLY source IDs to this test namespace, never change historical
        # quotes/ranges/claims or interpret them as new reference proposals.
        for case, label in [("reporting", "reporting-http"), ("export", "export-E"), ("status", "status-decoy")]:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as d:
                graph = fixture(d, case)
                try:
                    context = graph.prepare_context()
                    for model in [0, 1]:
                        report = json.loads((FIXTURES / f"final/{model}-{label}/report.json").read_text())
                        prefix = "partial-series" if case == "reporting" else "final"
                        messages = json.loads((FIXTURES / f"{prefix}/1-{label}/messages-1.json").read_text())
                        historic_sources = json.loads(messages[1]["content"])["sources"]
                        mapping = {s["source_id"]: next(v["id"] for v in context["sources"].values()
                                   if v["repository"] == s["repository"] and v["path"] == s["path"]) for s in historic_sources}
                        session = EvidenceSession(graph, context["id"])
                        for action in report["actions"]:
                            if action["action"] == "read_source":
                                source_id = mapping[action["source_id"]]
                                if case == "export" and model == 1 and action["end_line"] == 12:
                                    # Original GPT read exceeded the 9-line provider.
                                    # References must not silently clamp that range.
                                    with self.assertRaises(GraphError) as caught:
                                        session.read(source_id, action["start_line"], action["end_line"])
                                    self.assertEqual(caught.exception.code, "invalid_evidence_range")
                                else:
                                    session.read(source_id, action["start_line"], action["end_line"])
                            for p in action["proposals"]:
                                rebound = {**p, "citations": [{**c, "source_id": mapping[c["source_id"]]} for c in p["citations"]]}
                                with self.assertRaises(GraphError) as caught:
                                    graph.propose(context["id"], rebound, from_model=True)
                                self.assertEqual(caught.exception.code, "evidence_mismatch")
                    self.assertEqual(graph.store.proposals(graph.view), [])
                finally:
                    graph.store.close()


class ReferenceTransportTests(unittest.TestCase):
    def test_v2_schema_over_local_http_stub_no_real_model(self):
        from tests.graph.test_inference import config, server
        from agent_graph.inference import ChatModel
        value = dict(action="propose", source_id=None, start_line=None, end_line=None,
                     proposals=[proposal("reporting", ["STUB-ONLY-NO-ADMISSION"])])
        with server(reply=value) as (url, requests):
            reply, _ = ChatModel(config(url, protocol="evidence-refs-v2")).complete([
                dict(role="user", content="OFFLINE HTTP stub, no real model")])
        self.assertIsInstance(reply, ReferenceReply)
        schema = requests[0]["body"]["response_format"]["json_schema"]["schema"]
        self.assertIn("ReferenceProposal", schema["$defs"])
        self.assertNotIn("Citation", schema["$defs"])

    def test_v2_transport_rejects_legacy_proposal_without_repair(self):
        from tests.graph.test_inference import config, server
        from agent_graph.inference import ChatModel
        legacy = dict(action="propose", source_id=None, start_line=None, end_line=None,
                      proposals=[dict(key="test", kind="hypothesis", statement="legacy",
                                      citations=[dict(source_id="stub", start_line=1, end_line=1, quote="text")], supersedes=None)])
        with server(reply=legacy) as (url, _), self.assertRaises(GraphError) as caught:
            ChatModel(config(url, protocol="evidence-refs-v2")).complete([dict(role="user", content="stub")])
        self.assertEqual(caught.exception.code, "model_unavailable_or_invalid")
