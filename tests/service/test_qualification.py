"""The model path is on only for a batch 2B report that matches the loaded code and model profile."""

from contextlib import redirect_stdout
import copy
import hashlib
import http.server
import io
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

import yaml

from agent_graph.constitution import DEFAULT_PATH
from agent_graph.contracts import Limits, ModelConfig
from agent_service.__main__ import doctor
from agent_service.qualification import check, loaded_fingerprint, loaded_profile
from agent_service.smoke import SmokeBench

ENDPOINT = "http://127.0.0.1:9/v1/chat/completions"
MODEL = dict(protocol="actions-v3", endpoint=ENDPOINT, allowed_endpoints=[ENDPOINT], model="OFFLINE-SCRIPT",
             configuration_id="script-v3", allow_source_transfer=True, max_prompt_bytes=60000,
             context_tokens=131072, run_token_cap=10_000_000, installation_token_cap=10_000_000)
RUN_ID = "amvp-2b-test-r1"
PHASES = ["transport", "development", "evaluation-1", "evaluation-2", "evaluation-3"]
GATES = ["G1_accepted_forbidden_actions", "G2_accepted_forged_or_unauthentic_refs", "G7_program_complete"]
METRICS = ["T1_transport_success_rate", "T4_static_claim_recall"]
# runner.provenance() inside the report job of the model workflow.
PROVENANCE = dict(runner="tools.autonomous_mvp.runner", repository="rengalaxies/agent",
                  workflow_ref="rengalaxies/agent/.github/workflows/autonomous-mvp-model.yml@refs/heads/main",
                  workflow_run_id="18000000001", workflow_run_attempt=1, source_sha="c" * 40)


def policy(**model):
    """The part of the core Policy check() reads, with the real ModelConfig validation."""
    return SimpleNamespace(model=ModelConfig(**{**MODEL, **model}), limits=Limits())


def report_document(*, verdict="QUALIFIED", protocol=None, endpoint=ENDPOINT, profile=None):
    """An amvp-report-2 document as scorer.report(..., manifest=, provenance=) writes it, all gates held."""
    entry = dict(verdict=verdict, gates={g: True for g in GATES},
                 thresholds={t: dict(value=1.0, rule=">= 0.9", passed=True) for t in METRICS},
                 expected_case_runs=156, executed=156,
                 phases={p: dict(status="COMPLETED", case_runs=3, reserved_open=0, source_sha="c" * 40,
                                 actions_run="18000000000", measurements=None) for p in PHASES},
                 profile=loaded_profile(policy()) if profile is None else profile)
    return dict(schema="amvp-report-2", run_id=RUN_ID, label="test", live_status="test",
                program=dict(id="2b-test", run_id=RUN_ID, revision=1, phases=PHASES, gates=GATES, metrics=METRICS),
                manifest_digest="b" * 64, provenance=dict(PROVENANCE),
                provider=dict(name="test provider", chat_endpoint=endpoint, credential_env="RUNNER_KEY"),
                protocol=loaded_fingerprint(None) if protocol is None else protocol,
                ignored_ledgers=[], models={MODEL["model"]: entry})


