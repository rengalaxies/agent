import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from tools.autonomous_mvp import ledger, runner
from tools.autonomous_mvp.tests.helpers import Clock, FakeProtocol, act, claim, small_program
from tools.autonomous_mvp.transport import ScriptedTransport, TransportResult, reply

MODEL = "openai/gpt-oss-120b"
CANARY = "sk-canary-0123456789abcdef"


class RunnerHarness(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.program, self.cases = small_program()
        self.protocol = FakeProtocol()

    def tearDown(self):
        self.tmp.cleanup()

    def backend_for(self, phase):
        return ledger.FileBackend(self.dir / "ledgers" / f"{phase}.json")

    def execute(self, phase, script, *, models=(MODEL,), protocol=None, clock=None):
        transport = ScriptedTransport(script, models=models)
        work = self.dir / ("work-" + phase)
        work.mkdir(exist_ok=True)
        kwargs = dict(clock=clock.wall, mono=clock.mono) if clock else {}
        state = runner.execute_phase(phase, MODEL, program=self.program, cases=self.cases, manifest_digest="m" * 64,
                                     source_sha="a" * 40, transport=transport, backend_for=self.backend_for,
                                     work=work, protocol=protocol or self.protocol, **kwargs)
        return state, transport

    def stored(self, phase):
        return json.loads((self.dir / "ledgers" / f"{phase}.json").read_text())["state"]


class FullCycle(RunnerHarness):
    def test_transport_phase_completes_read_propose_finish_and_settles_known_usage(self):
        script = []
        for _ in range(3):
            script += [reply(act("read"), prompt_tokens=1000, completion_tokens=100),
                       reply(act("propose", claims=[dict(claim=claim("reporting"))]), prompt_tokens=1200,
                             completion_tokens=50),
                       reply(act("finish"), prompt_tokens=1300, completion_tokens=10)]
        state, transport = self.execute("transport", script)
        self.assertEqual(state["status"], "COMPLETED")
        self.assertEqual(len(transport.sent), 9)
        row = state["case_runs"][0]
        self.assertEqual(row["result"]["terminal"], "FINISHED")
        # 1000*15.86 + 100*61 = 21960 micro-RUB, ceil per attempt; known usage is never charged at worst case.
        self.assertEqual(row["attempts"][0]["cost_micro"], 21960)
        self.assertEqual(row["settled_micro"], sum(a["cost_micro"] for a in row["attempts"]))
        self.assertLess(row["settled_micro"], row["reserved_micro"])
        self.assertTrue(runner.requirement_met("development", self.stored("transport")))

    def test_provider_echoing_the_key_in_a_stored_field_stops_the_write(self):
        self.program["phases"]["transport"]["repeat"] = 1
        echoed = reply(act("finish"))
        echoed.returned_model = CANARY  # `model` of the response body is one of the persisted safe fields.
        with mock.patch.dict("os.environ", {"CLOUDRU_FOUNDATION_API_KEY": CANARY}):
            with self.assertRaises(ledger.LedgerError) as raised:
                self.execute("transport", [echoed])
        self.assertEqual(raised.exception.code, "ledger_secret_detected")
        self.assertNotIn(CANARY, (self.dir / "ledgers" / "transport.json").read_text())

    def test_model_content_is_never_persisted(self):
        script = [reply(act("read", note=CANARY)), reply(act("finish"))] * 3
        self.execute("transport", script)
        self.assertNotIn(CANARY, (self.dir / "ledgers" / "transport.json").read_text())


class Limits(RunnerHarness):
    def test_step_limit_sends_exactly_max_steps_requests(self):
        self.program["phases"]["transport"]["repeat"] = 1
        state, transport = self.execute("transport", [reply(act("read"))] * 20)
        result = state["case_runs"][0]["result"]
        self.assertEqual(result["terminal"], "STEP_LIMIT")
        self.assertEqual(len(transport.sent), self.cases["S01"]["limits"]["max_model_steps"])

    def test_late_response_is_never_shown_to_the_executor(self):
        self.program["phases"]["transport"]["repeat"] = 1
        self.cases["S01"] = dict(self.cases["S01"], limits=dict(self.cases["S01"]["limits"], case_seconds=0.3))
        state, _ = self.execute("transport", [("sleep", 1.0), reply(act("finish"))])
        result = state["case_runs"][0]["result"]
        self.assertEqual(result["terminal"], "DEADLINE")
        self.assertEqual(self.protocol.seen, [])
        self.assertEqual(result["steps"], [])

    def test_invalid_actions_stop_after_the_configured_limit(self):
        self.program["phases"]["transport"]["repeat"] = 1
        state, transport = self.execute("transport", [reply(act("dance"))] * 10)
        result = state["case_runs"][0]["result"]
        self.assertEqual(result["terminal"], "ACTION_REJECTED_LIMIT")
        self.assertEqual(len(transport.sent), self.program["parameters"]["max_invalid_actions_per_case"] + 1)
        self.assertEqual(result["steps"][0]["errors"], [dict(path="action", type="literal_error")])

    def test_truncated_output_is_an_action_failure_not_a_transport_failure(self):
        self.program["phases"]["transport"]["repeat"] = 1
        state, _ = self.execute("transport", [reply(act("read"), finish_reason="length"), reply(act("finish"))])
        row = state["case_runs"][0]
        self.assertTrue(all(a["ok"] for a in row["attempts"]))
        self.assertEqual(row["result"]["steps"][0]["layer"], "completion")
        self.assertEqual(row["result"]["terminal"], "FINISHED")


class Failures(RunnerHarness):
    def test_server_error_ends_the_case_without_retry_and_books_worst_case_for_unknown_usage(self):
        self.program["phases"]["transport"]["repeat"] = 1
        state, transport = self.execute("transport", [TransportResult(ok=False, code="http_server_error",
                                                                       http_status=503)])
        row = state["case_runs"][0]
        self.assertEqual(len(transport.sent), 1)
        self.assertEqual(row["result"]["terminal"], "TRANSPORT_FAILED")
        self.assertEqual(row["settled_micro"], state["worst_micro_per_request"])

    def test_unauthorized_stops_the_phase_and_keeps_the_attempt(self):
        with self.assertRaises(runner.RunnerError) as raised:
            self.execute("transport", [TransportResult(ok=False, code="http_unauthorized", http_status=401)])
        self.assertEqual(raised.exception.code, "breaker_unauthorized")
        state = self.stored("transport")
        self.assertEqual(state["status"], "STOPPED_breaker_unauthorized")
        self.assertEqual(len(state["case_runs"][0]["attempts"]), 1)
        self.assertEqual(state["case_runs"][0]["settled_micro"], state["worst_micro_per_request"])

    def test_five_consecutive_transport_failures_trip_the_breaker(self):
        self.program["phases"]["transport"]["repeat"] = 6
        failures = [TransportResult(ok=False, code="timeout")] * 6
        with self.assertRaises(runner.RunnerError) as raised:
            self.execute("transport", failures)
        self.assertEqual(raised.exception.code, "breaker_consecutive_transport_failures")
        self.assertEqual(len(self.stored("transport")["case_runs"]), 5)

    def test_unavailable_model_stops_before_any_ledger_write(self):
        with self.assertRaises(runner.RunnerError) as raised:
            self.execute("transport", [reply(act("finish"))], models=("some/other-model",))
        self.assertEqual(raised.exception.code, "model_not_available")
        self.assertFalse((self.dir / "ledgers" / "transport.json").exists())


class PhaseRules(RunnerHarness):
    def test_a_phase_runs_once_and_a_rerun_is_refused(self):
        self.program["phases"]["transport"]["repeat"] = 1
        self.execute("transport", [reply(act("finish"))])
        with self.assertRaises(ledger.LedgerError) as raised:
            self.execute("transport", [reply(act("finish"))])
        self.assertEqual(raised.exception.code, "phase_already_started_no_rerun")

    def test_development_requires_a_passed_transport_phase(self):
        with self.assertRaises(runner.RunnerError) as raised:
            self.execute("development", [])
        self.assertEqual(raised.exception.code, "phase_requirement_not_met:transport")
        # A completed transport phase without two full cycles is still not enough.
        self.program["phases"]["transport"]["repeat"] = 3
        self.execute("transport", [reply(act("dance")), reply(act("finish"))] * 3)
        with self.assertRaises(runner.RunnerError):
            self.execute("development", [])

    def test_evaluation_refuses_an_interim_protocol(self):
        interim = FakeProtocol()
        interim.interim = True
        with self.assertRaises(runner.RunnerError) as raised:
            self.execute("evaluation-1", [], protocol=interim)
        self.assertEqual(raised.exception.code, "evaluation_requires_full_protocol")

    def test_money_cap_refuses_a_case_whose_worst_case_does_not_fit(self):
        backend = ledger.FileBackend(self.dir / "cap.json")
        led = ledger.Ledger(backend, dict(run_id="r", phase="p", model="m", manifest_digest="d", source_sha="s",
                                          request_cap=100, money_cap_micro=25, worst_micro_per_request=10,
                                          price=dict(input_per_million="1", output_per_million="1"),
                                          phase_seconds=60))
        led.claim("local", started_epoch=led.clock())
        led.start_case("a", 1, 2)
        with self.assertRaises(ledger.LedgerError) as raised:
            led.start_case("b", 1, 1)
        self.assertEqual(raised.exception.code, "money_cap_reached")

    def test_phase_deadline_is_durable_across_a_restart(self):
        clock = Clock()
        backend = ledger.FileBackend(self.dir / "deadline.json")
        identity = dict(run_id="r", phase="p", model="m", manifest_digest="d", source_sha="s", request_cap=10,
                        money_cap_micro=1000, worst_micro_per_request=1,
                        price=dict(input_per_million="1", output_per_million="1"), phase_seconds=60)
        ledger.Ledger(backend, identity, clock=clock.wall).claim("local", started_epoch=clock.wall())
        clock.offset = 61
        restarted = ledger.Ledger(backend, identity, clock=clock.wall)
        with self.assertRaises(ledger.LedgerError) as raised:
            restarted.start_case("a", 1, 1)
        self.assertEqual(raised.exception.code, "phase_deadline")
        self.assertEqual(json.loads((self.dir / "deadline.json").read_text())["state"]["status"],
                         "STOPPED_PHASE_DEADLINE")

    def test_concurrent_writer_conflict_stops_instead_of_forking(self):
        backend = ledger.FileBackend(self.dir / "cas.json")
        identity = dict(run_id="r", phase="p", model="m", manifest_digest="d", source_sha="s", request_cap=10,
                        money_cap_micro=1000, worst_micro_per_request=1,
                        price=dict(input_per_million="1", output_per_million="1"), phase_seconds=60)
        first = ledger.Ledger(backend, identity)
        first.claim("one", started_epoch=first.clock())
        stale = ledger.Ledger(backend, identity)
        first.start_case("a", 1, 1)
        stale.state["status"] = "RUNNING"
        with self.assertRaises(ledger.LedgerError) as raised:
            stale.start_case("b", 1, 1)
        self.assertEqual(raised.exception.code, "ledger_write_conflict")


if __name__ == "__main__":
    unittest.main()
