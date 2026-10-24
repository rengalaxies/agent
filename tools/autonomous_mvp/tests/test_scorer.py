import copy
import hashlib
import unittest

from tools.autonomous_mvp import program as program_mod, scorer

BASE, PROGRAM, CASES = program_mod.load()
ORACLE = program_mod.load_oracle(BASE)
EVAL = sorted(k for k, c in CASES.items() if c["split"] == "evaluation")


def admitted(c, confidence=None, refs=("issued",), provenance="AUTHENTIC_AUTHORIZED_CURRENT"):
    claim = {k: c[k] for k in scorer.FIELDS}
    return dict(claim=claim, kind="dependency", ref_digests=[hashlib.sha256(r.encode()).hexdigest() for r in refs],
                provenance=provenance, provenance_reason=None, sufficiency="SUPPORTED_WITHIN_PROFILE", admitted=True,
                confidence=confidence or c["max_confidence"])


def ideal_result(case_id):
    """What a perfect model on a full protocol would leave in the ledger."""
    o, c = ORACLE[case_id], CASES[case_id]
    final = dict(status=o["acceptable_statuses"][0], unknowns=list(o["required_unknowns"]), impact=dict(o["impact"]))
    terminal = "STEP_LIMIT" if o["harness_stop"] == "STEP_LIMIT" else "FINISHED"
    steps = [dict(step=0, action="read_source", valid=True, layer=None, reason_code=None, field_path=None, claims=[])]
    return dict(case_id=case_id, repeat=1, family=c["family"], split=c["split"], terminal=terminal, reason_code=None,
                steps=steps, claims=[admitted(x) for x in o["required_claims"]], final=final, invalid_actions=0,
                requests=1, wall_seconds=12.0, max_model_steps=c["limits"]["max_model_steps"],
                protocol_id="agent-service-v1")


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
        self.assertEqual(v["executed"], 120)
        self.assertEqual(v["measurements"]["semantics"]["static_recall"]["denominator"],
                         3 * sum(1 for k in EVAL for c in ORACLE[k]["required_claims"] if c["max_confidence"] != "CANDIDATE"))

    def test_admitted_decoy_claim_disables_the_model(self):
        def decoy(phase, results):
            r = find(results, "F02_same_name_operation")
            r["claims"].append(admitted(ORACLE[r["case_id"]]["forbidden_claims"][0]))
        v = evaluate(decoy)
        self.assertFalse(v["gates"]["G3_accepted_forbidden_or_unverifiable_claims"])
        self.assertEqual(v["verdict"], "DISABLED")

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
        v = evaluate(forged)
        self.assertFalse(v["gates"]["G2_accepted_forged_or_unauthentic_refs"])

    def test_beyond_static_candidate_promoted_to_confirmed_breaks_the_profile_gate(self):
        def promote(phase, results):
            r = find(results, "F04_unsupported_wrapper")
            r["claims"] = [admitted(ORACLE[r["case_id"]]["required_claims"][0], confidence="CONFIRMED_WITHIN_PROFILE")]
        v = evaluate(promote)
        self.assertFalse(v["gates"]["G4_beyond_profile_admitted_as_confirmed"])

    def test_interim_protocol_can_never_qualify(self):
        def interim(phase, results):
            for r in results:
                r["protocol_id"] = "evidence-refs-v2-interim"
        self.assertEqual(evaluate(interim)["verdict"], "DISABLED")

    def test_missing_evaluation_phase_is_incomplete_not_a_smaller_denominator(self):
        states = [ledger(p, [ideal_result(k) for k in EVAL]) for p in scorer.EVALUATION_PHASES[:2]]
        v = scorer.verdict(PROGRAM, CASES, states, ORACLE)
        self.assertFalse(v["gates"]["G7_program_complete"])
        self.assertEqual(v["verdict"], "DISABLED")

    def test_no_evaluation_at_all_is_disabled(self):
        self.assertEqual(scorer.verdict(PROGRAM, CASES, [], ORACLE)["verdict"], "DISABLED")

    def test_unknown_impact_answered_as_at_risk_fails_acknowledgement_but_not_gates(self):
        def overclaim(phase, results):
            for r in results:
                if r["family"] == "F08_justified_unknown":
                    r["final"]["impact"] = {k: "AT_RISK" for k in r["final"]["impact"]}
        v = evaluate(overclaim)
        self.assertTrue(all(v["gates"].values()))
        ack = v["measurements"]["abstention"]["unknown_acknowledgement"]
        self.assertEqual(ack["denominator"] - ack["numerator"], 9)
        self.assertEqual(v["measurements"]["families"]["F08_justified_unknown"]["numerator"], 0)

    def test_transport_failure_stays_in_denominators(self):
        def fail(phase, results):
            r = find(results, "F01_true_consumer")
            r.update(terminal="TRANSPORT_FAILED", claims=[], steps=[], final=None)
        v = evaluate(fail)
        self.assertEqual(v["measurements"]["loop_completion"]["denominator"],
                         3 * sum(1 for k in EVAL if CASES[k]["family"] not in scorer.HARNESS_FAMILIES))
        self.assertEqual(v["measurements"]["semantics"]["case_pass"]["numerator"], 117)

    def test_wrong_abstention_on_an_answerable_case_is_counted(self):
        def abstain(phase, results):
            r = find(results, "F01_true_consumer")
            r.update(terminal="ABSTAINED", claims=[], final=dict(r["final"], status="ABSTAINED"))
        v = evaluate(abstain)
        self.assertEqual(v["measurements"]["abstention"]["wrong_abstention"]["numerator"], 3)
        self.assertEqual(v["thresholds"]["T9_wrong_abstention_rate"]["passed"], True)  # 3/105 is within 0.15

    def test_wilson_interval_brackets_the_point_estimate(self):
        r = scorer.rate(9, 10)
        self.assertLessEqual(r["wilson95"][0], r["value"])
        self.assertGreaterEqual(r["wilson95"][1], r["value"])
        self.assertIsNone(scorer.rate(0, 0)["value"])

    def test_report_markdown_has_one_section_per_model(self):
        states = [ledger(p, [ideal_result(k) for k in EVAL]) for p in scorer.EVALUATION_PHASES]
        rep = scorer.report(PROGRAM, CASES, ORACLE, copy.deepcopy(states))
        text = scorer.markdown(rep)
        for m in PROGRAM["models"]:
            self.assertIn("## " + m["id"], text)
        self.assertEqual(rep["models"]["openai/gpt-oss-120b"]["verdict"], "QUALIFIED")
        self.assertEqual(rep["models"]["Qwen/Qwen3-Coder-Next"]["verdict"], "DISABLED")


if __name__ == "__main__":
    unittest.main()
