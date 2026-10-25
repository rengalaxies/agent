"""Dry runs through runner + 2A executor + ledger + scorer, on one case per family.

The full program dry run (all 61 cases) is `python -m tools.autonomous_mvp.dryrun`;
these tests use a smaller corpus so the verdict logic is exercised end to end quickly.
"""
import tempfile
import unittest

from tools.autonomous_mvp import dryrun
from tools.autonomous_mvp.tests.helpers import MODEL, ORACLE, SMALL, one_model_program


def run(behaviour):
    with tempfile.TemporaryDirectory() as work:
        report, states, sent = dryrun.dry_run(one_model_program(), SMALL, ORACLE, model_id=MODEL,
                                              behaviour=behaviour, work=work)
    return report["models"][MODEL], states, sent


class DryRun(unittest.TestCase):
    def test_follow_passes_every_case_and_qualifies(self):
        verdict, states, _ = run("follow")
        self.assertEqual([s["status"] for s in states], ["COMPLETED"] * 5)
        self.assertTrue(all(verdict["gates"].values()), verdict["gates"])
        cases = verdict["measurements"]["per_case"]
        self.assertEqual({k: v for k, v in cases.items() if not v["passed"]}, {})
        self.assertEqual(verdict["verdict"], "QUALIFIED", verdict["thresholds"])
        # Regression for the dde1f90 defect fixed in 2A b8ee515: a repository unavailable since
        # prepare made run_investigation raise stale_context, so every F05 case was CORE_REFUSED.
        f05 = [v for v in cases.values() if v["family"] == "F05_source_unavailable"]
        self.assertEqual({v["terminal"] for v in f05}, {"FINISHED"})

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
