"""Offline only: durable fake backend + local HTTP stubs + scripted test replies."""
import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from agent_graph.contracts import GraphError
from agent_graph.evidence_refs import ReferenceReply
from agent_graph.inference import ChatModel
from tools.evidence_refs_ledger import GitHubLedgerBackend, RunLedger
from tools.prepare_evidence_refs_experiment import RehearsalLedger, manifest
from tools.run_evidence_refs_experiment import AccountedModel, run_series, save_report


class Backend:
    """Test-only CAS storage, serialized between independent ledger objects."""
    def __init__(self):
        self.head = None
        self.data = None
        self.revision = 0
        self.fail = False
        self.on_write = None

    def read(self, **kwargs):
        return self.head, copy.deepcopy(self.data)

    def write(self, expected, data):
        if self.fail or expected != self.head:
            raise GraphError("ledger_write_conflict")
        self.revision += 1
        self.head = str(self.revision)
        self.data = json.loads(json.dumps(data))
        if self.on_write:
            self.on_write()
        return self.head


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.packet = manifest()
        self.clock = [time.time()]
        self.backend = Backend()
        self.ledger = RunLedger(self.backend, self.packet, "a" * 40, clock=lambda: self.clock[0])
        self.ledger.initialize(30, 1_000_000_000)
        self.model = self.packet["plan"]["models"][0]

    def claim(self):
        self.ledger.claim("test-run", started_epoch=self.clock[0])
        return self.ledger.start_case("reporting-http", self.model)

    def test_history_unknown_usage_and_new_results_are_separate(self):
        key, _ = self.claim()
        number = self.ledger.reserve(key, "test-only-digest")
        self.ledger.record(number, dict(http_status=503, usage=None), "model_http_error")
        report = self.ledger.report()
        self.assertEqual(report["lifetime_request_count"], 22)
        self.assertEqual(report["historical_unknown_usage_ids"], [15])
        self.assertEqual(report["new_unknown_usage_ids"], [22])
        self.assertEqual(report["new_attempts"][0]["http_status"], 503)
        self.assertFalse(report["historical_results_in_new_score"])
        self.assertEqual(report["historical_usage"]["observed_prompt_tokens"], 24208)
        self.assertIsNone(report["lifetime_usage"]["total_prompt_tokens"])
        self.assertGreater(report["reserved_new_micro"], 0)

    def test_missing_execute_never_initializes_and_repeat_initialize_never_resets(self):
        empty = RunLedger(Backend(), self.packet, "a" * 40)
        with self.assertRaisesRegex(GraphError, "ledger_missing_initialize"):
            empty.claim("test", started_epoch=time.time())
        with self.assertRaisesRegex(GraphError, "ledger_already_initialized"):
            self.ledger.initialize(30, 1_000_000_000)

    def test_restart_or_other_run_cannot_reclaim_or_clear_pending_attempt(self):
        key, _ = self.claim()
        self.ledger.reserve(key, "digest")
        other = RunLedger(self.backend, self.packet, "a" * 40)
        with self.assertRaisesRegex(GraphError, "series_already_started_no_rerun"):
            other.claim("new-run", started_epoch=time.time())
        self.assertEqual(len(other.state["attempts"]), 1)
        self.assertIsNone(other.state["attempts"][0]["usage"])

    def test_cas_rejects_concurrent_initialization(self):
        backend = Backend()
        one = RunLedger(backend, self.packet, "a" * 40)
        two = RunLedger(backend, self.packet, "a" * 40)
        one.initialize(30, 1_000_000_000)
        with self.assertRaisesRegex(GraphError, "ledger_write_conflict"):
            two.initialize(1, 1)
        self.assertEqual(backend.data["request_cap"], 30)

    def test_expiration_is_durable_and_clock_cannot_reopen_case(self):
        key, deadline = self.claim()
        self.clock[0] = deadline
        with self.assertRaisesRegex(GraphError, "series_or_case_deadline"):
            self.ledger.reserve(key, "digest")
        self.clock[0] = deadline - 1
        other = RunLedger(self.backend, self.packet, "a" * 40, clock=lambda: self.clock[0])
        with self.assertRaisesRegex(GraphError, "series_not_running"):
            other.check(key)
        self.assertEqual(other.state["status"], "STOPPED_DEADLINE")

    def test_original_rehearsal_expiration_rollback_regression(self):
        with tempfile.TemporaryDirectory() as d:
            ledger = RehearsalLedger(Path(d) / "db", self.packet, now=1000)
            try:
                ledger.simulate_attempt(self.model, "reporting-http", now=1000)
                with self.assertRaisesRegex(GraphError, "case_deadline"):
                    ledger.simulate_attempt(self.model, "reporting-http", now=1300)
                with self.assertRaisesRegex(GraphError, "case_deadline"):
                    ledger.simulate_attempt(self.model, "reporting-http", now=1299)
            finally:
                ledger.close()

    def test_budget_is_reserved_before_transport_and_error_not_refunded(self):
        key, deadline = self.claim()
        from tests.graph.test_inference import config
        model = AccountedModel(config("http://127.0.0.1:1/v1/chat/completions"), self.ledger, key, deadline)
        def fail(*args, **kwargs):
            self.assertEqual(len(self.backend.data["attempts"]), 1)
            self.assertEqual(self.backend.data["attempts"][0]["status"], "RESERVED_USAGE_UNKNOWN")
            kwargs["on_finished"]()
            raise GraphError("model_timeout")
        ended = []
        with patch.object(ChatModel, "complete", fail), self.assertRaisesRegex(GraphError, "model_timeout"):
            model.complete([], on_finished=lambda: ended.append(True))
        self.assertEqual(ended, [True])
        self.assertEqual(self.backend.data["attempts"][0]["error"], "model_timeout")
        self.assertIsNone(self.backend.data["attempts"][0]["usage"])
        self.assertGreater(self.backend.data["attempts"][0]["reserved_micro"], 0)

    def test_failed_reservation_or_elapsed_ledger_wait_prevents_transport(self):
        key, deadline = self.claim()
        from tests.graph.test_inference import config
        model = AccountedModel(config("http://127.0.0.1:1/v1/chat/completions"), self.ledger, key, deadline)
        self.backend.on_write = lambda: self.clock.__setitem__(0, deadline)
        ended = []
        with patch.object(ChatModel, "complete") as transport, self.assertRaises(GraphError):
            model.complete([], on_finished=lambda: ended.append(True))
        transport.assert_not_called()
        self.assertEqual(ended, [True])
        self.assertEqual(len(self.backend.data["attempts"]), 1)

    def test_caps_survive_restart_and_do_not_refund_unknown(self):
        key, _ = self.claim()
        for _ in range(5):
            self.ledger.reserve(key, "digest")
        with self.assertRaisesRegex(GraphError, "case_request_limit"):
            self.ledger.reserve(key, "digest")
        for case, model in [(c, m) for c in self.packet["plan"]["case_order"] for m in self.packet["plan"]["models"]][1:]:
            key, _ = self.ledger.start_case(case, model)
            for _ in range(5):
                self.ledger.reserve(key, "digest")
        self.assertEqual(len(self.backend.data["attempts"]), 30)
        with self.assertRaisesRegex(GraphError, "new_budget_exhausted"):
            self.ledger.reserve(key, "digest")
        self.assertTrue(all(r["usage"] is None for r in self.backend.data["attempts"]))

    def test_low_money_cap_prevents_transport(self):
        backend = Backend()
        ledger = RunLedger(backend, self.packet, "a" * 40)
        ledger.initialize(30, 1)
        ledger.claim("test", started_epoch=time.time())
        key, _ = ledger.start_case("reporting-http", self.model)
        with self.assertRaisesRegex(GraphError, "new_budget_exhausted"):
            ledger.reserve(key, "digest")
        self.assertEqual(ledger.state["attempts"], [])

    def test_source_or_manifest_change_is_rejected(self):
        with self.assertRaisesRegex(GraphError, "ledger_identity_mismatch"):
            RunLedger(self.backend, self.packet, "b" * 40)
        packet = copy.deepcopy(self.packet)
        packet["manifest_digest"] = "wrong"
        with self.assertRaisesRegex(GraphError, "ledger_identity_mismatch"):
            RunLedger(self.backend, packet, "a" * 40)

    def test_secret_canary_cannot_enter_ledger_or_artifact(self):
        with patch.dict(os.environ, {"CLOUDRU_FOUNDATION_API_KEY": "secret-canary-never-export"}):
            self.ledger.state["injected"] = "secret-canary-never-export"
            with self.assertRaisesRegex(GraphError, "ledger_secret_detected"):
                self.ledger._save()
            self.assertNotIn("injected", self.backend.data)
            with tempfile.TemporaryDirectory() as d, self.assertRaisesRegex(GraphError, "report_secret_detected"):
                save_report(Path(d) / "report.json", {"message": "secret-canary-never-export"})
            self.assertNotIn("secret-canary-never-export", json.dumps(self.backend.data))

    def test_github_backend_uses_single_fixed_ref_and_non_force_parent_commit(self):
        backend = GitHubLedgerBackend("rengalaxies/agent", "test-token")
        calls = []
        def api(method, path, body=None, **kwargs):
            calls.append((method, path, body))
            return {"sha": "test-object"}
        with patch.object(backend, "_api", api):
            backend.write("expected-parent", {"safe": True})
        commit = next(body for method, path, body in calls if path == "/git/commits")
        self.assertEqual(commit["parents"], ["expected-parent"])
        self.assertEqual(calls[-1], ("PATCH", "/git/refs/heads/experiment-state/evidence-refs-v2", {"sha": "test-object", "force": False}))
        self.assertNotIn("test-token", json.dumps(calls))


    def test_github_redirect_and_error_body_cannot_expose_credentials(self):
        from io import BytesIO
        import urllib.error
        from tools.evidence_refs_ledger import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "moved", {}, "https://attacker.test"))
        backend = GitHubLedgerBackend("rengalaxies/agent", "fake-canary-token")
        error = urllib.error.HTTPError("https://api.github.com", 403, "denied", {}, BytesIO(b"fake-canary-token"))
        with patch("urllib.request.build_opener") as opener, self.assertRaises(GraphError) as caught:
            opener.return_value.open.side_effect = error
            backend.read()
        self.assertEqual(str(caught.exception), "ledger_http_error")
        self.assertNotIn("fake-canary-token", str(caught.exception))


