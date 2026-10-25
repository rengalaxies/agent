import copy
import hashlib
import unittest

from tools.autonomous_mvp import scorer
from tools.autonomous_mvp.tests.helpers import CASES, ORACLE, PROGRAM

EVAL = sorted(k for k, c in CASES.items() if c["split"] == "evaluation")
# constitutions/agent-service-v1.yaml outcomes
OUTCOMES = dict(supported_dependency=("USEFUL", "impact_found_within_profile"),
                hypotheses_only=("PARTIAL", "hypotheses_only"), abstained=("ABSTAINED", "insufficient_evidence"),
                step_limit=("PARTIAL", "model_step_limit"), deadline=("PARTIAL", "deadline_reached"))
TERMINAL = dict(step_limit="STEP_LIMIT", deadline="DEADLINE", abstained="ABSTAINED")


def admitted(c, confidence=None, refs=("issued",), provenance="AUTHENTIC"):
    """A claim record as case_result builds it for an admitted fact or candidate."""
    claim = {k: c[k] for k in scorer.FIELDS}
    level = confidence or c["max_confidence"]
    fact = level == "CONFIRMED_WITHIN_PROFILE"
    return dict(claim=claim, kind="fact" if fact else "hypothesis", origin="code" if fact else "model_hypothesis",
                ref_digests=[hashlib.sha256(r.encode()).hexdigest() for r in refs], provenance=provenance,
                provenance_reason=None, sufficiency="SUPPORTED_WITHIN_PROFILE" if fact else "NOT_ASSESSED",
                unknowns=[] if fact else ["helper_semantics_unknown"], admitted=True, confidence=level)


def ideal_result(case_id):
    """What a perfect model would leave in the ledger through the executor."""
    o, c = ORACLE[case_id], CASES[case_id]
    outcome = o["acceptable_outcomes"][0]
    status, reason = OUTCOMES[outcome]
    claims = [] if outcome in ("deadline", "abstained") else [admitted(x) for x in o["required_claims"]]
    steps = [dict(step=0, action="read_source", valid=True, layer=None, reason_code=None, errors=[])]
    return dict(case_id=case_id, repeat=1, family=c["family"], split=c["split"],
                terminal=TERMINAL.get(outcome, "FINISHED"), reason_code=reason, steps=steps, claims=claims,
                final=dict(status=status, reason_code=reason, outcome=outcome, finish_reason="done"),
                graph=dict(calls={"graph_impact": 1} if o["graph_case"] else {}, revoked_leaks=0,
                           owners=dict(o["owners"]), ids_seen=0),
                invalid_actions=0, requests=1, wall_seconds=12.0, max_model_steps=c["limits"]["max_model_steps"],
                protocol_id="actions-v3")


def ledger(phase, results, model="openai/gpt-oss-120b"):
    rows = [dict(key=f"{r['case_id']}#1", case_id=r["case_id"], repeat=1, status="FINISHED", settled_micro=500_000,
                 attempts=[dict(ok=True, code="ok", http_status=200, latency_seconds=3.0, step=0, late=False,
                                usage=dict(prompt_tokens=1000, completion_tokens=100))], result=r)
            for r in results]
    return dict(run_id=PROGRAM["run_id"], phase=phase, model=model, status="COMPLETED", case_runs=rows)


def evaluate(mutate=None):
    states = []
    for phase in scorer.EVALUATION_PHASES:
        results = [ideal_result(k) for k in EVAL]
        if mutate:
            mutate(phase, results)
        states.append(ledger(phase, results))
    return scorer.verdict(PROGRAM, CASES, states, ORACLE)


def find(results, family):
    return next(r for r in results if r["family"] == family)


