"""Readiness scorer (current revision rules): each kind of wrong output is counted on its own denominator, and nothing wrong is useful.

The ledgers here are built by hand in the runner's record shape: one that says
exactly what the oracle says, then one deliberate error at a time.
"""
import copy
import unittest

from tools.autonomous_mvp.readiness import program, scorer

ORACLE = program.load_oracle("development")
_, PROGRAM, _ = program.load()
RULES = PROGRAM["scoring"]


def relationship(rid, consumer, o, freshness="CURRENT"):
    path = o["paths"][consumer]
    return dict(id=rid, source=consumer, target=dict(service=path["provider"], method=path["method"],
                                                     route=path["route"]),
                origins=["code"], freshness=freshness)


def ideal_stage(o, stage):
    expected = o["jira"]["expected_consumers"] if stage == "jira" else list(o["pr"]["expected_consumers"])
    status = {"answer": "USEFUL", "partial": "PARTIAL", "abstain": "ABSTAINED", "no_impact": "ABSTAINED",
              "candidate": "PARTIAL"}[o[stage]["expected_outcome"]]
    rels, affected, findings = [], [], []
    for i, consumer in enumerate(expected):
        fresh = "STALE" if o["paths"][consumer]["basis"] == "stale_runtime" else "CURRENT"
        rels.append(relationship(f"rel:{i}", consumer, o, fresh))
        affected.append(dict(service=consumer, owner_status=o["services"][consumer]["owner_status"], owner_teams=[],
                             relationship_refs=[f"rel:{i}"]))
        if stage == "pr" and o["paths"][consumer]["basis"] == "code":
            # A runtime-only consumer has no call site: the service names it without a finding.
            severity = o["pr"]["expected_consumers"][consumer]
            callsite = dict(o["paths"][consumer]["callsite"] or dict(repository=consumer, path="client.py"))
            findings.append(dict(code="POSSIBLE_TRUNCATION" if severity == "breaking" else "RECHECK_REQUIRED",
                                 consumer=consumer, usage="SINGLE_REQUEST_OBSERVED", callsite=callsite))
    result = dict(status=status, reason_code="x", affected=affected, relationships=rels, findings=findings,
                  unknowns=[], source_freshness=[], costs=dict(model_calls=0))
    publication = dict(lost=False, duplicate=False, stale=False, writes_after_redelivery=0, creates=1, updates=0)
    return dict(result=result, comment_texts=["comment"], publication=publication, latency_seconds=1.0,
                redelivery_duplicate=True)


def ideal_record(o):
    head = "a" * 40
    return dict(change_id=o["change_id"], error=None, jira=ideal_stage(o, "jira"), pr=ideal_stage(o, "pr"),
                merge=dict(head=head, provider_source_version=head, seconds=1.0,
                           active_operations=sorted(o["world"]["defaults"]["change"])),
                costs=dict(model_calls=0), wall_seconds=5.0,
                human=dict(interventions=0, active_minutes=None, status="NOT_RECORDED"))


def ledger(records):
    return dict(configuration="service-no-model", split="development", manifest_digest="m", manifest_current=True,
                records=records)


def score(records, rules=RULES):
    return scorer.score(ledger(records), ORACLE, rules=rules)


class IdealOutput(unittest.TestCase):
    def test_output_equal_to_the_oracle_is_useful_for_every_change(self):
        report = score([ideal_record(o) for o in ORACLE.values()])
        self.assertEqual(report["useful_autonomous"]["numerator"], len(ORACLE))
        self.assertEqual(report["severity"]["breaking"]["reported_breaking"]["value"], 1.0)
        self.assertEqual(report["severity"]["negatives"]["pr_fp"]["numerator"], 0)
        self.assertEqual(report["graph_freshness"]["reflected_after_one_reconcile"]["value"], 1.0)
        gates = scorer.verdict(report, PROGRAM["thresholds"])["gates"]
        self.assertEqual((gates["technical"], gates["quality"]), ("PASS", "PASS"))
        self.assertEqual(gates["comparison"], "INCOMPLETE")  # no live baseline ledger
        self.assertEqual(gates["human"], "INCOMPLETE")  # minutes not recorded


