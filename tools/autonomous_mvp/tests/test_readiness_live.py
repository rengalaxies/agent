"""Live readiness configurations offline: qualification before any model call, costs, stopping, comparability.

No request leaves the machine: the service gets an offline model object and the
baseline a scripted transport. The qualification reports are built like the
service's own qualification tests build them.
"""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from agent_graph.contracts import GraphError, Limits, ModelConfig
from agent_service.qualification import loaded_profile
from tests.service.test_qualification import report_document, save
from tools.autonomous_mvp.readiness import baseline, live, program, runner, scorer
from tools.autonomous_mvp.transport import ScriptedTransport, TransportResult, reply

MODEL_ID = "openai/gpt-oss-120b"
CHANGES = runner.load_changes("development")
F01 = next(c["change_id"] for c in CHANGES if c["family"] == "F01_truncation")
F03 = next(c["change_id"] for c in CHANGES if c["family"] == "F03_no_impact_noop")


def qualified_report(directory, model_id=MODEL_ID, **profile):
    """A QUALIFIED 2B report for ``model_id`` whose profile is the readiness service-model profile."""
    section = live.model_section(MODEL_ID)
    used = dict(loaded_profile(SimpleNamespace(model=ModelConfig.model_validate(section),
                                               limits=Limits(max_tool_lines=live.READ_WINDOW))), **profile)
    report = report_document(endpoint=section["endpoint"], profile=used)
    report["models"] = {model_id: report["models"].pop("OFFLINE-SCRIPT")}
    return save(Path(directory), report)


class Finisher:
    """Offline model: one finish action per investigation. ``fail`` raises like a refused request."""

    def __init__(self, fail=False):
        self.calls, self.fail = 0, fail

    def complete_raw(self, messages, schema, **kwargs):
        self.calls += 1
        if self.fail:
            raise GraphError("model_unavailable_or_invalid")
        action = dict(name="finish", outcome="abstain", reason="insufficient_evidence")
        return json.dumps(dict(action=action)), dict(prompt_tokens=1000, completion_tokens=200)