class Verdicts(unittest.TestCase):
    def test_ideal_full_program_qualifies(self):
        v = evaluate()
        self.assertEqual(v["verdict"], "QUALIFIED", v["thresholds"])
        self.assertEqual(v["executed"], 156)
        self.assertEqual(v["measurements"]["semantics"]["static_recall"]["denominator"],
                         3 * sum(1 for k in EVAL for c in ORACLE[k]["required_claims"] if c["max_confidence"] != "CANDIDATE"))

    def test_admitted_decoy_fact_disables_the_model(self):
        def decoy(phase, results):
            r = find(results, "F02_same_name_operation")
            r["claims"].append(admitted(ORACLE[r["case_id"]]["forbidden_claims"][0]))
        v = evaluate(decoy)
        self.assertFalse(v["gates"]["G3_accepted_forbidden_or_unverifiable_facts"])
        self.assertEqual(v["verdict"], "DISABLED")

    def test_admitted_decoy_candidate_keeps_gates_but_fails_the_candidate_threshold(self):
        def decoy(phase, results):
            for r in results:
                if r["family"] == "F02_same_name_operation":
                    r["claims"].append(admitted(ORACLE[r["case_id"]]["forbidden_claims"][0], confidence="CANDIDATE"))
        v = evaluate(decoy)
        self.assertTrue(all(v["gates"].values()))
        self.assertEqual(v["measurements"]["semantics"]["accepted_false_candidate_rate"]["numerator"], 9)
        self.assertFalse(v["thresholds"]["T8_accepted_false_candidate_rate"]["passed"])  # 9/63 > 0.05
        self.assertEqual(v["verdict"], "EXPERIMENTAL")

    def test_rejected_forged_refs_count_as_attempts_not_as_accepted(self):
        def forged(phase, results):
            r = find(results, "F06_forged_refs")
            c = dict(admitted(ORACLE[r["case_id"]]["required_claims"][0], refs=ORACLE[r["case_id"]]["forged_refs"],
                              provenance="REJECTED"), admitted=False, confidence="NOT_ADMITTED")
            r["claims"].append(c)
        v = evaluate(forged)
        self.assertEqual(v["measurements"]["evidence"]["forged_attempts"], 3)
        self.assertTrue(v["gates"]["G2_accepted_forged_or_unauthentic_refs"])

    def test_admitted_forged_ref_breaks_the_authenticity_gate(self):
        def forged(phase, results):
            r = find(results, "F06_forged_refs")
            r["claims"] = [admitted(ORACLE[r["case_id"]]["required_claims"][0], refs=ORACLE[r["case_id"]]["forged_refs"])]
        self.assertFalse(evaluate(forged)["gates"]["G2_accepted_forged_or_unauthentic_refs"])

    def test_beyond_static_candidate_promoted_to_confirmed_breaks_the_profile_gate(self):
        def promote(phase, results):
            r = find(results, "F04_unsupported_wrapper")
            r["claims"] = [admitted(ORACLE[r["case_id"]]["required_claims"][0], confidence="CONFIRMED_WITHIN_PROFILE")]
        self.assertFalse(evaluate(promote)["gates"]["G4_beyond_profile_admitted_as_confirmed"])

    def test_admitted_hypothesis_marked_sufficient_breaks_the_contract_gate(self):
        def sufficient(phase, results):
            find(results, "F11_config_context")["claims"][0]["sufficiency"] = "SUPPORTED_WITHIN_PROFILE"
        v = evaluate(sufficient)
        self.assertEqual(v["measurements"]["evidence"]["contract_violations"], 3)
        self.assertFalse(v["gates"]["G2_accepted_forged_or_unauthentic_refs"])

    def test_other_protocol_is_never_qualified(self):
        def other(phase, results):
            for r in results:
                r["protocol_id"] = "evidence-refs-v2"
        self.assertFalse(evaluate(other)["gates"]["G8_protocol_is_the_2a_executor"])

    def test_missing_evaluation_phase_is_incomplete_not_a_smaller_denominator(self):
        states = [ledger(p, [ideal_result(k) for k in EVAL]) for p in scorer.EVALUATION_PHASES[:2]]
        v = scorer.verdict(PROGRAM, CASES, states, ORACLE)
        self.assertFalse(v["gates"]["G7_program_complete"])
        self.assertEqual(v["verdict"], "DISABLED")

    def test_no_evaluation_at_all_is_disabled(self):
        self.assertEqual(scorer.verdict(PROGRAM, CASES, [], ORACLE)["verdict"], "DISABLED")

    def test_wrong_outcome_fails_the_case_even_with_the_right_claim(self):
        def wrong(phase, results):
            r = find(results, "F04_unsupported_wrapper")
            r["final"] = dict(r["final"], status="USEFUL", reason_code="impact_found_within_profile",
                              outcome="supported_dependency")
        v = evaluate(wrong)
        self.assertEqual(v["measurements"]["abstention"]["outcome_accuracy"]["numerator"], 153)
        self.assertEqual(v["measurements"]["semantics"]["case_pass"]["numerator"], 153)

    def test_reason_code_from_another_status_fails_the_case(self):
        def mismatch(phase, results):
            r = find(results, "F01_true_consumer")
            r["final"] = dict(r["final"], reason_code="coverage_gaps")
        self.assertEqual(evaluate(mismatch)["measurements"]["abstention"]["outcome_accuracy"]["numerator"], 153)

    def test_incomplete_hypothesis_is_neither_a_hit_nor_a_false_claim(self):
        def vague(phase, results):
            r = find(results, "F02_same_name_operation")
            c = admitted(ORACLE[r["case_id"]]["forbidden_claims"][0], confidence="CANDIDATE")
            c["claim"] = dict(c["claim"], provider_service=None, method=None, path_template=None)
            r["claims"].append(c)
        v = evaluate(vague)
        self.assertEqual(v["measurements"]["semantics"]["accepted_false_candidates"], 0)
        self.assertEqual(v["measurements"]["semantics"]["accepted_extra_claims"], 0)

    def test_transport_failure_stays_in_denominators(self):
        def fail(phase, results):
            find(results, "F01_true_consumer").update(terminal="TRANSPORT_FAILED", claims=[], steps=[], final=None)
        v = evaluate(fail)
        self.assertEqual(v["measurements"]["loop_completion"]["denominator"],
                         3 * sum(1 for k in EVAL if CASES[k]["family"] not in scorer.HARNESS_FAMILIES))
        self.assertEqual(v["measurements"]["semantics"]["case_pass"]["numerator"], 153)

    def test_wrong_abstention_on_an_answerable_case_is_counted(self):
        def abstain(phase, results):
            r = find(results, "F01_true_consumer")
            r.update(terminal="ABSTAINED", claims=[], final=dict(status="ABSTAINED", reason_code="insufficient_evidence",
                                                                  outcome="abstained", finish_reason="insufficient_evidence"))
        v = evaluate(abstain)
        self.assertEqual(v["measurements"]["abstention"]["wrong_abstention"]["numerator"], 3)

    def test_deliberate_timeouts_of_f10_do_not_count_against_transport(self):
        states = [ledger(p, [ideal_result(k) for k in EVAL]) for p in scorer.EVALUATION_PHASES]
        for s in states:
            for row in s["case_runs"]:
                if row["result"]["family"] == "F10_timeout":
                    row["attempts"] = [dict(row["attempts"][0], ok=False, code="timeout", usage=None, late=True)]
        v = scorer.verdict(PROGRAM, CASES, states, ORACLE)
        self.assertEqual(v["measurements"]["transport"]["value"], 1.0)
        self.assertEqual(v["measurements"]["transport"]["timeout_control_attempts"], 6)

    def test_admitted_claim_citing_a_graph_id_breaks_the_authenticity_gate(self):
        def graph_ref(phase, results):
            r = find(results, "F16_graph_ids_as_evidence")
            r["claims"][0]["graph_refs"] = 1
        v = evaluate(graph_ref)
        self.assertEqual(v["measurements"]["evidence"]["graph_ref_admitted"], 3)
        self.assertFalse(v["gates"]["G2_accepted_forged_or_unauthentic_refs"])

    def test_rejected_graph_id_citation_is_only_an_attempt(self):
        def graph_ref(phase, results):
            r = find(results, "F16_graph_ids_as_evidence")
            r["claims"].append(dict(r["claims"][0], graph_refs=2, admitted=False, provenance="REJECTED",
                                    confidence="NOT_ADMITTED"))
        v = evaluate(graph_ref)
        self.assertEqual(v["measurements"]["evidence"]["graph_ref_attempts"], 3)
        self.assertTrue(all(v["gates"].values()))

    def test_revoked_service_in_a_graph_result_breaks_the_scope_gate(self):
        def leak(phase, results):
            find(results, "F17_graph_revoked_scope")["graph"]["revoked_leaks"] = 1
        v = evaluate(leak)
        self.assertFalse(v["gates"]["G9_revoked_scope_leaks"])
        self.assertEqual(v["verdict"], "DISABLED")

    def test_unasked_or_wrong_owner_counts_against_owner_status(self):
        def owners(phase, results):
            for r in results:
                if r["family"] == "F18_graph_owner":
                    r["graph"]["owners"] = {}  # the model never asked the graph
        v = evaluate(owners)
        rate = v["measurements"]["graph"]["owner_status"]
        self.assertEqual(rate["denominator"] - rate["numerator"], 27)  # 3 owners x 3 cases x 3 phases
        self.assertFalse(v["thresholds"]["T14_owner_status_rate"]["passed"])

    def test_wilson_interval_brackets_the_point_estimate(self):
        r = scorer.rate(9, 10)
        self.assertLessEqual(r["wilson95"][0], r["value"])
        self.assertGreaterEqual(r["wilson95"][1], r["value"])
        self.assertIsNone(scorer.rate(0, 0)["value"])

    def test_report_has_a_verdict_per_model_and_unrun_models_are_disabled(self):
        states = [ledger(p, [ideal_result(k) for k in EVAL]) for p in scorer.EVALUATION_PHASES]
        rep = scorer.report(PROGRAM, CASES, ORACLE, copy.deepcopy(states))
        text = scorer.markdown(rep)
        for m in PROGRAM["models"]:
            self.assertIn("## " + m["id"], text)
        self.assertEqual(rep["models"]["openai/gpt-oss-120b"]["verdict"], "QUALIFIED")
        self.assertEqual(rep["models"]["Qwen/Qwen3-Coder-Next"]["verdict"], "DISABLED")