class OneErrorAtATime(unittest.TestCase):
    def setUp(self):
        self.records = {cid: ideal_record(o) for cid, o in ORACLE.items()}

    def rescore(self):
        return score(list(self.records.values()))

    def pr_change(self, family):
        return next(cid for cid, o in sorted(ORACLE.items()) if o["family"] == family)

    def test_a_missed_breaking_consumer_is_a_breaking_false_negative(self):
        cid = self.pr_change("F01_truncation")
        stage = self.records[cid]["pr"]["result"]
        gone = next(f["consumer"] for f in stage["findings"] if f["code"] == "POSSIBLE_TRUNCATION")
        stage["affected"] = [a for a in stage["affected"] if a["service"] != gone]
        stage["findings"] = [f for f in stage["findings"] if f["consumer"] != gone]
        report = self.rescore()
        self.assertEqual(report["severity"]["breaking"]["missed"], 1)
        self.assertEqual(report["useful_autonomous"]["numerator"], len(ORACLE) - 1)

    def test_a_breaking_consumer_reported_as_recheck_is_under_severity_not_a_miss(self):
        cid = self.pr_change("F01_truncation")
        finding = next(f for f in self.records[cid]["pr"]["result"]["findings"] if f["code"] == "POSSIBLE_TRUNCATION")
        finding["code"] = "RECHECK_REQUIRED"
        report = self.rescore()
        self.assertEqual((report["severity"]["breaking"]["missed"], report["severity"]["breaking"]["under_severity"]),
                         (0, 1))
        self.assertLess(report["severity"]["breaking"]["reported_breaking"]["value"], 1.0)

    def test_a_named_bystander_is_a_false_positive_on_the_negative_denominator(self):
        cid = self.pr_change("F01_truncation")
        bystander = next(n for n, s in ORACLE[cid]["services"].items() if s.get("kind") == "bystander")
        self.records[cid]["pr"]["result"]["affected"].append(dict(service=bystander, owner_status="KNOWN",
                                                                  owner_teams=[], relationship_refs=[]))
        report = self.rescore()
        fp = report["severity"]["negatives"]["pr_fp"]
        self.assertEqual((fp["numerator"], fp["denominator"]), (1, sum(len(o["negatives"]) for o in ORACLE.values())))
        self.assertFalse(next(r for r in report["per_change"] if r["change_id"] == cid)["useful"])

    def test_a_revoked_service_in_the_comment_text_is_a_leak(self):
        cid = self.pr_change("F08_revoked_source")
        self.records[cid]["jira"]["comment_texts"] = [f"... {ORACLE[cid]['revoked'][0]}: команда ..."]
        report = self.rescore()
        self.assertEqual(report["stages"]["jira"]["revoked_leaks"], 1)
        self.assertEqual(scorer.verdict(report, PROGRAM["thresholds"])["gates"]["technical"], "FAIL")

    def test_a_revoked_name_inside_a_longer_name_is_not_a_leak(self):
        cid = self.pr_change("F08_revoked_source")
        self.records[cid]["jira"]["comment_texts"] = [f"{ORACLE[cid]['revoked'][0]}x-service"]
        self.assertEqual(self.rescore()["stages"]["jira"]["revoked_leaks"], 0)

    def test_stale_runtime_evidence_shown_as_current_is_counted(self):
        cid = self.pr_change("F07_stale_runtime")
        for rel in self.records[cid]["jira"]["result"]["relationships"]:
            rel["freshness"] = "CURRENT"
        report = self.rescore()
        self.assertEqual(report["stages"]["jira"]["stale_as_current"]["count"], 1)

    def test_a_wrong_call_site_breaks_the_path(self):
        cid = self.pr_change("F01_truncation")
        self.records[cid]["pr"]["result"]["findings"][0]["callsite"]["path"] = "other.py"
        report = self.rescore()
        self.assertLess(report["stages"]["pr"]["path_correct"]["value"], 1.0)
        self.assertEqual(report["severity"]["breaking"]["missed"], 0)

    def test_a_confident_answer_where_abstaining_is_correct_is_wrong_confident(self):
        cid = self.pr_change("F10_ambiguous_jira")
        self.records[cid]["jira"]["result"]["status"] = "USEFUL"
        report = self.rescore()
        self.assertEqual(report["stages"]["jira"]["wrong_confident"]["numerator"], 1)

    def test_a_guessed_owner_is_counted(self):
        cid = self.pr_change("F09_ownership_conflict")
        for a in self.records[cid]["pr"]["result"]["affected"]:
            a["owner_status"] = "KNOWN"
        report = self.rescore()
        self.assertLess(report["stages"]["pr"]["owner_accuracy"]["value"], 1.0)

    def test_publication_problems_make_the_change_not_useful_and_fail_the_technical_gate(self):
        cid = self.pr_change("F01_truncation")
        self.records[cid]["pr"]["publication"]["duplicate"] = True
        report = self.rescore()
        self.assertEqual(report["publication"]["duplicate"], 1)
        self.assertEqual(report["useful_autonomous"]["numerator"], len(ORACLE) - 1)
        self.assertEqual(scorer.verdict(report, PROGRAM["thresholds"])["gates"]["technical"], "FAIL")

    def test_a_change_that_never_ran_is_a_failure_in_every_rate(self):
        del self.records["D05"]
        report = self.rescore()
        self.assertEqual(report["not_run"], ["D05"])
        self.assertEqual(report["useful_autonomous"]["denominator"], len(ORACLE))
        self.assertEqual(report["stages"]["pr"]["observed_outcomes"]["failure"], 1)
        self.assertEqual(report["publication"]["lost"], 2)

    def test_a_merge_not_reflected_in_the_graph_is_counted(self):
        cid = self.pr_change("F02_operation_removed")
        merge = self.records[cid]["merge"]
        merge["active_operations"] = sorted(ORACLE[cid]["world"]["defaults"]["main"])
        report = self.rescore()
        self.assertEqual(report["graph_freshness"]["reflected_after_one_reconcile"]["numerator"], len(ORACLE) - 1)