class DeadlineTransportTests(unittest.TestCase):
    def test_absolute_remaining_time_bounds_body_not_fresh_full_timeout(self):
        from tests.graph.test_transport_regressions import config, http_stub
        metadata = {}
        with http_stub(body_pause=1) as (url, _, calls):
            started = time.monotonic()
            with self.assertRaisesRegex(GraphError, "model_timeout"):
                ChatModel(config(url, timeout_seconds=5)).complete([], deadline_epoch=time.time() + .15, metadata=metadata)
            self.assertLess(time.monotonic() - started, .7)
        self.assertEqual(calls, [1])
        self.assertEqual(metadata.get("http_status"), 200)
        self.assertIsNone(metadata.get("usage"))

    def test_expired_absolute_deadline_sends_nothing(self):
        from tests.graph.test_inference import config, server
        with server() as (url, calls), self.assertRaisesRegex(GraphError, "model_timeout"):
            ChatModel(config(url)).complete([], deadline_epoch=time.time() - 1)
        self.assertEqual(calls, [])

    def test_cloud_token_parameter_opt_in_and_v1_default_preserved(self):
        from tests.graph.test_inference import config, server
        for parameter in ["max_completion_tokens", "max_tokens"]:
            with server() as (url, calls):
                ChatModel(config(url, token_parameter=parameter)).complete([])
            self.assertEqual(calls[0]["body"][parameter], 1024)
            self.assertNotIn("max_tokens" if parameter == "max_completion_tokens" else "max_completion_tokens", calls[0]["body"])

    def test_valid_usage_preserved_even_when_action_schema_is_invalid(self):
        from tests.graph.test_inference import config, server
        metadata = {}
        with server(reply={"action": "invalid"}) as (url, _), self.assertRaises(GraphError):
            ChatModel(config(url)).complete([], metadata=metadata)
        self.assertEqual(metadata["http_status"], 200)
        self.assertEqual(metadata["usage"], dict(prompt_tokens=20, completion_tokens=30))

    def test_deadline_at_admission_rolls_back_candidate(self):
        from tests.graph.test_evidence_refs import fixture, reads, proposal
        from agent_graph.evidence_refs import EvidenceSession
        with tempfile.TemporaryDirectory() as d:
            graph = fixture(d)
            try:
                context = graph.prepare_context()
                session = EvidenceSession(graph, context["id"])
                refs = reads(session, context)
                checks = []
                def guard():
                    checks.append(1)
                    if len(checks) == 2:
                        raise GraphError("investigation_deadline")
                with self.assertRaisesRegex(GraphError, "investigation_deadline"):
                    session.propose(proposal("reporting", refs.values()), admission_check=guard)
                self.assertEqual(graph.store.proposals(graph.view), [])
                self.assertEqual(len(checks), 2)
            finally:
                graph.store.close()


