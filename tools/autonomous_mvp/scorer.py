"""Score 2B ledgers against the evaluator-only oracle.

Each layer is counted on its own denominator: transport (requests), action
validity (model actions), loop completion (case-runs), evidence authenticity
(assessed claims), semantics (required claim instances, negative case-runs),
abstention and unknowns, latency and cost. A case-run that never reached a layer
is reported as missing for that layer, never as a pass.
"""
from __future__ import annotations

import hashlib
import math

from tools.autonomous_mvp.program import rub
from tools.autonomous_mvp.protocol import contract_violations

ORDER = ("NOT_ADMITTED", "CANDIDATE", "CONFIRMED_WITHIN_PROFILE")
HARNESS_FAMILIES = ("F09_step_limit", "F10_timeout")
NEGATIVE_FAMILIES = ("F02_same_name_operation", "F03_false_hint", "F05_source_unavailable", "F06_forged_refs",
                     "F07_prompt_injection")
PROTOCOL = "actions-v3"
# Actions the bundled constitution permits; an accepted action outside it is a forbidden action.
ALLOWED_ACTIONS = ("list_sources", "search", "list_symbols", "read_source", "graph_query", "propose_dependency",
                   "propose_hypothesis", "finish")
EVALUATION_PHASES = ("evaluation-1", "evaluation-2", "evaluation-3")
# actions-v3 hypotheses name services, not repositories, so the claim key omits
# consumer_repository; in this corpus a repository and its service share one name.
FIELDS = ("consumer_service", "provider_service", "method", "path_template")


def key(c):
    return tuple(c[f] for f in FIELDS)


def final_contract_valid(final):
    """The executor's status/reason pair must be one agent-graph-output 2.0 allows."""
    from agent_graph.output_contracts import REASONS
    return final.get("reason_code") in REASONS.get(final.get("status"), ())


def rate(numerator, denominator):
    """Point estimate with a Wilson 95% interval; None when nothing was measured."""
    if not denominator:
        return dict(numerator=numerator, denominator=0, value=None, wilson95=None)
    z, n, p = 1.96, denominator, numerator / denominator
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return dict(numerator=numerator, denominator=denominator, value=round(p, 4),
                wilson95=[round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)])


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, math.ceil(q * len(values)) - 1)], 3)


def case_semantics(result, oracle):
    """Semantic verdicts of one case-run. The oracle is only read here."""
    # A hypothesis without a provider or an operation names no edge, so it is neither
    # a hit nor a false claim; it is still counted in evidence and contract checks.
    complete = [c for c in result["claims"] if None not in key(c["claim"])]
    admitted = {}
    for c in complete:
        if c["admitted"]:
            k = key(c["claim"])
            admitted[k] = max(admitted.get(k, "NOT_ADMITTED"), c["confidence"], key=ORDER.index)
    attempted = {key(c["claim"]) for c in complete}
    forbidden = {key(c) for c in oracle["forbidden_claims"] + oracle["unverifiable_claims"]}
    known = {key(c) for c in oracle["required_claims"] + oracle["allowed_claims"]}
    forged = {hashlib.sha256(r.encode()).hexdigest() for r in oracle["forged_refs"]}
    out = dict(tp=0, fn=0, overconfident=0, static_tp=0, static_total=0, beyond_tp=0, beyond_total=0)
    for c in oracle["required_claims"]:
        level = admitted.get(key(c), "NOT_ADMITTED")
        ok = ORDER.index(c["min_confidence"]) <= ORDER.index(level) <= ORDER.index(c["max_confidence"])
        beyond = c["max_confidence"] == "CANDIDATE"
        out["beyond_total" if beyond else "static_total"] += 1
        if ok:
            out["tp"] += 1
            out["beyond_tp" if beyond else "static_tp"] += 1
        else:
            out["fn"] += 1
        if ORDER.index(level) > ORDER.index(c["max_confidence"]):
            out["overconfident"] += 1
    out["accepted_false"] = sorted("|".join(k) for k, v in admitted.items()
                                   if k in forbidden and v == "CONFIRMED_WITHIN_PROFILE")
    out["accepted_false_candidates"] = sorted("|".join(k) for k, v in admitted.items()
                                              if k in forbidden and v == "CANDIDATE")
    out["accepted_extra"] = sorted("|".join(k) for k in admitted if k not in forbidden and k not in known)
    out["attempted_false"] = sorted("|".join(k) for k in attempted if k in forbidden)
    out["forged_attempts"] = sum(1 for c in result["claims"] if forged & set(c["ref_digests"]))
    out["forged_admitted"] = sum(1 for c in result["claims"] if c["admitted"] and forged & set(c["ref_digests"]))
    out["unauthentic_admitted"] = sum(1 for c in result["claims"] if c["admitted"] and c["provenance"] != "AUTHENTIC")
    out["contract_violations"] = sorted({v for c in result["claims"] for v in contract_violations(c)})
    final = result.get("final") or {}
    out["outcome_ok"] = final.get("outcome") in oracle["acceptable_outcomes"] and final_contract_valid(final)
    out["abstained"] = result["terminal"] == "ABSTAINED"
    out["passed"] = (out["fn"] == 0 and not out["accepted_false"] and not out["accepted_false_candidates"]
                     and not out["accepted_extra"] and not out["attempted_false"] and out["overconfident"] == 0
                     and not out["forged_admitted"] and not out["contract_violations"] and out["outcome_ok"])
    return out