class HumanMinutes(unittest.TestCase):
    def test_only_recorded_minutes_count_and_the_gate_stays_incomplete_without_them(self):
        records = [ideal_record(o) for o in ORACLE.values()]
        report = score(records)
        self.assertEqual((report["human"]["status"], report["human"]["active_minutes_median"]), ("NOT_RECORDED", None))
        data = scorer.apply_human_minutes(ledger(records), dict(recorded_by="operator", minutes={"D01": 3, "D02": 4}))
        report = scorer.score(data, ORACLE)
        self.assertEqual(report["human"]["active_minutes_recorded"], 2)
        self.assertEqual(report["human"]["active_minutes_coverage"]["denominator"], len(ORACLE))
        self.assertEqual(scorer.verdict(report, PROGRAM["thresholds"])["gates"]["human"], "FAIL")  # median 3 > 2

    def test_minutes_for_an_unknown_change_or_without_a_recorder_are_refused(self):
        records = [ideal_record(o) for o in ORACLE.values()]
        with self.assertRaises(SystemExit):
            scorer.apply_human_minutes(ledger(records), dict(recorded_by="operator", minutes={"H99": 1}))
        with self.assertRaises(SystemExit):
            scorer.apply_human_minutes(ledger(records), dict(minutes={"D01": 1}))


