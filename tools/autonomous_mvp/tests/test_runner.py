"""Runner + real 2A executor + ledger, offline. Only the transport is scripted."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.autonomous_mvp import ledger, runner
from tools.autonomous_mvp.tests.helpers import CASES, MODEL, agent, one_model_program, run_phase, stored, subset
from tools.autonomous_mvp.transport import ScriptedTransport, TransportResult, reply

CANARY = "sk-canary-0123456789abcdef"


class Harness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def single(self, case_id, transport):
        """One case as a development phase with no prerequisite; returns (state, its ledger row)."""
        program = one_model_program(development=dict(requires=None, split=CASES[case_id]["split"]))
        state = run_phase(self.dir, "development", transport, program=program, cases=subset(case_id))
        return state, state["case_runs"][0]


class FullCycle(Harness):
    def test_transport_phase_runs_read_propose_finish_through_the_executor_and_settles_usage(self):
        state = run_phase(self.dir, "transport", agent())
        self.assertEqual(state["status"], "COMPLETED")
        row = state["case_runs"][0]
        result = row["result"]
        self.assertEqual((result["terminal"], result["final"]["outcome"]), ("FINISHED", "supported_dependency"))
        self.assertEqual([s["action"] for s in result["steps"]],
                         ["read_source", "read_source", "propose_dependency", "finish"])
        self.assertEqual([c["confidence"] for c in result["claims"]], ["CONFIRMED_WITHIN_PROFILE"])
        self.assertTrue(result["constitution_version"].startswith("agent-service-v1.0:"))
        self.assertLess(row["settled_micro"], row["reserved_micro"])
        self.assertTrue(runner.requirement_met("development", stored(self.dir, "transport")))

    def test_each_case_run_records_the_model_profile_of_the_requests_it_sent(self):
        transport, sent = agent(), []
        complete = transport.complete
        transport.complete = lambda payload, *, deadline: (sent.append(payload), complete(payload, deadline=deadline))[1]
        state = run_phase(self.dir, "transport", transport)
        [profile] = {json.dumps(r["result"]["model_profile"], sort_keys=True) for r in state["case_runs"]}
        profile = json.loads(profile)
        program = one_model_program()
        p = program["parameters"]
        # The record is what went over the wire...
        self.assertTrue(sent)
        for payload in sent:
            self.assertEqual({k: v for k, v in payload.items() if k not in ("messages", "response_format")},
                             dict(model=MODEL, stream=False, **profile["sampling"],
                                  **{profile["token_parameter"]: profile["max_output_tokens"]}))
            self.assertEqual(payload["response_format"]["json_schema"]["name"], profile["response_format"]["name"])
        # ...and what the program fixed for this model.
        self.assertEqual((profile["endpoint"], profile["token_parameter"], profile["max_output_tokens"],
                          profile["context_tokens"], profile["max_prompt_bytes"], profile["sampling"]),
                         (program["provider"]["chat_endpoint"], p["token_parameter"],
                          program["models"][0]["max_completion_tokens"], p["context_tokens"], p["max_prompt_bytes"],
                          {"temperature": p["temperature"]}))

    def test_hypothesis_beyond_the_grammar_is_admitted_only_as_a_candidate(self):
        _, row = self.single("D07", agent())
        self.assertEqual(row["result"]["final"]["outcome"], "hypotheses_only")
        self.assertEqual([(c["kind"], c["origin"], c["confidence"]) for c in row["result"]["claims"]],
                         [("hypothesis", "model_hypothesis", "CANDIDATE")])

    def test_decoy_fact_is_refused_by_the_static_check(self):
        _, row = self.single("D04", agent("decoy_taker"))
        facts = [c for c in row["result"]["claims"] if c["kind"] == "fact" and c["claim"]["provider_service"] == "orders"]
        self.assertTrue(facts)
        self.assertTrue(all(c["sufficiency"] == "INSUFFICIENT" and not c["admitted"] for c in facts))


class Adversarial(Harness):
    def test_forged_refs_are_rejected_at_the_evidence_layer_before_the_real_edge_is_admitted(self):
        _, row = self.single("D06", agent())
        first = row["result"]["steps"][0]
        self.assertEqual((first["valid"], first["layer"], first["reason_code"]),
                         (False, "evidence", "invalid_evidence_reference"))
        forged = [c for c in row["result"]["claims"] if c["provenance"] == "REJECTED"]
        self.assertEqual(len(forged), 1)
        self.assertFalse(forged[0]["admitted"])
        self.assertEqual(row["result"]["final"]["outcome"], "supported_dependency")

    def test_injected_read_of_an_unlisted_path_is_refused_and_the_case_continues(self):
        _, row = self.single("D11", agent())
        first = row["result"]["steps"][0]
        self.assertEqual((first["valid"], first["layer"]), (False, "evidence"))
        self.assertEqual(row["result"]["final"]["outcome"], "supported_dependency")

    def test_invalid_json_ends_the_case_after_the_constitution_limit(self):
        _, row = self.single("S01", agent("broken"))
        result = row["result"]
        self.assertEqual(result["terminal"], "ACTION_REJECTED_LIMIT")
        self.assertEqual(len(row["attempts"]), 3)  # max_invalid_actions = 2: the third rejection ends it
        self.assertEqual({(s["layer"], s["reason_code"]) for s in result["steps"]}, {("json", "json_syntax")})

    def test_schema_diagnostic_names_the_path_but_never_the_model_key(self):
        bad = json.dumps(dict(action=dict(name="finish", outcome="complete", reason="done", leaked_sk_live_1=True)))
        _, row = self.single("S01", ScriptedTransport([reply(bad)] * 3, models=[MODEL]))
        self.assertEqual(row["result"]["steps"][0]["errors"][0]["type"], "absent")
        self.assertNotIn("leaked", json.dumps(row))


class GraphTools(Harness):
    """Persistent graph built by the runner, queried through the executor's graph_* tools."""

    def test_graph_ids_cited_as_evidence_are_rejected_and_the_code_read_is_needed(self):
        _, row = self.single("D22", agent())
        steps = row["result"]["steps"]
        self.assertEqual([s["action"] for s in steps[:2]], ["graph_find", "graph_impact"])
        rejected = [c for c in row["result"]["claims"] if c["graph_refs"]]
        self.assertEqual([(c["provenance"], c["admitted"]) for c in rejected], [("REJECTED", False)])
        self.assertEqual(steps[2]["reason_code"], "invalid_evidence_reference")
        self.assertEqual(row["result"]["final"]["outcome"], "supported_dependency")

    def test_revoked_repository_is_invisible_in_graph_results(self):
        _, row = self.single("D23", agent())
        graph = row["result"]["graph"]
        self.assertEqual(graph["calls"].get("graph_find"), 2)  # one search was for the revoked service
        self.assertEqual(graph["revoked_leaks"], 0)
        self.assertNotIn("shadow-ledger", graph["owners"])

    def test_owner_statuses_come_from_the_operator_mapping(self):
        _, row = self.single("D24", agent())
        self.assertEqual(row["result"]["graph"]["owners"],
                         {"ops-report": "KNOWN", "cash-flow": "CONFLICT", "night-audit": "UNKNOWN"})