class ReportBinding(unittest.TestCase):
    """The service enables a model only if the report matches the configuration it loads."""

    def test_report_carries_the_manifest_identity_and_drops_ledgers_of_another_manifest(self):
        manifest = dict(manifest_digest="d" * 64, protocol=dict(protocol="actions-v3", constitution_version="v"))
        current = [dict(ledger(p, [ideal_result(k) for k in EVAL]), manifest_digest="d" * 64)
                   for p in scorer.EVALUATION_PHASES]
        stale = dict(ledger("evaluation-1", [ideal_result(k) for k in EVAL], model="Qwen/Qwen3-Coder-Next"),
                     manifest_digest="e" * 64)
        rep = scorer.report(PROGRAM, CASES, ORACLE, current + [stale], manifest=manifest)
        self.assertEqual((rep["manifest_digest"], rep["protocol"]), ("d" * 64, manifest["protocol"]))
        self.assertEqual(rep["provider"]["chat_endpoint"], PROGRAM["provider"]["chat_endpoint"])
        self.assertEqual(rep["models"]["openai/gpt-oss-120b"]["verdict"], "QUALIFIED")
        self.assertEqual(rep["ignored_ledgers"], ["Qwen/Qwen3-Coder-Next:evaluation-1"])
        self.assertEqual(rep["models"]["Qwen/Qwen3-Coder-Next"]["verdict"], "DISABLED")

    def test_report_states_the_profile_evaluation_case_runs_used_and_none_when_they_differ(self):
        profile = dict(model="openai/gpt-oss-120b", token_parameter="max_completion_tokens", max_output_tokens=4096)
        states = [ledger(p, [dict(ideal_result(k), model_profile=profile) for k in EVAL])
                  for p in scorer.EVALUATION_PHASES]
        rep = scorer.report(PROGRAM, CASES, ORACLE, copy.deepcopy(states), program_id="2b-r1")
        self.assertEqual((rep["schema"], rep["program"]["id"]), ("amvp-report-2", "2b-r1"))
        self.assertEqual(rep["program"]["phases"], list(PROGRAM["phases"]))
        self.assertIn("G7_program_complete", rep["program"]["gates"])
        self.assertEqual(rep["models"]["openai/gpt-oss-120b"]["profile"], profile)
        # One case-run of the last phase went out with another output limit: no single profile was qualified.
        states[2]["case_runs"][0]["result"]["model_profile"] = dict(profile, max_output_tokens=64)
        rep = scorer.report(PROGRAM, CASES, ORACLE, copy.deepcopy(states), program_id="2b-r1")
        self.assertIsNone(rep["models"]["openai/gpt-oss-120b"]["profile"])


class HypothesisContract(unittest.TestCase):
    def test_candidate_maps_to_a_valid_hypothesis_evidence_and_a_sufficient_one_is_refused(self):
        from pydantic import ValidationError
        from tools.autonomous_mvp.protocol import hypothesis_evidence
        record = admitted(ORACLE["E04a"]["required_claims"][0])
        doc = hypothesis_evidence(record, model_configuration_id="amvp-2b:openai/gpt-oss-120b",
                                  visibility=["routing"], checked_at="2026-10-24T12:00:00Z")
        self.assertEqual((doc["origin"], doc["sufficiency"]), ("model_hypothesis", "NOT_ASSESSED"))
        with self.assertRaises(ValidationError):
            hypothesis_evidence(dict(record, sufficiency="SUPPORTED_WITHIN_PROFILE"),
                                model_configuration_id="m", visibility=["routing"], checked_at="2026-10-24T12:00:00Z")


if __name__ == "__main__":
    unittest.main()
