"""Score readiness ledgers against the evaluator-only oracle and the frozen thresholds of their revision.

Units and denominators:

- change: one Jira issue and its PR. Change-level rates (useful autonomous
  output, outcome classes, failures) have the number of changes as denominator;
  changes are independent (fresh stand and installation each), so Wilson
  intervals apply;
- stage: the Jira comment or the PR comment of one change;
- consumer pair: (change, consumer) with an oracle severity. FN by severity,
  path correctness and owner accuracy use these; FP uses (change, service)
  pairs that the oracle marks as not affected. Pairs of one change are not
  independent, so their intervals are reported but are optimistic;
- resource: one Jira issue or one PR, for publication integrity.

A change that crashed or never published counts as a failure in every rate,
never as a skipped item.

A ledger is scored with the program, oracle and rules of the revision it names
(``ledger["program"]``), so a 6-r1 ledger scores exactly as it did when 6-r1 was
frozen. Rules a revision adds are read from its ``program.json`` ``scoring``:

- ``pr_runtime_basis: candidate`` (6-r2): on the PR stage a consumer whose only
  basis is runtime must be named with the changed operation and honest
  freshness; its severity is not required, because no call site shows how it
  reads the response. Such pairs leave the breaking-as-breaking denominator and
  get their own rate (``severity.runtime_basis``);
- an expected Jira outcome ``candidate`` (6-r2 F13): PARTIAL candidates or an
  abstention are correct; USEFUL is a wrong confident answer; named bystanders
  count in the Jira FP rate but do not make the stage wrong.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

from tools.autonomous_mvp.scorer import percentile, rate
from tools.autonomous_mvp.readiness import program as program_mod

BREAKING_CODES = ("POSSIBLE_TRUNCATION", "OPERATION_REMOVED")
OUTCOME_OF_STATUS = {"USEFUL": "answer", "PARTIAL": "partial", "ABSTAINED": "abstain"}
STAGES = ("jira", "pr")


# ---------------------------------------------------------------------------- observations


def _entry(named, service):
    return named.setdefault(service, dict(severity=None, targets=[], freshness=[], callsites=[], owner_status=None))


def observe_service(stage, provider):
    """Normalise a service stage record (AnalysisResult + published comment)."""
    result = (stage or {}).get("result")
    text = "\n".join((stage or {}).get("comment_texts") or [])
    if not result:
        return dict(status="FAILED", named={}, text=text)
    rels = {r["id"]: r for r in result["relationships"]}
    named = {}
    for a in result["affected"]:
        if a["service"] == provider:
            continue
        entry = _entry(named, a["service"])
        entry["owner_status"] = a["owner_status"]
        for rid in a["relationship_refs"]:
            if rid in rels:
                t = rels[rid]["target"]
                entry["targets"].append([t["service"], t["method"], t["route"]])
                entry["freshness"].append(rels[rid]["freshness"])
    for f in result.get("findings", []):
        if f["consumer"] == provider:
            continue
        entry = _entry(named, f["consumer"])
        severity = "breaking" if f["code"] in BREAKING_CODES else "recheck"
        if entry["severity"] != "breaking":
            entry["severity"] = severity
        entry["callsites"].append([f["callsite"]["repository"], f["callsite"]["path"]])
    return dict(status=result["status"], named=named, text=text)


def observe_baseline(stage, provider):
    """Normalise a baseline stage record (the agent's final answer)."""
    answer = (stage or {}).get("answer")
    if not isinstance(answer, dict):
        return dict(status="FAILED", named={}, text="")
    status = {"answer": "USEFUL", "partial": "PARTIAL", "abstain": "ABSTAINED"}.get(answer.get("outcome"), "FAILED")
    named = {}
    for item in answer.get("impacted") or []:
        service = item.get("service")
        if not isinstance(service, str) or service == provider:
            continue
        entry = _entry(named, service)
        if item.get("severity") in ("breaking", "recheck"):
            entry["severity"] = item["severity"]
        path = item.get("path") or {}
        entry["targets"].append([path.get("provider"), path.get("method"), path.get("route")])
        entry["freshness"].append(item.get("freshness") or "CURRENT")
        callsite = path.get("callsite")
        if isinstance(callsite, str) and ":" in callsite:
            entry["callsites"].append(callsite.split(":", 1))
        entry["owner_status"] = (item.get("owner") or {}).get("status")
    return dict(status=status, named=named, text=json.dumps(answer, ensure_ascii=False))


# ---------------------------------------------------------------------------- per stage


def score_stage(observed, oracle, stage, rules=None):
    runtime_candidates = stage == "pr" and (rules or {}).get("pr_runtime_basis") == "candidate"
    spec = oracle[stage]
    severities = oracle["pr"]["expected_consumers"]
    expected = {n: severities[n] for n in spec["expected_consumers"]} if stage == "jira" else dict(severities)
    negatives = set(oracle["negatives"])
    named = observed["named"]
    out = dict(status=observed["status"], expected_outcome=spec["expected_outcome"],
               outcome_ok=observed["status"] in spec["acceptable_statuses"],
               expected=len(expected), named=len(named), tp=0, fn=0, fp=0,
               fp_breaking=0, fp_recheck=0, missed_breaking=0, missed_recheck=0, under_severity=0, over_severity=0,
               path_correct=0, owner_checked=0, owner_correct=0, stale_named=0, stale_as_current=0,
               leaks=0, wrong_confident=0, runtime_pairs=0, runtime_named=0, problems=[])
    for consumer, severity in expected.items():
        seen = named.get(consumer)
        runtime_only = runtime_candidates and oracle["paths"][consumer]["basis"] in ("runtime", "stale_runtime")
        if runtime_only:
            out["runtime_pairs"] += 1
            out["runtime_named"] += seen is not None
        if seen is None:
            out["fn"] += 1
            # A runtime-only pair left the breaking and recheck denominators (6-r2 rule); its miss is
            # counted by runtime_named. Counting it here too drove those rates below zero.
            if not runtime_only:
                out["missed_breaking" if severity == "breaking" else "missed_recheck"] += 1
            out["problems"].append(f"missed:{consumer}")
            continue
        out["tp"] += 1
        if stage == "pr" and not runtime_only:
            if severity == "breaking" and seen["severity"] != "breaking":
                out["under_severity"] += 1
                out["problems"].append(f"under_severity:{consumer}")
            if severity == "recheck" and seen["severity"] == "breaking":
                out["over_severity"] += 1
                out["problems"].append(f"over_severity:{consumer}")
        path = oracle["paths"][consumer]
        target_ok = [path["provider"], path["method"], path["route"]] in seen["targets"]
        callsite_ok = (stage == "jira" or path["callsite"] is None
                       or [path["callsite"]["repository"], path["callsite"]["path"]] in seen["callsites"])
        if target_ok and callsite_ok:
            out["path_correct"] += 1
        else:
            out["problems"].append(f"path:{consumer}")
        out["owner_checked"] += 1
        if seen["owner_status"] == oracle["services"][consumer]["owner_status"]:
            out["owner_correct"] += 1
        else:
            out["problems"].append(f"owner:{consumer}")
        if path["basis"] == "stale_runtime":
            out["stale_named"] += 1
            if seen["freshness"] and all(f == "CURRENT" for f in seen["freshness"]):
                out["stale_as_current"] += 1
                out["problems"].append(f"stale_as_current:{consumer}")
    for service, seen in named.items():
        if service in negatives:
            out["fp"] += 1
            out["fp_breaking" if seen["severity"] == "breaking" else "fp_recheck"] += 1
            if spec["expected_outcome"] != "candidate":
                out["problems"].append(f"false_positive:{service}")
    for service in oracle["revoked"]:
        if service in named or re.search(rf"(?<![A-Za-z0-9_-]){re.escape(service)}(?![A-Za-z0-9_-])",
                                         observed["text"]):
            out["leaks"] += 1
            out["problems"].append(f"revoked_leak:{service}")
    if observed["status"] == "USEFUL" and spec["expected_outcome"] in ("abstain", "no_impact", "candidate"):
        out["wrong_confident"] = 1
    if not out["outcome_ok"]:
        out["problems"].append(f"outcome:{observed['status']}!={spec['expected_outcome']}")
    out["correct"] = not out["problems"]
    return out


# ---------------------------------------------------------------------------- aggregation


def _sum(stages, key):
    return sum(s[key] for s in stages)


def stage_summary(stages):
    classes = {"answer": 0, "partial": 0, "abstain": 0, "failure": 0}
    for s in stages:
        classes[OUTCOME_OF_STATUS.get(s["status"], "failure")] += 1
    expected_classes = {}
    for s in stages:
        expected_classes[s["expected_outcome"]] = expected_classes.get(s["expected_outcome"], 0) + 1
    return dict(
        n=len(stages), correct=rate(sum(s["correct"] for s in stages), len(stages)),
        outcome_accuracy=rate(sum(s["outcome_ok"] for s in stages), len(stages)),
        observed_outcomes=classes, expected_outcomes=dict(sorted(expected_classes.items())),
        failure=rate(classes["failure"], len(stages)),
        wrong_confident=rate(_sum(stages, "wrong_confident"),
                             sum(s["expected_outcome"] in ("abstain", "no_impact", "candidate") for s in stages)),
        consumer_recall=rate(_sum(stages, "tp"), _sum(stages, "expected")),
        path_correct=rate(_sum(stages, "path_correct"), _sum(stages, "expected")),
        false_positives=dict(count=_sum(stages, "fp"), breaking=_sum(stages, "fp_breaking"),
                             recheck=_sum(stages, "fp_recheck")),
        owner_accuracy=rate(_sum(stages, "owner_correct"), _sum(stages, "owner_checked")),
        stale_as_current=dict(count=_sum(stages, "stale_as_current"), named_stale=_sum(stages, "stale_named")),
        revoked_leaks=_sum(stages, "leaks"))


def score(ledger, oracle, *, kind="service", rules=None):
    observe = observe_service if kind == "service" else observe_baseline
    records = {r["change_id"]: r for r in ledger["records"]}
    missing = sorted(set(oracle) - set(records))
    per_change, stages = [], {s: [] for s in STAGES}
    negatives_total = sum(len(o["negatives"]) for cid, o in oracle.items())
    for cid in sorted(oracle):
        o = oracle[cid]
        record = records.get(cid) or {}
        row = dict(change_id=cid, family=o["family"], error=record.get("error") if record else "not_run")
        for stage in STAGES:
            s = score_stage(observe(record.get(stage), o["provider"]), o, stage, rules)
            row[stage] = s
            stages[stage].append(s)
        pubs = [((record.get(stage) or {}).get("publication") or {}) for stage in STAGES] if kind == "service" else []
        row["publication_ok"] = (all(p and not p["lost"] and not p["duplicate"] and not p["stale"]
                                     and p["writes_after_redelivery"] == 0 for p in pubs) if kind == "service"
                                 else None)
        row["useful"] = (not row["error"] and row["jira"]["correct"] and row["pr"]["correct"]
                         and row["publication_ok"] is not False)
        per_change.append(row)
    n = len(per_change)
    out = dict(kind=kind, configuration=ledger.get("configuration"), split=ledger.get("split"),
               manifest_digest=ledger.get("manifest_digest"), manifest_current=ledger.get("manifest_current"),
               changes=n, not_run=missing, errors=[r["change_id"] for r in per_change if r["error"]],
               useful_autonomous=rate(sum(r["useful"] for r in per_change), n),
               stages={s: stage_summary(stages[s]) for s in STAGES})
    out["error_count"] = len(out["errors"])
    out["useful_autonomous_lower95"] = (out["useful_autonomous"]["wilson95"] or [None])[0]
    pr = stages["pr"]
    runtime_rule = (rules or {}).get("pr_runtime_basis") == "candidate"

    def counted(o, name):
        return not (runtime_rule and o["paths"][name]["basis"] in ("runtime", "stale_runtime"))

    expected_pairs = {sev: sum(1 for o in oracle.values() for n, v in o["pr"]["expected_consumers"].items()
                               if v == sev and counted(o, n))
                      for sev in ("breaking", "recheck")}
    out["severity"] = dict(
        breaking=dict(pairs=expected_pairs["breaking"],
                      reported_breaking=rate(expected_pairs["breaking"] - _sum(pr, "missed_breaking")
                                             - _sum(pr, "under_severity"), expected_pairs["breaking"]),
                      missed=_sum(pr, "missed_breaking"), under_severity=_sum(pr, "under_severity")),
        recheck=dict(pairs=expected_pairs["recheck"],
                     named=rate(expected_pairs["recheck"] - _sum(pr, "missed_recheck"), expected_pairs["recheck"]),
                     missed=_sum(pr, "missed_recheck"), over_severity=_sum(pr, "over_severity")),
        runtime_basis=dict(pairs=_sum(pr, "runtime_pairs"),
                           named=rate(_sum(pr, "runtime_named"), _sum(pr, "runtime_pairs"))) if runtime_rule else None,
        negatives=dict(pairs=negatives_total,
                       jira_fp=rate(_sum(stages["jira"], "fp"), negatives_total),
                       pr_fp=rate(_sum(pr, "fp"), negatives_total),
                       pr_fp_breaking=_sum(pr, "fp_breaking"), pr_fp_recheck=_sum(pr, "fp_recheck")))
    if kind == "service":
        out["publication"] = publication_summary(ledger, n)
        out["latency"] = {s: latency(ledger, s) for s in STAGES}
        out["graph_freshness"] = graph_freshness(ledger, oracle)
    out["cost"] = cost(ledger)
    out["human"] = human(ledger)
    out["families"] = families(per_change)
    out["per_change"] = [dict(change_id=r["change_id"], family=r["family"], useful=r["useful"], error=r["error"],
                              jira=dict(status=r["jira"]["status"], problems=r["jira"]["problems"]),
                              pr=dict(status=r["pr"]["status"], problems=r["pr"]["problems"]),
                              publication_ok=r["publication_ok"]) for r in per_change]
    return out


def publication_summary(ledger, changes):
    pubs = [r[s]["publication"] for r in ledger["records"] for s in STAGES if r.get(s)]
    resources = 2 * changes
    return dict(resources=resources, observed=len(pubs),
                lost=sum(p["lost"] for p in pubs) + (resources - len(pubs)),
                duplicate=sum(p["duplicate"] for p in pubs),
                stale=sum(p["stale"] for p in pubs),
                writes_after_redelivery=sum(p["writes_after_redelivery"] for p in pubs),
                creates=sum(p["creates"] for p in pubs), updates=sum(p["updates"] for p in pubs),
                redelivery_recognised=rate(sum(bool(r[s].get("redelivery_duplicate")) for r in ledger["records"]
                                               for s in STAGES if r.get(s)), len(pubs)))


def latency(ledger, stage):
    values = [r[stage]["latency_seconds"] for r in ledger["records"] if r.get(stage)
              and r[stage].get("latency_seconds") is not None]
    return dict(n=len(values), p50=percentile(values, 0.5), p95=percentile(values, 0.95),
                max=round(max(values), 3) if values else None)


def graph_freshness(ledger, oracle):
    rows = []
    for r in ledger["records"]:
        merge = r.get("merge")
        if not merge:
            rows.append((False, None))
            continue
        o = oracle[r["change_id"]]
        changed = o["changed_operation"]
        routes = set(o["world"]["defaults"]["change"])
        reflects = merge["provider_source_version"] == merge["head"] and set(merge["active_operations"]) == routes
        if changed and changed["route"] not in routes and changed["route"] in merge["active_operations"]:
            reflects = False
        rows.append((reflects, merge["seconds"]))
    seconds = [s for _, s in rows if s is not None]
    return dict(reflected_after_one_reconcile=rate(sum(ok for ok, _ in rows), len(oracle)),
                seconds_p50=percentile(seconds, 0.5), seconds_p95=percentile(seconds, 0.95))


def cost(ledger):
    records = ledger["records"]
    calls = sum((r.get("costs") or {}).get("model_calls") or 0 for r in records)
    tokens = [(r.get("costs") or {}) for r in records]
    rub = [(r.get("costs") or {}).get("rub") for r in records]
    known_rub = [x for x in rub if x is not None]
    total = 0.0 if calls == 0 else (round(sum(known_rub), 2) if len(known_rub) == len(rub) else None)
    return dict(model_calls=calls, prompt_tokens=sum(t.get("prompt_tokens") or 0 for t in tokens),
                rub_per_change=None if total is None or not records else round(total / len(records), 4),
                completion_tokens=sum(t.get("completion_tokens") or 0 for t in tokens),
                rub_total=total,
                rub_status="NO_MODEL_CALLS" if calls == 0 else ("MEASURED" if len(known_rub) == len(rub)
                                                                 else "NOT_MEASURED"),
                cpu_wall_seconds=round(sum(r.get("wall_seconds") or 0 for r in records), 1))


def human(ledger):
    minutes = [r["human"]["active_minutes"] for r in ledger["records"]
               if (r.get("human") or {}).get("active_minutes") is not None]
    return dict(interventions=sum((r.get("human") or {}).get("interventions") or 0 for r in ledger["records"]),
                active_minutes_recorded=len(minutes), active_minutes_total=sum(minutes) if minutes else None,
                active_minutes_median=percentile(minutes, 0.5),
                active_minutes_coverage=rate(len(minutes), len(ledger["records"])),
                status="RECORDED" if minutes else "NOT_RECORDED")


def families(per_change):
    out = {}
    for r in per_change:
        row = out.setdefault(r["family"], dict(changes=0, useful=0, jira_correct=0, pr_correct=0))
        row["changes"] += 1
        row["useful"] += bool(r["useful"])
        row["jira_correct"] += bool(r["jira"]["correct"])
        row["pr_correct"] += bool(r["pr"]["correct"])
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------- thresholds


def lookup(report, path):
    value = report
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def verdict(report, thresholds, *, baseline=None):
    rows, gates = [], {}
    for t in thresholds:
        source = baseline if t.get("needs") == "baseline" else report
        if t.get("needs") == "baseline":
            if baseline is None or baseline.get("configuration_kind") != "live":
                rows.append(dict(t, observed=None, result="NOT_EVALUATED"))
                gates.setdefault(t["gate"], []).append("NOT_EVALUATED")
                continue
            observed = (lookup(report, t["metric"]) or 0) - (lookup(baseline, t["metric"]) or 0)
        else:
            observed = lookup(source, t["metric"])
        if observed is None:
            result = "NOT_MEASURED"
        else:
            ok = {"<=": observed <= t["value"], ">=": observed >= t["value"], "==": observed == t["value"]}[t["op"]]
            result = "PASS" if ok else "FAIL"
        rows.append(dict(t, observed=observed, result=result))
        gates.setdefault(t["gate"], []).append(result)
    summary = {}
    for gate, results in gates.items():
        if "FAIL" in results:
            summary[gate] = "FAIL"
        elif all(r == "PASS" for r in results):
            summary[gate] = "PASS"
        else:
            summary[gate] = "INCOMPLETE"
    return dict(thresholds=rows, gates=summary)


def apply_human_minutes(ledger, recorded):
    """Operator-recorded active minutes per change: {"recorded_by": ..., "minutes": {change_id: number}}.

    Only recorded values enter the report; a change without a record stays NOT_RECORDED.
    """
    minutes = recorded.get("minutes") or {}
    unknown = sorted(set(minutes) - {r["change_id"] for r in ledger["records"]})
    if unknown or not recorded.get("recorded_by"):
        raise SystemExit("REFUSED human minutes: need recorded_by and known change ids " + ",".join(unknown))
    for r in ledger["records"]:
        value = minutes.get(r["change_id"])
        if value is not None:
            if not isinstance(value, (int, float)) or value < 0:
                raise SystemExit(f"REFUSED human minutes: invalid value for {r['change_id']}")
            r["human"] = dict(r.get("human") or {}, active_minutes=float(value), status="RECORDED",
                              recorded_by=recorded["recorded_by"])
    return ledger


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("ledger")
    parser.add_argument("--baseline", help="baseline ledger of the same split, for the comparison gate")
    parser.add_argument("--human-minutes", help="JSON with operator-recorded active minutes per change")
    parser.add_argument("--full", action="store_true", help="print the per-change rows too")
    args = parser.parse_args()
    ledger = json.loads(Path(args.ledger).read_text(encoding="utf-8"))
    if args.human_minutes:
        apply_human_minutes(ledger, json.loads(Path(args.human_minutes).read_text(encoding="utf-8")))
    revision_dir = program_mod.program_dir(ledger["program"])
    oracle = program_mod.load_oracle(ledger["split"], revision_dir)
    _, program, _ = program_mod.load(revision_dir)
    rules = program.get("scoring") or {}
    kind = "baseline" if ledger.get("configuration", "").startswith("baseline") else "service"
    report = score(ledger, oracle, kind=kind, rules=rules)
    base = None
    if args.baseline:
        bl = json.loads(Path(args.baseline).read_text(encoding="utf-8"))
        if bl.get("program") != ledger["program"] or bl.get("split") != ledger["split"]:
            raise SystemExit("REFUSED baseline of another revision or split")
        base = score(bl, oracle, kind="baseline", rules=rules)
        base["configuration_kind"] = bl.get("transport_kind")
    report["verdict"] = verdict(report, program["thresholds"], baseline=base) if kind == "service" else None
    if not args.full:
        report.pop("per_change")
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