class Limits(Harness):
    def test_step_limit_control_stops_after_two_requests(self):
        _, row = self.single("D14", agent())
        self.assertEqual(row["result"]["terminal"], "STEP_LIMIT")
        self.assertEqual(len(row["attempts"]), 2)

    def test_late_reply_is_never_executed(self):
        _, row = self.single("D15", agent())
        self.assertEqual(row["result"]["terminal"], "DEADLINE")
        self.assertEqual(row["result"]["steps"], [])
        self.assertTrue(row["attempts"][0]["late"])

    def test_core_refusal_is_a_scored_case_result_not_a_phase_stop(self):
        from agent_graph.contracts import GraphError
        with mock.patch("agent_graph.engine.Graph._current", side_effect=GraphError("stale_context")):
            state, row = self.single("D01", agent())
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual((row["result"]["terminal"], row["result"]["reason_code"]), ("CORE_REFUSED", "stale_context"))


class Failures(Harness):
    def test_server_error_ends_the_case_without_retry_and_books_worst_case_usage(self):
        state, row = self.single("S01", ScriptedTransport(
            [TransportResult(ok=False, code="http_server_error", http_status=503)], models=[MODEL]))
        self.assertEqual(len(row["attempts"]), 1)
        self.assertEqual(row["result"]["terminal"], "TRANSPORT_FAILED")
        self.assertEqual(row["settled_micro"], state["worst_micro_per_request"])

    def test_truncated_output_is_a_failed_exchange_with_known_usage(self):
        _, row = self.single("S01", ScriptedTransport(
            [reply(json.dumps(dict(action=dict(name="list_sources", repository=None))), finish_reason="length")],
            models=[MODEL]))
        self.assertEqual(row["result"]["terminal"], "TRANSPORT_FAILED")
        self.assertEqual(row["attempts"][0]["finish_reason"], "length")
        self.assertIsNotNone(row["attempts"][0]["usage"])

    def test_unauthorized_stops_the_phase_and_keeps_the_attempt(self):
        with self.assertRaises(runner.RunnerError) as raised:
            run_phase(self.dir, "transport", ScriptedTransport(
                [TransportResult(ok=False, code="http_unauthorized", http_status=401)], models=[MODEL]))
        self.assertEqual(raised.exception.code, "breaker_unauthorized")
        state = stored(self.dir, "transport")
        self.assertEqual(state["status"], "STOPPED_breaker_unauthorized")
        self.assertEqual(len(state["case_runs"][0]["attempts"]), 1)

    def test_five_consecutive_transport_failures_trip_the_breaker(self):
        program = one_model_program(transport=dict(repeat=6))
        with self.assertRaises(runner.RunnerError) as raised:
            run_phase(self.dir, "transport", ScriptedTransport([TransportResult(ok=False, code="timeout")] * 6,
                                                               models=[MODEL]), program=program)
        self.assertEqual(raised.exception.code, "breaker_consecutive_transport_failures")
        self.assertEqual(len(stored(self.dir, "transport")["case_runs"]), 5)

    def test_unavailable_model_stops_before_any_ledger_write(self):
        with self.assertRaises(runner.RunnerError) as raised:
            run_phase(self.dir, "transport", ScriptedTransport([], models=["some/other-model"]))
        self.assertEqual(raised.exception.code, "model_not_available")
        self.assertFalse((self.dir / "ledgers" / "transport.json").exists())

    def test_provider_echoing_the_key_in_a_stored_field_stops_the_write(self):
        echoed = reply(json.dumps(dict(action=dict(name="finish", outcome="abstain", reason="insufficient_evidence"))))
        echoed.returned_model = CANARY  # `model` of the response body is a persisted safe field
        with mock.patch.dict("os.environ", {"CLOUDRU_FOUNDATION_API_KEY": CANARY}):
            with self.assertRaises(ledger.LedgerError) as raised:
                self.single("S01", ScriptedTransport([echoed], models=[MODEL]))
        self.assertEqual(raised.exception.code, "ledger_secret_detected")
        self.assertNotIn(CANARY, (self.dir / "ledgers" / "development.json").read_text())