class WholeRunnerTests(unittest.TestCase):
    def test_six_scripted_cases_reserve_26_attempts_before_transport_and_finish(self):
        packet = manifest()
        backend = Backend()
        ledger = RunLedger(backend, packet, "a" * 40)
        ledger.initialize(30, 1_000_000_000)
        ledger.claim("SCRIPTED-OFFLINE-ONLY", started_epoch=time.time())
        parameter_sets = []
        def scripted(model, messages, *, on_finished=None, metadata=None, **kwargs):
            self.assertEqual(len(backend.data["attempts"]), len(ledger.state["attempts"]))
            self.assertEqual(backend.data["attempts"][-1]["status"], "RESERVED_USAGE_UNKNOWN")
            self.assertNotIn('"required"', json.dumps(messages))
            self.assertNotIn('"forbidden"', json.dumps(messages))
            values = [json.loads(m["content"]) for m in messages if m["role"] == "user"]
            sources = values[0]["sources"]
            read_values = [v["untrusted_source"] for v in values if "untrusted_source" in v]
            consumer = next(s["repository"] for s in sources if s["path"] == "client.py")
            if len(read_values) < len(sources):
                src = sources[len(read_values)]
                data = dict(action="read_source", source_id=src["source_id"], start_line=1, end_line=src["lines"], proposals=[])
            elif not any("stored_candidates" in v for v in values):
                # EXPLICIT scripted positive test data, not a real model result.
                claim = dict(consumer_repository=consumer, consumer_service=consumer, provider_service="status" if consumer == "health" else "orders", method="GET", path_template="/orders")
                data = dict(action="propose", source_id=None, start_line=None, end_line=None,
                            proposals=[dict(claim=claim, evidence_refs=[v["evidence_ref"] for v in read_values])])
            else:
                data = dict(action="finish", source_id=None, start_line=None, end_line=None, proposals=[])
            metadata.update(http_status=200, usage=dict(prompt_tokens=10, completion_tokens=10), finish_reason="stop")
            parameter_sets.append(model.config.model_dump(exclude={"model", "configuration_id"}))
            on_finished()
            return ReferenceReply.model_validate(data), dict(prompt_tokens=10, completion_tokens=10)
        with tempfile.TemporaryDirectory() as d, patch.object(ChatModel, "complete", scripted):
            run_series(ledger, Path(d))
        self.assertEqual(len(backend.data["attempts"]), 26)
        self.assertEqual(len(backend.data["cases"]), 6)
        self.assertTrue(all(c["result"]["evaluation"]["all_passed"] for c in backend.data["cases"]))
        self.assertTrue(all(p == parameter_sets[0] for p in parameter_sets))
        self.assertEqual(ledger.report()["lifetime_request_count"], 47)
        self.assertEqual(ledger.report()["historical_unknown_usage_ids"], [15])
        self.assertFalse(any(c["result"]["report"]["model_quality_established"] for c in ledger.state["cases"]))


