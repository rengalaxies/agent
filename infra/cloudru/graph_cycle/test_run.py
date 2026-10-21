import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import run

CORE = Path(os.environ.get("GRAPH_CORE", "../graph-core-candidate")).resolve()
sys.path.insert(0, str(CORE / "src"))
from agent_graph.contracts import GraphError, ModelConfig, ModelReply
from agent_graph.inference import ChatModel, model_payload
from agent_graph.store import Store


def scripted_request(model, messages, flight):
    """Local script exercises the real investigation/tools/validator, no HTTP."""
    model.on_http("request", {})
    model.on_http("http", {"http_status": 200})
    model.on_http("response", {"usage": {"prompt_tokens": 100, "completion_tokens": 100}, "finish_reason": "stop"})
    task = json.loads(messages[1]["content"])
    sources = task["sources"]
    past = [json.loads(m["content"]) for m in messages if m["role"] == "assistant"]
    if len(past) < len(sources):
        s = sources[len(past)]
        value = dict(action="read_source", source_id=s["source_id"], start_line=1,
                     end_line=s["lines"], proposals=[])
    elif len(past) == len(sources):
        evidence = [json.loads(m["content"])["untrusted_source"] for m in messages
                    if m["role"] == "user" and "untrusted_source" in json.loads(m["content"])]
        consumer = next(s["repository"] for s in sources if s["path"] == "client.py")
        provider = "status" if consumer == "health" else "orders"
        citations = [{k: e[k] for k in ("source_id", "start_line", "end_line", "quote")}
                     for e in evidence if e["repository"] in (consumer, provider)]
        value = dict(action="propose", source_id=None, start_line=None, end_line=None,
                     proposals=[dict(key=f"{consumer}->{provider} GET /orders", kind="hypothesis",
                                     statement="Source quotes support this synthetic dependency.",
                                     citations=citations, supersedes=None)])
    else:
        value = dict(action="finish", source_id=None, start_line=None, end_line=None, proposals=[])
    return ModelReply.model_validate(value), dict(prompt_tokens=100, completion_tokens=100)


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.prior_patch = patch.object(run, "prior_case", return_value=None)
        self.prior_patch.start()
        self.addCleanup(self.prior_patch.stop)
        reviewed = patch.object(run, "reviewed_first_case", return_value=None)
        reviewed.start()
        self.addCleanup(reviewed.stop)
        frozen = patch.object(run, "completed_cases", return_value=[])
        frozen.start()
        self.addCleanup(frozen.stop)
        closed = patch.object(run, "experiment_closed", return_value=False)
        closed.start()
        self.addCleanup(closed.stop)

    def test_corporate_config_preserves_cost_guard(self):
        for model in run.CONFIG["models"]:
            config = ModelConfig.model_validate(run.model_config(model))
            self.assertEqual(config.route, "corporate")
            self.assertGreater(config.micro_per_million_tokens, 0)
            self.assertEqual(config.max_output_tokens, 4096)
            self.assertEqual(config.allowed_endpoints, [run.ENDPOINT])
            self.assertEqual(config.api_key_env, "CLOUDRU_FOUNDATION_API_KEY")

    def test_cloud_payload_uses_documented_completion_token_limit(self):
        for name in run.CONFIG["models"]:
            config = ModelConfig.model_validate(run.model_config(name))
            body = json.loads(model_payload(config, [{"role": "user", "content": "synthetic"}]))
            self.assertEqual(body["max_completion_tokens"], 4096)
            self.assertNotIn("max_tokens", body)
            self.assertNotIn("reasoning_effort", body)
            self.assertEqual(body["response_format"]["type"], "json_schema")
            self.assertEqual(config.timeout_seconds, 60)

    @patch.object(ChatModel, "_request", scripted_request)
    def test_remaining_two_cases_preserve_all_fifteen_attempts(self):
        frozen = [json.loads(p.read_text()) for p in (run.HISTORY_ROOT / "partial-series").glob("*/report.json")]
        with tempfile.TemporaryDirectory() as tmp, patch.object(run, "completed_cases", return_value=frozen), patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "1", "CLOUDRU_FOUNDATION_API_KEY": "synthetic"}), patch.object(
                sys, "argv", ["run.py", "--core", str(CORE), "--output", tmp + "/out", "--live"]):
            self.assertEqual(run.main(), 0)
            summary = json.loads(Path(tmp + "/out/summary.json").read_text())
            self.assertEqual(len(summary["results"]), 6)
            self.assertEqual(summary["requests"], 24)
            self.assertEqual(summary["results"][3]["request_count"], 3)
            self.assertFalse(summary["results"][3]["usage_complete"])

    def test_global_and_per_case_ledger_are_conservative(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = run.Ledger(Path(tmp) / "ledger.sqlite3")
            for _ in range(6):
                ledger.reserve("same", "qwen")
            with self.assertRaises(RuntimeError):
                ledger.reserve("same", "qwen")
            for i in range(34):
                ledger.reserve(str(i), "other")
            with self.assertRaises(RuntimeError):
                ledger.reserve("last", "other")
            self.assertEqual(ledger.count(), 40)

    def test_no_secret_in_serialized_reports(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"CLOUDRU_FOUNDATION_API_KEY": "synthetic-sensitive-value"}):
            target = Path(tmp) / "safe.json"
            run.dump(target, {"untrusted_model_output": "synthetic-sensitive-value"})
            self.assertNotIn("synthetic-sensitive-value", target.read_text())
            self.assertIn("REDACTED", target.read_text())

    def test_expectations_not_in_model_task(self):
        expected = json.loads((run.HERE / "expectations.json").read_text())
        for name in run.CONFIG["cases"]:
            for edge in expected[name]["required"]:
                self.assertNotIn(edge, run.TASK)
        self.assertNotIn("expectations", run.TASK)

    def test_preparation_has_no_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(sys, "argv", ["run.py", "--core", str(CORE), "--output", tmp + "/out"]), patch.object(ChatModel, "complete", side_effect=AssertionError("network")):
            self.assertEqual(run.main(), 0)
            self.assertEqual(json.loads(Path(tmp + "/out/summary.json").read_text())["requests"], 0)

    @patch.object(ChatModel, "_request", scripted_request)
    def test_full_scripted_cases_use_real_tools_and_validator(self):
        for case in run.CONFIG["cases"]:
            with self.subTest(case=case), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                ledger = run.Ledger(root / "ledger.sqlite3")
                store = Store(root / "state")
                try:
                    report = run.run_case(CORE, root / "case", case, run.CONFIG["models"][0], ledger, store)
                finally:
                    store.close()
                self.assertTrue(report["protocol_passed"], report["investigation"])
                self.assertTrue(report["quality"]["passed"], report["quality"])
                self.assertLessEqual(report["request_count"], 6)
                self.assertTrue(report["usage_complete"])
                self.assertEqual(report["proposals"][0]["decision"], "ACCEPTED_UNAPPROVED_CANDIDATE")
                if case == "export-E":
                    self.assertEqual(report["transition"]["before_export_edges"], 0)
                    self.assertEqual(report["transition"]["after_export_edges"], 1)
                    self.assertTrue(report["transition"]["same_view"])
                # Oracle/task expectations are outside every transmitted context.
                for messages in (root / "case").glob("messages-*.json"):
                    self.assertNotIn("never_sent_to_model", messages.read_text())
                    self.assertNotIn('"dependencies"', messages.read_text())
                    for message in json.loads(messages.read_text()):
                        if message["role"] == "user":
                            evidence = json.loads(message["content"]).get("untrusted_source")
                            if evidence:
                                self.assertEqual("\n".join(line["text"] for line in evidence["numbered_lines"]), evidence["quote"])
                                self.assertEqual(evidence["numbered_lines"][0]["line"], evidence["start_line"])

    def test_core_rejects_fabricated_quote(self):
        def forged(model, messages, flight):
            reply, usage = scripted_request(model, messages, flight)
            if reply.action == "propose":
                reply.proposals[0].citations[0].quote = "fabricated evidence"
            return reply, usage
        with tempfile.TemporaryDirectory() as tmp, patch.object(ChatModel, "_request", forged):
            root = Path(tmp)
            ledger = run.Ledger(root / "ledger.sqlite3")
            store = Store(root / "state")
            try:
                report = run.run_case(CORE, root / "case", "reporting-http", run.CONFIG["models"][0], ledger, store)
            finally:
                store.close()
            self.assertFalse(report["protocol_passed"])
            self.assertTrue(report["transport_action_protocol_passed"])
            self.assertFalse(report["quality"]["passed"])
            self.assertEqual(report["proposals"][0]["decision"], "REJECTED")
            self.assertEqual(report["proposals"][0]["reason"], "evidence_mismatch")

    def test_late_reads_do_not_satisfy_quality(self):
        oracle = json.loads((run.HERE / "expectations.json").read_text())
        proposal = dict(key="reporting->orders GET /orders", citations=[dict(source_id="a"), dict(source_id="b")])
        records = [dict(decision="ACCEPTED_UNAPPROVED_CANDIDATE", proposal=proposal)]
        actions = [dict(action="propose", proposals=[proposal]),
                   dict(action="read_source", source_id="a"), dict(action="read_source", source_id="b")]
        score = run.score_case("reporting-http", records, actions, {"a": "orders/api.py", "b": "reporting/client.py"}, oracle)
        self.assertFalse(score["passed"])

    @patch.object(ChatModel, "_request", scripted_request)
    def test_whole_series_is_serial_and_bounded(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "1",
            "CLOUDRU_FOUNDATION_API_KEY": "synthetic-only-not-a-real-key"}), patch.object(
                sys, "argv", ["run.py", "--core", str(CORE), "--output", tmp + "/out", "--live"]):
            self.assertEqual(run.main(), 0)
            report = json.loads(Path(tmp + "/out/summary.json").read_text())
            self.assertEqual(report["status"], "SERIES_COMPLETED")
            self.assertEqual(len(report["results"]), 6)
            self.assertLessEqual(report["requests"], 36)
            self.assertEqual(report["results"][0]["model"], run.CONFIG["models"][0])
            for result in report["results"]:
                self.assertTrue(result["quality"]["passed"])
            for file in Path(tmp + "/out").rglob("*.json"):
                self.assertNotIn("synthetic-only-not-a-real-key", file.read_text())

    def test_rerun_is_blocked_before_any_model_call(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "2",
            "CLOUDRU_FOUNDATION_API_KEY": "synthetic-only"}), patch.object(
                sys, "argv", ["run.py", "--core", str(CORE), "--output", tmp + "/out", "--live"]), patch.object(
                    ChatModel, "complete", side_effect=AssertionError("network")):
            self.assertEqual(run.main(), 1)
            report = json.loads(Path(tmp + "/out/summary.json").read_text())
            self.assertEqual(report["status"], "BLOCKED_ACTIONS_FIRST_ATTEMPT_REQUIRED")
            self.assertEqual(report["requests"], 0)

    def test_closed_experiment_blocks_new_live_runs_before_secret_or_network(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(run, "experiment_closed", return_value=True), patch.object(
                sys, "argv", ["run.py", "--core", str(CORE), "--output", tmp + "/out", "--live"]), patch.object(
                    ChatModel, "complete", side_effect=AssertionError("network")):
            self.assertEqual(run.main(), 1)
            self.assertEqual(json.loads(Path(tmp + "/out/summary.json").read_text())["status"], "EXPERIMENT_CLOSED_NO_NETWORK")

    def test_diagnosed_continuation_revalidates_reads_and_keeps_six_call_cap(self):
        prior = json.loads((run.PRIOR / "0-reporting-http/report.json").read_text())
        def corrected(model, messages, flight):
            filtered = [m for m in messages if not (m["role"] == "assistant" and
                        json.loads(m["content"])["action"] == "propose" and
                        (json.loads(m["content"])["source_id"] is not None or "“" in m["content"]))]
            return scripted_request(model, filtered, flight)
        with tempfile.TemporaryDirectory() as tmp, patch.object(run, "prior_case", return_value=prior), patch.object(ChatModel, "_request", corrected):
            root = Path(tmp)
            ledger = run.Ledger(root / "ledger.sqlite3")
            for _ in range(prior["request_count"]):
                ledger.reserve("reporting-http", run.CONFIG["models"][0])
            store = Store(root / "state")
            try:
                report = run.run_case(CORE, root / "case", "reporting-http", run.CONFIG["models"][0], ledger, store)
            finally:
                store.close()
            self.assertTrue(report["protocol_passed"], report["investigation"])
            self.assertTrue(report["quality"]["passed"])
            self.assertEqual(report["request_count"], 6)
            self.assertEqual(ledger.count(), 6)
            self.assertEqual(report["limits"]["max_model_steps"], 2)
            self.assertEqual(report["config"]["run_token_cap"], 100000 - 53240)

    def test_continuation_rejects_changed_snapshot(self):
        prior = json.loads((run.PRIOR / "0-reporting-http/report.json").read_text())
        with self.assertRaises(GraphError):
            run.validated_resume(None, {"basis": "changed"}, prior)

    def test_whole_continuation_keeps_prior_charges(self):
        prior = json.loads((run.PRIOR / "0-reporting-http/report.json").read_text())
        def corrected(model, messages, flight):
            filtered = [m for m in messages if not (m["role"] == "assistant" and
                        json.loads(m["content"])["action"] == "propose" and
                        (json.loads(m["content"])["source_id"] is not None or "“" in m["content"]))]
            return scripted_request(model, filtered, flight)
        with tempfile.TemporaryDirectory() as tmp, patch.object(run, "prior_case", return_value=prior), patch.object(ChatModel, "_request", corrected), patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "1", "CLOUDRU_FOUNDATION_API_KEY": "synthetic"}), patch.object(
                sys, "argv", ["run.py", "--core", str(CORE), "--output", tmp + "/out", "--live"]):
            self.assertEqual(run.main(), 0)
            report = json.loads(Path(tmp + "/out/summary.json").read_text())
            self.assertEqual(len(report["results"]), 6)
            self.assertEqual(report["results"][0]["request_count"], 6)
            self.assertEqual(report["requests"], sum(r["request_count"] for r in report["results"]))

    @patch.object(ChatModel, "_request", scripted_request)
    def test_reviewed_rejection_skips_first_case_and_runs_remaining_series(self):
        reviewed = json.loads(run.REVIEWED_FIRST.read_text())
        with tempfile.TemporaryDirectory() as tmp, patch.object(run, "reviewed_first_case", return_value=reviewed), patch.dict(os.environ, {
            "GITHUB_ACTIONS": "true", "GITHUB_RUN_ATTEMPT": "1", "CLOUDRU_FOUNDATION_API_KEY": "synthetic"}), patch.object(
                sys, "argv", ["run.py", "--core", str(CORE), "--output", tmp + "/out", "--live"]):
            self.assertEqual(run.main(), 0)
            summary = json.loads(Path(tmp + "/out/summary.json").read_text())
            self.assertEqual(len(summary["results"]), 6)
            self.assertFalse(summary["results"][0]["quality"]["passed"])
            self.assertFalse(summary["results"][0]["protocol_passed"])
            self.assertTrue(summary["results"][0]["transport_action_protocol_passed"])
            self.assertEqual(summary["results"][0]["request_count"], 5)
            self.assertEqual(summary["requests"], sum(r["request_count"] for r in summary["results"]))


if __name__ == "__main__":
    unittest.main()