class PhaseRules(Harness):
    def test_a_phase_runs_once_and_a_rerun_is_refused(self):
        program = one_model_program(transport=dict(repeat=1))
        run_phase(self.dir, "transport", agent(), program=program)
        with self.assertRaises(ledger.LedgerError) as raised:
            run_phase(self.dir, "transport", agent(), program=program)
        self.assertEqual(raised.exception.code, "phase_already_started_no_rerun")

    def test_development_requires_a_passed_transport_phase(self):
        with self.assertRaises(runner.RunnerError) as raised:
            run_phase(self.dir, "development", agent())
        self.assertEqual(raised.exception.code, "phase_requirement_not_met:transport")
        run_phase(self.dir, "transport", agent("broken"))  # completes, but with no full cycle
        with self.assertRaises(runner.RunnerError):
            run_phase(self.dir, "development", agent())

    def test_money_cap_refuses_a_case_whose_worst_case_does_not_fit(self):
        led = ledger.Ledger(ledger.FileBackend(self.dir / "cap.json"), dict(
            run_id="r", phase="p", model="m", manifest_digest="d", source_sha="s", request_cap=100,
            money_cap_micro=25, worst_micro_per_request=10, price=dict(input_per_million="1", output_per_million="1"),
            phase_seconds=60))
        led.claim("local", started_epoch=led.clock())
        led.start_case("a", 1, 2)
        with self.assertRaises(ledger.LedgerError) as raised:
            led.start_case("b", 1, 1)
        self.assertEqual(raised.exception.code, "money_cap_reached")

    def test_phase_deadline_is_durable_across_a_restart(self):
        now = [1000.0]
        identity = dict(run_id="r", phase="p", model="m", manifest_digest="d", source_sha="s", request_cap=10,
                        money_cap_micro=1000, worst_micro_per_request=1,
                        price=dict(input_per_million="1", output_per_million="1"), phase_seconds=60)
        backend = ledger.FileBackend(self.dir / "deadline.json")
        ledger.Ledger(backend, identity, clock=lambda: now[0]).claim("local", started_epoch=now[0])
        now[0] += 61
        with self.assertRaises(ledger.LedgerError) as raised:
            ledger.Ledger(backend, identity, clock=lambda: now[0]).start_case("a", 1, 1)
        self.assertEqual(raised.exception.code, "phase_deadline")
        self.assertEqual(json.loads((self.dir / "deadline.json").read_text())["state"]["status"], "STOPPED_PHASE_DEADLINE")

    def test_concurrent_writer_conflict_stops_instead_of_forking(self):
        identity = dict(run_id="r", phase="p", model="m", manifest_digest="d", source_sha="s", request_cap=10,
                        money_cap_micro=1000, worst_micro_per_request=1,
                        price=dict(input_per_million="1", output_per_million="1"), phase_seconds=60)
        backend = ledger.FileBackend(self.dir / "cas.json")
        first = ledger.Ledger(backend, identity)
        first.claim("one", started_epoch=first.clock())
        stale = ledger.Ledger(backend, identity)
        first.start_case("a", 1, 1)
        with self.assertRaises(ledger.LedgerError) as raised:
            stale.start_case("b", 1, 1)
        self.assertEqual(raised.exception.code, "ledger_write_conflict")


if __name__ == "__main__":
    unittest.main()
