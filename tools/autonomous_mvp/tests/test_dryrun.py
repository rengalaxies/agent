"""Dry runs through runner + 2A executor + ledger + scorer, on one case per family.

The full program dry run (all 61 cases) is `python -m tools.autonomous_mvp.dryrun`;
these tests use a smaller corpus so the verdict logic is exercised end to end quickly.
"""
import tempfile
import unittest

from tools.autonomous_mvp import dryrun
from tools.autonomous_mvp.tests.helpers import CASES, MODEL, ORACLE, one_model_program

# S01, one development case and one evaluation case of every family.
SMALL = {k: CASES[k] for k in ["S01", "D01"] + sorted(
    {c["family"]: k for k, c in sorted(CASES.items(), reverse=True) if c["split"] == "evaluation"}.values())}


def run(behaviour):
    with tempfile.TemporaryDirectory() as work:
        report, states, sent = dryrun.dry_run(one_model_program(), SMALL, ORACLE, model_id=MODEL,
                                              behaviour=behaviour, work=work)
    return report["models"][MODEL], states, sent


class DryRun(unittest.TestCase):
    def test_follow_passes_every_case_except_where_the_core_refuses_the_unavailable_source(self):
        verdict, states, _ = run("follow")
        self.assertEqual([s["status"] for s in states], ["COMPLETED"] * 5)
        self.assertTrue(all(verdict["gates"].values()), verdict["gates"])
        cases = verdict["measurements"]["per_case"]
        self.assertTrue(all(v["passed"] for v in cases.values() if v["family"] != "F05_source_unavailable"),
                        {k: v for k, v in cases.items() if not v["passed"]})
        # On dde1f90, pinned_freshness refuses a context whose pinned repository is unavailable, so F05
        # ends CORE_REFUSED before any model call (reported to mvp-2a-core). That costs only static recall.
        f05 = [v for v in cases.values() if v["family"] == "F05_source_unavailable"]
        if all(v["passed"] for v in f05):
            self.assertEqual(verdict["verdict"], "QUALIFIED")
        else:
            self.assertEqual({v["terminal"] for v in f05}, {"CORE_REFUSED"})
            failing = {k for k, v in verdict["thresholds"].items() if not v["passed"]}
            self.assertLessEqual(failing, {"T4_static_claim_recall"})

    def test_decoy_taker_is_held_by_the_executor_but_fails_the_false_claim_thresholds(self):
        verdict, _, _ = run("decoy_taker")
        self.assertTrue(verdict["gates"]["G3_accepted_forbidden_or_unverifiable_facts"])
        self.assertGreater(verdict["measurements"]["semantics"]["accepted_false_candidates"], 0)
        self.assertFalse(verdict["thresholds"]["T6_attempted_false_claim_rate"]["passed"])
        self.assertEqual(verdict["verdict"], "EXPERIMENTAL")

    def test_broken_model_never_reaches_evaluation(self):
        verdict, states, _ = run("broken")
        self.assertEqual([s["phase"] for s in states], ["transport"])
        self.assertEqual((verdict["verdict"], verdict.get("reason")), ("DISABLED", "evaluation_not_run"))


if __name__ == "__main__":
    unittest.main()
