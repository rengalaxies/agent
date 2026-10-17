from pathlib import Path
import unittest

from datamesh_release_protocol.engine import ReleaseEngine, finalize
from datamesh_release_protocol.loaders import load_baseline_policy, load_scenario
from datamesh_release_protocol.models import Decision, ValidationMode


class FailSafeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = ReleaseEngine(load_baseline_policy(Path("policies/v1-ind.yaml")))

    def test_finalization_priority(self):
        self.assertEqual(finalize([Decision.ACCEPT, Decision.REJECT]), Decision.REJECT)
        self.assertEqual(
            finalize([Decision.ACCEPT, Decision.NEEDS_REVIEW]),
            Decision.NEEDS_REVIEW,
        )
        self.assertEqual(finalize([Decision.ACCEPT, Decision.ACCEPT]), Decision.ACCEPT)
        self.assertEqual(finalize([]), Decision.NEEDS_REVIEW)

    def test_empty_obligation_fails_to_needs_review(self):
        base = load_scenario(Path("scenarios/development/M-02.yaml"))
        payload = base.model_dump(mode="json")
        obligation = payload["obligations"][0]
        for field in [
            "required_meaning",
            "required_formula",
            "accepted_units",
            "accepted_scales",
            "min_window_days",
            "accepted_identity_scopes",
            "allowed_sources",
            "required_purposes",
        ]:
            obligation[field] = [] if field in {
                "accepted_units",
                "accepted_scales",
                "accepted_identity_scopes",
                "allowed_sources",
                "required_purposes",
            } else None
        scenario = type(base).model_validate(payload)
        result = self.engine.run(scenario, ValidationMode.V2, run_id="test")
        self.assertEqual(result.decision, Decision.NEEDS_REVIEW)
        self.assertEqual(result.reason_codes, ["V2_EMPTY_OBLIGATION"])

    def test_schema_break_is_rejected_by_every_mode(self):
        scenario = load_scenario(Path("scenarios/development/M-02.yaml"))
        scenario.new_contract.schema_fields.pop("gross_spend")
        for mode in ValidationMode:
            with self.subTest(mode=mode):
                self.assertEqual(
                    self.engine.run(scenario, mode, run_id="test").decision,
                    Decision.REJECT,
                )


if __name__ == "__main__":
    unittest.main()