class ServiceModelQualification(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.models = []

    def make(self):
        model = Finisher()
        self.models.append(model)
        return model

    def refused(self, reference):
        with self.assertRaises(SystemExit) as caught:
            runner.model_run(MODEL_ID, reference, make=self.make)
        self.assertEqual(self.models, [])  # refused before any model object exists
        return str(caught.exception)

    def test_without_a_qualification_reference_the_series_is_refused_before_a_model_call(self):
        self.assertIn("qualification_missing", self.refused(None))

    def test_a_report_that_qualified_another_model_is_refused(self):
        self.assertIn("model_not_in_qualification", self.refused(qualified_report(self.tmp, "Qwen/Qwen3-Coder-Next")))

    def test_a_report_with_another_profile_is_refused_and_names_the_field(self):
        message = self.refused(qualified_report(self.tmp, max_output_tokens=1024))
        self.assertIn("qualification_profile_max_output_tokens_mismatch", message)

    def test_a_changed_report_file_is_refused(self):
        reference = qualified_report(self.tmp)
        Path(reference["report_path"]).write_text("{}", encoding="utf-8")
        self.assertIn("qualification_report_digest_mismatch", self.refused(reference))


class ServiceModelRun(unittest.TestCase):
    def run_series(self, only, *, fail=False, seconds=3600):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.models = []

        def make():
            self.models.append(Finisher(fail=fail))
            return self.models[-1]

        live_model = runner.model_run(MODEL_ID, qualified_report(tmp.name), make=make)
        return runner.run_split("development", out=Path(tmp.name) / "ledger.json", only=only, live_model=live_model,
                                series_seconds=seconds)[0]

    def test_a_qualified_model_answers_and_its_tokens_and_roubles_are_booked(self):
        ledger = self.run_series([F01])
        [record] = ledger["records"]
        self.assertIsNone(record["error"])
        self.assertEqual(record["qualification"], "qualified")
        self.assertEqual(ledger["configuration"], "service-model-openai--gpt-oss-120b")
        self.assertEqual((ledger["model_binding"]["model"], ledger["model_binding"]["qualification"]["run_id"]),
                         (MODEL_ID, "amvp-2b-test-r1"))
        calls = record["model_requests"]["calls"]
        self.assertGreaterEqual(calls, 2)  # the Jira and the PR stage each ask the model
        self.assertEqual(record["costs"]["model_calls"], calls)
        self.assertEqual(record["costs"]["prompt_tokens"], 1000 * calls)
        self.assertEqual(record["costs"]["rub"], live.rub(1000 * calls, 200 * calls, live.model_entry(MODEL_ID)["price"]))

    def test_two_changes_whose_requests_all_fail_stop_the_series_and_the_rest_stays_counted(self):
        ledger = self.run_series([F01, F03, CHANGES[-1]["change_id"]], fail=True)
        self.assertEqual(ledger["stopped"], "model_requests_failing")
        self.assertEqual(len(self.models), 2)
        self.assertEqual(ledger["records"][2]["error"], "not_run:model_requests_failing")
        oracle = program.load_oracle("development")
        report = scorer.score(ledger, oracle, rules=program.load()[1]["scoring"])
        self.assertIn(ledger["records"][2]["change_id"], report["errors"])


class SeriesStopRule(unittest.TestCase):
    def test_failures_in_a_row_a_refusing_transport_and_the_deadline_stop_a_series(self):
        now = [0.0]
        stop = live.SeriesStop(100, clock=lambda: now[0])
        self.assertIsNone(stop.observe(3, 3))
        self.assertIsNone(stop.observe(3, 1))  # a change with an answer resets the count
        self.assertIsNone(stop.observe(3, 3))
        self.assertEqual(stop.observe(2, 2), "model_requests_failing")
        self.assertEqual(live.SeriesStop(100).observe(1, 1, ("http_unauthorized",)), "transport_http_unauthorized")
        late = live.SeriesStop(100, clock=lambda: now[0])
        now[0] = 100.0
        self.assertEqual(late.before_change(), "series_deadline")
        self.assertIsNone(live.SeriesStop(100).observe(0, 0))  # no request, nothing failed


class BaselineLive(unittest.TestCase):
    def run_baseline(self, script, only):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.transport = ScriptedTransport(script)
        return baseline.run_split("development", "live", out=Path(tmp.name) / "ledger.json", model_id=MODEL_ID,
                                  transport=self.transport, only=only)[0]

    def test_the_live_baseline_asks_the_service_model_and_books_its_tokens(self):
        finish = json.dumps(dict(action="finish", arguments=dict(outcome="abstain", impacted=[])))
        ledger = self.run_baseline([reply(finish), reply(finish)], [F01])
        [record] = ledger["records"]
        self.assertEqual({p["model"] for p in self.transport.sent}, {MODEL_ID})
        self.assertEqual({p["max_completion_tokens"] for p in self.transport.sent},
                         {live.model_entry(MODEL_ID)["max_completion_tokens"]})
        self.assertEqual((ledger["configuration"], ledger["transport_kind"]), ("baseline-live-openai--gpt-oss-120b",
                                                                               "live"))
        self.assertEqual((record["costs"]["model_calls"], record["costs"]["prompt_tokens"]), (2, 200))
        self.assertEqual(record["costs"]["rub"], live.rub(200, 40, live.model_entry(MODEL_ID)["price"]))

    def test_an_unauthorised_transport_stops_the_series_at_once(self):
        refused = TransportResult(ok=False, code="http_unauthorized", http_status=401)
        ledger = self.run_baseline([refused, refused], [F01, F03])
        self.assertEqual(ledger["stopped"], "transport_http_unauthorized")
        self.assertEqual(len(self.transport.sent), 2)  # one per stage of the first change, none after
        self.assertEqual(ledger["records"][1]["error"], "not_run:transport_http_unauthorized")
        self.assertIsNone(ledger["records"][0]["costs"]["rub"])  # the provider reported no usage

    def test_the_live_baseline_needs_the_model_it_is_compared_with(self):
        with self.assertRaises(SystemExit):
            baseline.run_split("development", "live", out="unused.json")


class Comparability(unittest.TestCase):
    SERVICE = dict(program="6-r3", split="heldout", manifest_digest="m", configuration="service-model-x",
                   model_binding=dict(model=MODEL_ID, endpoint="https://e/v1/chat/completions"))

    def baseline(self, **fields):
        return dict(dict(self.SERVICE, configuration="baseline-live-x", transport_kind="live"), **fields)

    def test_a_live_baseline_of_another_model_revision_or_manifest_is_not_compared(self):
        self.assertIsNone(scorer.comparison_problem(self.SERVICE, self.baseline()))
        other = self.baseline(model_binding=dict(model="Qwen/Qwen3-Coder-Next", endpoint="https://e/v1/chat/completions"))
        self.assertIn("model and endpoint", scorer.comparison_problem(self.SERVICE, other))
        self.assertEqual(scorer.comparison_problem(self.SERVICE, self.baseline(manifest_digest="n")),
                         "manifest_digest differs")
        self.assertEqual(scorer.comparison_problem(self.SERVICE, self.baseline(split="development")), "split differs")
        no_model = dict(self.SERVICE, configuration="service-no-model", model_binding=None)
        self.assertIn("model and endpoint", scorer.comparison_problem(no_model, self.baseline()))


if __name__ == "__main__":
    unittest.main()