def save(directory: Path, report: dict) -> dict:
    path = directory / "report.json"
    path.write_bytes(json.dumps(report).encode())
    return dict(report_path=str(path), run_id=report.get("run_id"),
                report_sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def write_report(directory: Path, **fields) -> dict:
    return save(directory, report_document(**fields))


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

    def test_loaded_output_limit_other_than_the_qualified_one_keeps_the_model_off(self):
        bench = self.bench(qualification=write_report, policy_overrides={"model": {**MODEL, "max_output_tokens": 64}})
        self.assertEqual(bench.analyzer.model_status().reason_code, "qualification_profile_max_output_tokens_mismatch")
        self.jira(bench)
        self.assertEqual(self.model.calls, 0)
        code, message = self.doctor(bench)
        self.assertEqual(code, 1)
        self.assertIn("лимит токенов ответа в отчёте amvp-2b-test-r1 (1024)", message)


class ReportCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def reason(self, report, loaded=None):
        return check(save(self.dir, report), loaded or policy(), None).reason_code

    def entry(self, report):
        return report["models"][MODEL["model"]]


class ReproducedDefectsTest(ReportCase):
    """A qualifying report checked against a configuration other than the one it qualified (review of 0f0dc02)."""

    def test_lower_output_token_limit_is_rejected(self):
        self.assertEqual(self.reason(report_document(), policy(max_output_tokens=64)),
                         "qualification_profile_max_output_tokens_mismatch")

    def test_other_token_parameter_name_is_rejected(self):
        self.assertEqual(self.reason(report_document(), policy(token_parameter="max_completion_tokens")),
                         "qualification_profile_token_parameter_mismatch")

    def test_smaller_context_is_rejected(self):
        self.assertEqual(self.reason(report_document(), policy(context_tokens=65536)),
                         "qualification_profile_context_tokens_mismatch")

    def test_qualified_verdict_without_manifest_and_with_an_incomplete_program_is_rejected(self):
        report = report_document()
        report.pop("manifest_digest")
        self.entry(report)["gates"]["G7_program_complete"] = False
        self.assertEqual(self.reason(report), "qualification_manifest_missing")
        report["manifest_digest"] = "b" * 64
        self.assertEqual(self.reason(report), "qualification_program_incomplete")


class ArtifactTest(ReportCase):
    def test_matching_artifact_is_accepted(self):
        result = check(write_report(self.dir), policy(), None)
        self.assertEqual((result.ok, result.reason_code, result.run_id), (True, "qualified", RUN_ID))

    def test_installation_specific_fields_may_differ(self):
        installation = policy(api_key_env="INSTALLATION_MODEL_KEY", configuration_id="installation-7",
                              timeout_seconds=45, run_token_cap=5000, installation_token_cap=90_000)
        self.assertEqual(self.reason(report_document(), installation), "qualified")

    def test_report_of_the_previous_schema_is_rejected(self):
        report = report_document()
        report["schema"] = "amvp-report-1"
        self.assertEqual(self.reason(report), "qualification_report_mismatch")

    def test_report_without_provenance_or_from_outside_the_model_workflow_is_rejected(self):
        bad = {"absent": None, "local run": dict(PROVENANCE, workflow_run_id=None, workflow_run_attempt=None),
               "dirty checkout": dict(PROVENANCE, source_sha=None),
               "other runner": dict(PROVENANCE, runner="tools.handmade"),
               "other workflow": dict(PROVENANCE, workflow_ref="rengalaxies/agent/.github/workflows/x.yml@refs/heads/main")}
        for name, provenance in bad.items():
            with self.subTest(name):
                report = report_document()
                report["provenance"] = provenance
                self.assertEqual(self.reason(report), "qualification_provenance_missing")

    def test_malformed_manifest_digest_is_rejected(self):
        report = report_document()
        report["manifest_digest"] = "dry-run"
        self.assertEqual(self.reason(report), "qualification_manifest_missing")

    def test_qualified_verdict_with_a_failed_or_missing_gate_is_rejected(self):
        report = report_document()
        self.entry(report)["gates"]["G2_accepted_forged_or_unauthentic_refs"] = False
        self.assertEqual(self.reason(report), "qualification_gate_failed")
        del self.entry(report)["gates"]["G2_accepted_forged_or_unauthentic_refs"]
        self.assertEqual(self.reason(report), "qualification_gate_failed")

    def test_qualified_verdict_with_a_failed_metric_is_rejected(self):
        report = report_document()
        self.entry(report)["thresholds"]["T4_static_claim_recall"]["passed"] = False
        self.assertEqual(self.reason(report), "qualification_threshold_failed")

    def test_program_with_fewer_executed_case_runs_than_expected_is_rejected(self):
        report = report_document()
        self.entry(report)["executed"] = 155
        self.assertEqual(self.reason(report), "qualification_program_incomplete")

    def test_unfinished_phase_or_open_reservation_is_rejected(self):
        for change in (dict(status="STOPPED_phase_deadline"), dict(reserved_open=1)):
            with self.subTest(change):
                report = report_document()
                self.entry(report)["phases"]["evaluation-3"].update(change)
                self.assertEqual(self.reason(report), "qualification_phase_incomplete")
        report = report_document()
        del self.entry(report)["phases"]["development"]
        self.assertEqual(self.reason(report), "qualification_phase_incomplete")

    def test_each_essential_profile_parameter_is_compared(self):
        changes = dict(endpoint="http://127.0.0.1:10/v1/chat/completions", model="Qwen/Other",
                       protocol="evidence-refs-v2", token_parameter="max_completion_tokens", max_output_tokens=2048,
                       context_tokens=65536, max_prompt_bytes=50000, max_tool_lines=120, stream=True,
                       response_format=dict(type="json_object", name="graph_action", strict=False),
                       sampling=dict(temperature=0, top_p=0.9))
        for field, value in changes.items():
            with self.subTest(field):
                report = report_document()
                self.entry(report)["profile"][field] = value
                self.assertEqual(self.reason(report), f"qualification_profile_{field}_mismatch")

    def test_report_without_a_model_profile_is_rejected(self):
        report = report_document()
        self.entry(report)["profile"] = None  # evaluation case-runs disagreed or recorded none
        self.assertEqual(self.reason(report), "qualification_profile_missing")
        report = report_document()
        del self.entry(report)["profile"]["sampling"]
        self.assertEqual(self.reason(report), "qualification_profile_missing")


class ReportIntegrityTest(ReportCase):
    def test_report_edited_after_it_was_referenced_is_rejected(self):
        reference = write_report(self.dir)
        report = json.loads(Path(reference["report_path"]).read_text())
        report["label"] = "edited"
        Path(reference["report_path"]).write_text(json.dumps(report))
        self.assertEqual(check(reference, policy(), None).reason_code, "qualification_report_digest_mismatch")

    def test_report_without_a_protocol_fingerprint_cannot_qualify(self):
        report = report_document()
        report.pop("protocol")
        self.assertEqual(self.reason(report), "qualification_report_incomplete")

    def test_report_of_another_model_or_run_is_rejected(self):
        reference = write_report(self.dir)
        self.assertEqual(check(reference, policy(model="Qwen/Other"), None).reason_code, "model_not_in_qualification")
        self.assertEqual(check({**reference, "run_id": "amvp-2b-other"}, policy(), None).reason_code,
                         "qualification_report_mismatch")

    def test_report_from_another_provider_endpoint_is_rejected(self):
        self.assertEqual(self.reason(report_document(endpoint="https://other.example/v1/chat/completions")),
                         "qualification_provider_mismatch")

    def test_every_core_file_the_report_pinned_is_compared_but_not_the_2b_harness(self):
        protocol = loaded_fingerprint(None)
        protocol["code_sha256"]["tools/autonomous_mvp/protocol.py"] = "1" * 64  # not loaded by the service
        self.assertEqual(self.reason(report_document(protocol=copy.deepcopy(protocol))), "qualified")
        protocol["code_sha256"]["src/agent_graph/graph_query.py"] = "2" * 64  # loaded: must match
        self.assertEqual(self.reason(report_document(protocol=protocol)), "qualification_code_mismatch")

    def test_changed_action_schema_is_detected(self):
        protocol = loaded_fingerprint(None)
        protocol["schema_sha256"] = "0" * 64
        self.assertEqual(self.reason(report_document(protocol=protocol)), "qualification_schema_sha256_mismatch")


class ChatModelProfileTest(unittest.TestCase):
    def test_loaded_profile_is_what_chat_model_sends(self):
        """loaded_profile states the request fields ChatModel adds; the 2B harness records them from its request."""
        from agent_graph.actions import action_schema
        from agent_graph.inference import ChatModel
        from tools.autonomous_mvp.protocol import model_profile

        bodies = []

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                bodies.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
                body = json.dumps(dict(choices=[dict(message=dict(content="{}"), finish_reason="stop")],
                                       usage=dict(prompt_tokens=1, completion_tokens=1))).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        self.addCleanup(httpd.server_close)
        self.addCleanup(httpd.shutdown)
        url = f"http://127.0.0.1:{httpd.server_port}/v1/chat/completions"
        loaded = policy(endpoint=url, allowed_endpoints=[url], token_parameter="max_completion_tokens",
                        max_output_tokens=2048)
        ChatModel(loaded.model).complete_raw([dict(role="user", content="test")], action_schema())
        [body] = bodies
        self.assertEqual(model_profile(loaded, body), loaded_profile(loaded))


class RunnerAgreementTest(unittest.TestCase):
    """The 2B runner and scorer produce the artifact check() reads: a dry run through the live code path."""

    @classmethod
    def setUpClass(cls):
        from tools.autonomous_mvp import dryrun, program as program_mod
        from tools.autonomous_mvp.tests.helpers import MODEL as RUN_MODEL, ORACLE, SMALL, one_model_program

        # F09/F10 controls sleep to their deadlines; no threshold depends on them.
        cases = {k: c for k, c in SMALL.items() if c["family"] not in ("F09_step_limit", "F10_timeout")}
        cls.program, cls.model_id = one_model_program(), RUN_MODEL
        with tempfile.TemporaryDirectory() as work:
            cls.report, _, _ = dryrun.dry_run(cls.program, cases, ORACLE, model_id=RUN_MODEL, behaviour="follow",
                                              work=work, manifest=program_mod.manifest(), provenance=PROVENANCE)

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def installation(self, **overrides):
        """A service configuration written from the program's published values, with its own credentials."""
        p, m = self.program["parameters"], self.program["models"][0]
        endpoint = self.program["provider"]["chat_endpoint"]
        model = dict(protocol="actions-v3", endpoint=endpoint, allowed_endpoints=[endpoint], model=self.model_id,
                     configuration_id="installation-1", api_key_env="INSTALLATION_MODEL_KEY",
                     allow_source_transfer=True, route="corporate", token_parameter=p["token_parameter"],
                     max_output_tokens=m["max_completion_tokens"], context_tokens=p["context_tokens"],
                     max_prompt_bytes=p["max_prompt_bytes"], currency="RUB", micro_per_million_tokens=400_000_000,
                     installation_micro_cap=10**12, run_micro_cap=10**10)
        return SimpleNamespace(model=ModelConfig(**{**model, **overrides}), limits=Limits())

    def test_dry_run_artifact_is_accepted_for_the_configuration_it_ran(self):
        self.assertEqual(self.report["models"][self.model_id]["verdict"], "QUALIFIED")
        reference = save(self.dir, self.report)
        result = check(reference, self.installation(), None)
        self.assertEqual((result.reason_code, result.ok), ("qualified", True), result.message)
        self.assertEqual(check(reference, self.installation(max_output_tokens=2048), None).reason_code,
                         "qualification_profile_max_output_tokens_mismatch")

    def test_artifact_scored_outside_github_actions_is_refused(self):
        from tools.autonomous_mvp import runner

        report = dict(self.report, provenance=runner.provenance(env={}))
        self.assertEqual(check(save(self.dir, report), self.installation(), None).reason_code,
                         "qualification_provenance_missing")


if __name__ == "__main__":
    unittest.main()