class Baseline(unittest.TestCase):
    def test_baseline_answers_are_scored_with_the_same_rules(self):
        o = ORACLE[next(cid for cid, x in sorted(ORACLE.items()) if x["family"] == "F01_truncation")]
        impacted = []
        for consumer, severity in o["pr"]["expected_consumers"].items():
            path = o["paths"][consumer]
            impacted.append(dict(service=consumer, severity=severity, owner=dict(
                status=o["services"][consumer]["owner_status"]), freshness="CURRENT",
                path=dict(provider=path["provider"], method=path["method"], route=path["route"],
                          callsite=f"{consumer}:client.py")))
        record = dict(change_id=o["change_id"], error=None,
                      jira=dict(answer=dict(outcome="answer", impacted=impacted)),
                      pr=dict(answer=dict(outcome="answer", impacted=impacted)), costs=dict(model_calls=0))
        report = scorer.score(dict(configuration="baseline-x", split="development", records=[record]),
                              {o["change_id"]: o}, kind="baseline")
        self.assertEqual(report["useful_autonomous"]["numerator"], 1)
        record["pr"]["answer"]["impacted"] = impacted[1:]
        report = scorer.score(dict(configuration="baseline-x", split="development", records=[record]),
                              {o["change_id"]: o}, kind="baseline")
        self.assertEqual(report["useful_autonomous"]["numerator"], 0)

    def test_comparison_gate_needs_a_live_baseline(self):
        report = score([ideal_record(o) for o in ORACLE.values()])
        scripted = copy.deepcopy(report)
        scripted["configuration_kind"] = "scripted"
        rows = scorer.verdict(report, PROGRAM["thresholds"], baseline=scripted)["thresholds"]
        self.assertEqual(next(r for r in rows if r["gate"] == "comparison")["result"], "NOT_EVALUATED")
        live = copy.deepcopy(report)
        live["configuration_kind"] = "live"
        live["useful_autonomous"]["value"] = 0.95
        rows = scorer.verdict(report, PROGRAM["thresholds"], baseline=live)["thresholds"]
        self.assertEqual(next(r for r in rows if r["gate"] == "comparison")["result"], "FAIL")


class RevisionRules(unittest.TestCase):
    """6-r2 rules for runtime-only PR consumers and candidate Jira stages; 6-r1 ledgers keep 6-r1 rules."""

    def runtime_change(self):
        return next(o for o in ORACLE.values() if any(p["basis"] == "runtime" for p in o["paths"].values()))

    def score_with(self, record, rules=RULES):
        records = [record if o["change_id"] == record["change_id"] else ideal_record(o) for o in ORACLE.values()]
        return score(records, rules)

    def test_runtime_only_consumer_named_without_a_finding_is_correct_under_6r2_rules(self):
        o = self.runtime_change()
        report = self.score_with(ideal_record(o))
        row = next(r for r in report["per_change"] if r["change_id"] == o["change_id"])
        self.assertEqual(row["pr"]["problems"], [])
        self.assertEqual(report["severity"]["runtime_basis"]["named"]["value"], 1.0)

    def test_the_same_output_is_under_severity_under_6r1_rules(self):
        o = self.runtime_change()
        report = self.score_with(ideal_record(o), rules={})
        row = next(r for r in report["per_change"] if r["change_id"] == o["change_id"])
        self.assertTrue(any(p.startswith("under_severity:") for p in row["pr"]["problems"]))
        self.assertIsNone(report["severity"]["runtime_basis"])

    def test_a_missed_runtime_only_consumer_fails_the_runtime_rate(self):
        o = self.runtime_change()
        record = ideal_record(o)
        name = next(n for n, p in o["paths"].items() if p["basis"] == "runtime")
        record["pr"]["result"]["affected"] = [a for a in record["pr"]["result"]["affected"] if a["service"] != name]
        report = self.score_with(record)
        self.assertLess(report["severity"]["runtime_basis"]["named"]["value"], 1.0)

    def test_candidate_stage_answered_with_confidence_is_wrong_confident(self):
        o = next(o for o in ORACLE.values() if o["jira"]["expected_outcome"] == "candidate")
        record = ideal_record(o)
        record["jira"]["result"]["status"] = "USEFUL"
        report = self.score_with(record)
        self.assertEqual(report["stages"]["jira"]["wrong_confident"]["numerator"], 1)

    def test_candidate_stage_naming_a_bystander_counts_fp_but_stays_correct(self):
        o = next(o for o in ORACLE.values() if o["jira"]["expected_outcome"] == "candidate")
        record = ideal_record(o)
        bystander = o["negatives"][0]
        record["jira"]["result"]["affected"].append(dict(service=bystander, owner_status="KNOWN", owner_teams=[],
                                                         relationship_refs=[]))
        report = self.score_with(record)
        row = next(r for r in report["per_change"] if r["change_id"] == o["change_id"])
        self.assertEqual(row["jira"]["problems"], [])
        self.assertEqual(report["severity"]["negatives"]["jira_fp"]["numerator"], 1)


if __name__ == "__main__":
    unittest.main()
