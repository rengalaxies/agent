"""The model path is on only for a batch 2B report that matches the loaded code."""

from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

import yaml

from agent_graph.constitution import DEFAULT_PATH
from agent_service.__main__ import doctor
from agent_service.qualification import check, loaded_fingerprint
from agent_service.smoke import SmokeBench

ENDPOINT = "http://127.0.0.1:9/v1/chat/completions"
MODEL = dict(protocol="actions-v3", endpoint=ENDPOINT, allowed_endpoints=[ENDPOINT], model="OFFLINE-SCRIPT",
             configuration_id="script-v3", allow_source_transfer=True, max_prompt_bytes=60000,
             context_tokens=131072, run_token_cap=10_000_000, installation_token_cap=10_000_000)


def write_report(directory: Path, *, verdict="QUALIFIED", protocol=None, run_id="amvp-2b-test-r1",
                 endpoint=ENDPOINT):
    """An amvp-report-1 document of a 2B run (fields as scorer.report(..., manifest=) writes them)."""
    report = dict(schema="amvp-report-1", run_id=run_id, label="test", manifest_digest="b" * 64,
                  provider=dict(name="test provider", chat_endpoint=endpoint, credential_env="RUNNER_KEY"),
                  models={MODEL["model"]: dict(verdict=verdict)},
                  protocol=loaded_fingerprint(None) if protocol is None else protocol)
    path = directory / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return dict(report_path=str(path), run_id=run_id, report_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


class Script:
    """Offline model: asks the graph about one operation, then abstains."""

    def __init__(self):
        self.operation_id, self.calls, self.answers = None, 0, []

    def complete_raw(self, messages, schema, *, cancel=None, deadline_epoch=None):
        self.calls += 1
        if self.calls == 1:
            action = dict(name="graph_impact", entity_id=self.operation_id, depth=1, limit=10)
        else:
            self.answers.append(json.loads(messages[-1]["content"])["tool_result"])
            action = dict(name="finish", outcome="abstain", reason="insufficient_evidence")
        return json.dumps(dict(action=action)), dict(prompt_tokens=10, completion_tokens=5)


class BenchCase(unittest.TestCase):
    def bench(self, *, qualification, policy_overrides=None):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.model = Script()
        reference = qualification(Path(tmp.name)) if callable(qualification) else qualification
        bench = SmokeBench(Path(tmp.name) / "bench", policy_overrides={"model": MODEL, **(policy_overrides or {})},
                           model=self.model, model_qualification=reference)
        self.addCleanup(bench.close)
        self.model.operation_id = next(h["id"] for h in bench.analyzer.query().find("orders GET /orders", "operation"))
        return bench

    def jira(self, bench):
        bench.deliver_jira()
        bench.drain()
        [text] = bench.jira_texts()
        result = [j for j in bench.service.store.jobs("jira:10012") if j["state"] == "DONE"][-1]["result"]
        return text, result

    def doctor(self, bench):
        out = io.StringIO()
        with redirect_stdout(out):
            code = doctor(bench.service)
        return code, out.getvalue()


class MatchingReportTest(BenchCase):
    def test_matching_qualified_report_runs_the_model_with_the_persistent_graph(self):
        bench = self.bench(qualification=write_report)
        text, result = self.jira(bench)
        [answer] = self.model.answers
        self.assertNotIn("error", answer)  # without graph_store the tool answers graph_unavailable
        self.assertEqual({p["consumer"] for p in answer["result"]["paths"]}, {"reporting", "archive"})
        self.assertEqual(result["model"]["configuration_id"], "script-v3")
        self.assertEqual((result["costs"]["model_calls"], result["costs"]["prompt_tokens"]), (2, 20))
        self.assertEqual(result["status"], "USEFUL")  # the static graph facts, not the model, back it
        self.assertEqual(self.doctor(bench)[0], 0)


class ConstitutionMismatchTest(BenchCase):
    def test_report_for_another_constitution_keeps_the_model_off_and_the_answer_partial(self):
        # The service loads a constitution with one limit changed; the report pinned the shipped one.
        changed = Path(tempfile.mkdtemp()) / "agent-service-v1.yaml"
        data = yaml.safe_load(Path(DEFAULT_PATH).read_text(encoding="utf-8"))
        data["limits"]["max_steps"] = data["limits"]["max_steps"] - 1
        changed.write_text(yaml.safe_dump(data), encoding="utf-8")
        bench = self.bench(qualification=write_report, policy_overrides={"constitution": str(changed)})
        self.assertEqual(bench.analyzer.model_status().reason_code, "qualification_constitution_version_mismatch")
        text, result = self.jira(bench)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual((result["status"], result["reason_code"]), ("PARTIAL", "model_unavailable"))
        self.assertIsNone(result["model"])
        self.assertIn("model_hypothesis_unverified (qualification:qualification_constitution_version_mismatch)", text)
        code, message = self.doctor(bench)
        self.assertEqual(code, 1)
        self.assertIn("версия конституции", message)
        bench.service.reconcile_graph()
        self.assertEqual([(n["kind"], n["detail"]) for n in bench.service.store.notices() if n["kind"] == "model_disabled"],
                         [("model_disabled", "qualification_constitution_version_mismatch")])


class NotQualifiedTest(BenchCase):
    def test_experimental_verdict_never_calls_the_model(self):
        bench = self.bench(qualification=lambda d: write_report(d, verdict="EXPERIMENTAL"))
        text, result = self.jira(bench)
        self.assertEqual(self.model.calls, 0)
        self.assertEqual((result["status"], result["reason_code"]), ("PARTIAL", "model_unavailable"))
        self.assertIn("qualification:model_not_qualified", text)
        code, message = self.doctor(bench)
        self.assertEqual(code, 1)
        self.assertIn("вердикт EXPERIMENTAL", message)

    def test_configured_model_without_a_report_reference_is_never_called(self):
        bench = self.bench(qualification=None)
        bench.deliver_pr("opened")
        bench.drain()
        self.assertEqual(self.model.calls, 0)
        self.assertEqual(bench.analyzer.model_status().reason_code, "qualification_missing")
        self.assertIsNone(bench.analyzer.request_settings()["model_configuration_id"])


class ReportIntegrityTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        # check() reads only the configured model ID of the policy.
        self.policy = SimpleNamespace(model=SimpleNamespace(model=MODEL["model"], endpoint=ENDPOINT))

    def test_report_edited_after_it_was_referenced_is_rejected(self):
        reference = write_report(self.dir)
        report = json.loads(Path(reference["report_path"]).read_text())
        report["models"][MODEL["model"]]["verdict"] = "QUALIFIED"
        report["label"] = "edited"
        Path(reference["report_path"]).write_text(json.dumps(report))
        self.assertEqual(check(reference, self.policy, None).reason_code, "qualification_report_digest_mismatch")

    def test_report_without_a_protocol_fingerprint_cannot_qualify(self):
        reference = write_report(self.dir, protocol={})
        report = json.loads(Path(reference["report_path"]).read_text())
        report.pop("protocol")
        Path(reference["report_path"]).write_text(json.dumps(report))
        reference["report_sha256"] = hashlib.sha256(Path(reference["report_path"]).read_bytes()).hexdigest()
        self.assertEqual(check(reference, self.policy, None).reason_code, "qualification_report_incomplete")

    def test_report_of_another_model_or_run_is_rejected(self):
        reference = write_report(self.dir)
        other = SimpleNamespace(model=SimpleNamespace(model="Qwen/Other", endpoint=ENDPOINT))
        self.assertEqual(check(reference, other, None).reason_code, "model_not_in_qualification")
        self.assertEqual(check({**reference, "run_id": "amvp-2b-other"}, self.policy, None).reason_code,
                         "qualification_report_mismatch")

    def test_report_from_another_provider_endpoint_is_rejected(self):
        reference = write_report(self.dir, endpoint="https://other.example/v1/chat/completions")
        self.assertEqual(check(reference, self.policy, None).reason_code, "qualification_provider_mismatch")

    def test_every_core_file_the_report_pinned_is_compared_but_not_the_2b_harness(self):
        protocol = loaded_fingerprint(None)
        protocol["code_sha256"]["tools/autonomous_mvp/protocol.py"] = "1" * 64  # not loaded by the service
        reference = write_report(self.dir, protocol=protocol)
        self.assertEqual(check(reference, self.policy, None).reason_code, "qualified")
        protocol["code_sha256"]["src/agent_graph/graph_query.py"] = "2" * 64  # loaded: must match
        reference = write_report(self.dir, protocol=protocol)
        self.assertEqual(check(reference, self.policy, None).reason_code, "qualification_code_mismatch")

    def test_changed_action_schema_is_detected(self):
        protocol = loaded_fingerprint(None)
        protocol["schema_sha256"] = "0" * 64
        reference = write_report(self.dir, protocol=protocol)
        self.assertEqual(check(reference, self.policy, None).reason_code, "qualification_schema_sha256_mismatch")


if __name__ == "__main__":
    unittest.main()