class ScoreTests(unittest.TestCase):
    def test_rejected_false_claim_counts_even_when_a_correct_candidate_exists(self):
        from tools.run_evidence_refs_experiment import score
        correct = dict(consumer_repository="control-a", consumer_service="svc-a", provider_service="svc-b", method="GET", path_template="/x")
        wrong = {**correct, "provider_service": "decoy-c"}
        report = dict(status="COMPLETED", candidate_ids=["only-correct-test-candidate"], events=[
            dict(reference_proposals=[dict(claim=correct), dict(claim=wrong)], evidence_assessments=[
                dict(provenance=dict(status="AUTHENTIC_AUTHORIZED_CURRENT"), sufficiency=dict(status="SUPPORTED_WITHIN_PROFILE")),
                dict(provenance=dict(status="AUTHENTIC_AUTHORIZED_CURRENT"), sufficiency=dict(status="INSUFFICIENT"))])])
        result = score(report, dict(required=[correct], forbidden=[wrong]))
        self.assertFalse(result["held_out_quality_passed"])
        self.assertFalse(result["sufficiency_passed"])
        self.assertFalse(result["all_passed"])
        self.assertTrue(result["candidates_admitted"])
        self.assertEqual(result["trust"], "UNAPPROVED_CANDIDATE")
        missing_read = score(report, dict(required=[correct], forbidden=[wrong]), {"unread-control-source": 2})
        self.assertFalse(missing_read["corpus_read_protocol_passed"])
        self.assertFalse(missing_read["protocol_passed"])


class StopTests(unittest.TestCase):
    def test_exhausted_budget_or_cancel_stops_before_other_cases(self):
        for cancelled in [False, True]:
            with self.subTest(cancelled=cancelled):
                packet = manifest()
                backend = Backend()
                ledger = RunLedger(backend, packet, "a" * 40)
                ledger.initialize(30, 1_000_000_000 if cancelled else 1)
                ledger.claim("OFFLINE-STOP-CONTROL", started_epoch=time.time())
                calls = []
                def stop(*args, **kwargs):
                    calls.append(1)
                    kwargs["on_finished"]()
                    raise GraphError("cancelled")
                with tempfile.TemporaryDirectory() as d, patch.object(ChatModel, "complete", stop), self.assertRaises(GraphError):
                    run_series(ledger, Path(d))
                self.assertEqual(len(ledger.state["cases"]), 1)
                self.assertEqual(len(calls), 1 if cancelled else 0)
                self.assertFalse(ledger.report()["all_new_cases_passed"])