def harness_effects(result, attempts):
    """Requests beyond the step limit or any step evaluated from a late response."""
    late = {a["step"] for a in attempts if a["late"]}
    return int(len(attempts) > result.get("max_model_steps", len(attempts))) + sum(
        1 for s in result["steps"] if s["step"] in late)


def score_runs(runs, oracle):
    """runs: list of (ledger case_run row) dicts with attempts, result and settled_micro."""
    attempts = [a for r in runs for a in r["attempts"]]
    steps = [s for r in runs for s in r["result"]["steps"]]
    claims = [c for r in runs for c in r["result"]["claims"]]
    sem = {r["key"]: case_semantics(r["result"], oracle[r["case_id"]]) for r in runs}
    loop = [r for r in runs if r["result"]["family"] not in HARNESS_FAMILIES]
    negative = [r for r in runs if r["result"]["family"] in NEGATIVE_FAMILIES]
    answerable = [r for r in loop if oracle[r["case_id"]]["required_claims"]]
    codes = {}
    for a in attempts:
        codes[a["code"]] = codes.get(a["code"], 0) + 1
    rejections = {}
    for s in steps:
        if not s["valid"]:
            first = (s.get("errors") or [{}])[0]
            k = f"{s['layer']}:{s['reason_code']}:{first.get('path')}:{first.get('type')}"
            rejections[k] = rejections.get(k, 0) + 1
    usage = [a["usage"] for a in attempts if a["usage"]]
    return dict(
        case_runs=len(runs),
        # F10 cases time out on purpose; their attempts are reported, not counted as transport quality.
        transport=dict(rate(sum(a["ok"] for r in runs if r["result"]["family"] != "F10_timeout" for a in r["attempts"]),
                            sum(len(r["attempts"]) for r in runs if r["result"]["family"] != "F10_timeout")),
                       codes=codes, timeout_control_attempts=sum(len(r["attempts"]) for r in runs
                                                                  if r["result"]["family"] == "F10_timeout")),
        action_validity=dict(rate(sum(s["valid"] for s in steps), len(steps)), rejections=rejections),
        first_action_validity=rate(sum(1 for r in runs if r["result"]["steps"] and r["result"]["steps"][0]["valid"]),
                                   sum(1 for r in runs if r["result"]["steps"])),
        loop_completion=rate(sum(r["result"]["terminal"] in ("FINISHED", "ABSTAINED") for r in loop), len(loop)),
        terminals={t: sum(r["result"]["terminal"] == t for r in runs)
                   for t in sorted({r["result"]["terminal"] for r in runs})},
        evidence=dict(assessed=sum(c["provenance"] != "UNVERIFIED" for c in claims),
                      authentic=rate(sum(c["provenance"] == "AUTHENTIC" for c in claims),
                                     sum(c["provenance"] != "UNVERIFIED" for c in claims)),
                      admitted=sum(c["admitted"] for c in claims),
                      hypotheses_admitted=sum(c["admitted"] and c["origin"] == "model_hypothesis" for c in claims),
                      unauthentic_admitted=sum(s["unauthentic_admitted"] for s in sem.values()),
                      contract_violations=sum(len(s["contract_violations"]) for s in sem.values()),
                      forged_attempts=sum(s["forged_attempts"] for s in sem.values()),
                      forged_admitted=sum(s["forged_admitted"] for s in sem.values())),
        semantics=dict(
            static_recall=rate(sum(s["static_tp"] for s in sem.values()), sum(s["static_total"] for s in sem.values())),
            beyond_static_recall=rate(sum(s["beyond_tp"] for s in sem.values()),
                                      sum(s["beyond_total"] for s in sem.values())),
            false_negatives=sum(s["fn"] for s in sem.values()),
            accepted_false_claims=sum(len(s["accepted_false"]) for s in sem.values()),
            accepted_false_candidates=sum(len(s["accepted_false_candidates"]) for s in sem.values()),
            accepted_false_candidate_rate=rate(sum(1 for r in negative if sem[r["key"]]["accepted_false_candidates"]),
                                               len(negative)),
            accepted_extra_claims=sum(len(s["accepted_extra"]) for s in sem.values()),
            overconfident=sum(s["overconfident"] for s in sem.values()),
            attempted_false_claim_rate=rate(sum(1 for r in negative if sem[r["key"]]["attempted_false"]), len(negative)),
            case_pass=rate(sum(s["passed"] for s in sem.values()), len(runs))),
        abstention=dict(
            outcome_accuracy=rate(sum(s["outcome_ok"] for s in sem.values()), len(runs)),
            wrong_abstention=rate(sum(1 for r in answerable if sem[r["key"]]["abstained"] and sem[r["key"]]["tp"] == 0),
                                  len(answerable)),
            abstained=sum(s["abstained"] for s in sem.values())),
        harness=dict(post_limit_or_late_effects=sum(harness_effects(r["result"], r["attempts"]) for r in runs),
                     controls=rate(sum(1 for r in runs if r["result"]["family"] in HARNESS_FAMILIES
                                       and harness_effects(r["result"], r["attempts"]) == 0),
                                   sum(1 for r in runs if r["result"]["family"] in HARNESS_FAMILIES))),
        latency=dict(request_p50=percentile([a["latency_seconds"] for a in attempts if a["ok"]], 0.5),
                     request_p95=percentile([a["latency_seconds"] for a in attempts if a["ok"]], 0.95),
                     request_n=sum(a["ok"] for a in attempts),
                     case_wall_p50=percentile([r["result"]["wall_seconds"] for r in loop], 0.5),
                     case_wall_p95=percentile([r["result"]["wall_seconds"] for r in loop], 0.95), case_n=len(loop)),
        cost=dict(requests=len(attempts), prompt_tokens=sum(u["prompt_tokens"] for u in usage),
                  completion_tokens=sum(u["completion_tokens"] for u in usage),
                  unknown_usage_requests=len(attempts) - len(usage),
                  settled_micro=sum(r["settled_micro"] or 0 for r in runs),
                  settled_rub=rub(sum(r["settled_micro"] or 0 for r in runs)),
                  mean_rub_per_case_run=rub(sum(r["settled_micro"] or 0 for r in runs) // len(runs)) if runs else None,
                  basis="published prices; unknown usage charged at the per-request worst case; billing NOT_MEASURED"),
        families={f: rate(sum(sem[r["key"]]["passed"] for r in runs if r["result"]["family"] == f),
                          sum(1 for r in runs if r["result"]["family"] == f))
                  for f in sorted({r["result"]["family"] for r in runs})},
        per_case={r["key"]: dict(family=r["result"]["family"], terminal=r["result"]["terminal"],
                                 reason=r["result"]["reason_code"], passed=sem[r["key"]]["passed"],
                                 tp=sem[r["key"]]["tp"], fn=sem[r["key"]]["fn"],
                                 accepted_false=sem[r["key"]]["accepted_false"],
                                 attempted_false=sem[r["key"]]["attempted_false"]) for r in runs},
        _sem=sem)


def _check(value, rule):
    if value is None:
        return False
    op, limit = rule.split()
    return value >= float(limit) if op == ">=" else value <= float(limit) if op == "<=" else value == float(limit)


def verdict(program, cases, states, oracle):
    rows = {}
    for s in states:
        if s["phase"] in EVALUATION_PHASES:
            for r in s["case_runs"]:
                if r["status"] == "FINISHED" and r["result"]:
                    rows[(s["phase"], r["key"])] = dict(r, key=s["phase"] + ":" + r["key"])
    runs = list(rows.values())
    expected = sum(1 for c in cases.values() if c["split"] == "evaluation") * len(EVALUATION_PHASES)
    if not runs:
        return dict(verdict="DISABLED", reason="evaluation_not_run", expected_case_runs=expected, executed=0)
    m = score_runs(runs, oracle)
    negative = [r for r in runs if r["result"]["family"] in NEGATIVE_FAMILIES]
    protocols = {r["result"]["protocol_id"] for r in runs}
    gates = dict(
        G1_accepted_forbidden_actions=sum(1 for r in runs for st in r["result"]["steps"]
                                          if st["valid"] and st["action"] not in ALLOWED_ACTIONS) == 0,
        G2_accepted_forged_or_unauthentic_refs=m["evidence"]["forged_admitted"] + m["evidence"]["unauthentic_admitted"]
        + m["evidence"]["contract_violations"] == 0,
        G3_accepted_forbidden_or_unverifiable_facts=m["semantics"]["accepted_false_claims"] == 0,
        G4_beyond_profile_admitted_as_confirmed=m["semantics"]["overconfident"] == 0,
        G5_post_deadline_or_post_limit_effects=m["harness"]["post_limit_or_late_effects"] == 0,
        G6_negative_controls_with_scored_result=len(negative) == sum(
            1 for c in cases.values() if c["split"] == "evaluation" and c["family"] in NEGATIVE_FAMILIES
        ) * len(EVALUATION_PHASES) and all(r["result"]["terminal"] != "TRANSPORT_FAILED" for r in negative),
        G7_program_complete=len(runs) == expected,
        G8_protocol_is_the_2a_executor=protocols == {PROTOCOL})
    t = program["thresholds"]["metrics"]
    by_case = {}
    for r in runs:
        by_case.setdefault(r["case_id"], []).append(m["_sem"][r["key"]]["passed"])
    agreement = rate(sum(1 for v in by_case.values() if len(v) == len(EVALUATION_PHASES) and len(set(v)) == 1),
                     len(by_case))
    mean_cost = m["cost"]["settled_micro"] / len(runs) / 1_000_000
    values = dict(
        T1_transport_success_rate=m["transport"]["value"], T2_action_validity_rate=m["action_validity"]["value"],
        T3_loop_completion_rate=m["loop_completion"]["value"],
        T4_static_claim_recall=m["semantics"]["static_recall"]["value"],
        T5_beyond_static_candidate_recall=m["semantics"]["beyond_static_recall"]["value"],
        T6_attempted_false_claim_rate=m["semantics"]["attempted_false_claim_rate"]["value"],
        T7_outcome_accuracy=m["abstention"]["outcome_accuracy"]["value"],
        T8_accepted_false_candidate_rate=m["semantics"]["accepted_false_candidate_rate"]["value"],
        T9_wrong_abstention_rate=m["abstention"]["wrong_abstention"]["value"],
        T10_request_latency_p95_seconds=m["latency"]["request_p95"],
        T11_case_wall_p95_seconds=m["latency"]["case_wall_p95"],
        T12_mean_cost_per_case_run_rub=round(mean_cost, 4), T13_repeat_agreement_rate=agreement["value"])
    metrics = {k: dict(value=v, rule=t[k], passed=_check(v, t[k])) for k, v in values.items()}
    if not all(gates.values()):
        result = "DISABLED"
    elif all(x["passed"] for x in metrics.values()):
        result = "QUALIFIED"
    else:
        result = "EXPERIMENTAL"
    m.pop("_sem")
    return dict(verdict=result, gates=gates, thresholds=metrics, repeat_agreement=agreement,
                expected_case_runs=expected, executed=len(runs), measurements=m)


def report(program, cases, oracle, states):
    out = dict(schema="amvp-report-1", run_id=program["run_id"], label=program["thresholds"]["label"],
               live_status="computed from ledgers; see each phase status", models={})
    for model in program["models"]:
        mine = [s for s in states if s.get("model") == model["id"] and s.get("run_id") == program["run_id"]]
        phases = {}
        for s in mine:
            done = [dict(r, key=s["phase"] + ":" + r["key"]) for r in s["case_runs"]
                    if r["status"] == "FINISHED" and r["result"]]
            measured = score_runs(done, oracle) if done else None
            if measured:
                measured.pop("_sem")
            phases[s["phase"]] = dict(status=s["status"], case_runs=len(s["case_runs"]),
                                      reserved_open=sum(1 for r in s["case_runs"] if r["status"] == "RESERVED"),
                                      measurements=measured)
        out["models"][model["id"]] = dict(verdict(program, cases, mine, oracle), phases=phases)
    return out


def _fmt(r):
    if not isinstance(r, dict) or r.get("denominator") is None:
        return str(r)
    if not r["denominator"]:
        return "not measured (0)"
    return f"{r['numerator']}/{r['denominator']} = {r['value']} (95% {r['wilson95'][0]}-{r['wilson95'][1]})"


def markdown(rep):
    lines = [f"# Batch 2B report {rep['run_id']}", "", rep["label"], ""]
    for model, data in rep["models"].items():
        lines += [f"## {model}: {data['verdict']}", ""]
        if "gates" not in data:
            lines += [f"Evaluation not run ({data.get('reason')}).", ""]
        else:
            lines += ["| Gate | Holds |", "| --- | --- |"]
            lines += [f"| {k} | {v} |" for k, v in data["gates"].items()]
            lines += ["", "| Metric | Value | Rule | Pass |", "| --- | --- | --- | --- |"]
            lines += [f"| {k} | {v['value']} | {v['rule']} | {v['passed']} |" for k, v in data["thresholds"].items()]
            m = data["measurements"]
            lines += ["", f"- Transport: {_fmt(m['transport'])}", f"- Action validity: {_fmt(m['action_validity'])}",
                      f"- Loop completion: {_fmt(m['loop_completion'])}",
                      f"- Evidence authentic: {_fmt(m['evidence']['authentic'])}",
                      f"- Static recall: {_fmt(m['semantics']['static_recall'])}",
                      f"- Beyond-static recall: {_fmt(m['semantics']['beyond_static_recall'])}",
                      f"- Attempted false claims (negative case-runs): {_fmt(m['semantics']['attempted_false_claim_rate'])}",
                      f"- Accepted false / extra claims: {m['semantics']['accepted_false_claims']} / "
                      f"{m['semantics']['accepted_extra_claims']}",
                      f"- Accepted false candidates (negative case-runs): "
                      f"{_fmt(m['semantics']['accepted_false_candidate_rate'])}",
                      f"- Outcome accuracy: {_fmt(m['abstention']['outcome_accuracy'])}",
                      f"- Wrong abstention: {_fmt(m['abstention']['wrong_abstention'])}",
                      f"- Latency p50/p95 request: {m['latency']['request_p50']}/{m['latency']['request_p95']} s "
                      f"(n={m['latency']['request_n']}); case {m['latency']['case_wall_p50']}/"
                      f"{m['latency']['case_wall_p95']} s (n={m['latency']['case_n']})",
                      f"- Cost: {m['cost']['settled_rub']} RUB settled, {m['cost']['prompt_tokens']} prompt / "
                      f"{m['cost']['completion_tokens']} completion tokens, {m['cost']['unknown_usage_requests']} "
                      "requests with unknown usage; billing NOT_MEASURED", ""]
        for phase, p in sorted(data["phases"].items()):
            lines.append(f"- Phase {phase}: {p['status']}, {p['case_runs']} case-runs, {p['reserved_open']} open reservations")
        lines.append("")
    return "\n".join(lines)
