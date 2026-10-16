"""Independent attacks on observation binding and suite completeness.

These fixtures are not proof that captured observations came from execution.
"""
import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from change_completion.models import Action, AuthorityGrant, ContentRef, TransitionSpec
from change_completion.verification import (
    TrustPolicy, context_digest, digest_bytes, verify_observations,
)

NOW = datetime(2026, 10, 16, 14, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


def wire(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def valid_case_data():
    """Return spec, candidate, mutable suite/observations, trusted policy.

    Explicit owner examples precede candidate creation. External trust policy
    pins exact bytes rather than accepting candidate-supplied approval claims.
    """
    data = json.loads((ROOT / "examples/product/service-event.json").read_text())
    data["unknowns"] = []
    spec = TransitionSpec.model_validate(data)
    candidate = ContentRef(uri="candidate://patch", sha256="9" * 64)
    table = {"columns": [{"name": "amount", "kind": "int"}], "rows": [[100], [200]]}
    suite = {
        "format": "independent-expectations/1", "transition_id": spec.transition_id,
        "context_sha256": context_digest(spec), "approved_by": "business-owner",
        "origin": "owner_examples", "prepared_at": (NOW - timedelta(hours=2)).isoformat(),
        "valid_until": (NOW + timedelta(hours=1)).isoformat(),
        "required_tags": ["nonempty", "empty"],
        "cases": [
            {"case_id": "populated", "requirement_ids": ["r1"],
             "fixture": {"uri": "fixture://populated", "sha256": "a" * 64},
             "input_records": 2, "tags": ["nonempty"], "expected": copy.deepcopy(table)},
            {"case_id": "empty", "requirement_ids": ["r1"],
             "fixture": {"uri": "fixture://empty", "sha256": "b" * 64},
             "input_records": 0, "tags": ["empty"],
             "expected": {"columns": table["columns"], "rows": []}},
        ],
    }
    observations = {
        "format": "captured-observations/1", "transition_id": spec.transition_id,
        "context_sha256": context_digest(spec), "candidate_sha256": candidate.sha256,
        "suite_sha256": digest_bytes(wire(suite)),
        "candidate_created_at": (NOW - timedelta(hours=1)).isoformat(),
        "captured_at": (NOW - timedelta(minutes=5)).isoformat(),
        "cases": [{"case_id": c["case_id"], "fixture": copy.deepcopy(c["fixture"]),
                   "status": "executed", "actual": copy.deepcopy(c["expected"])}
                  for c in suite["cases"]],
    }
    grant = AuthorityGrant(grant_id="trusted-verify", actor="worker", issued_by="deployment-owner",
                           component_ids=spec.consumers, actions=(Action.VERIFY,),
                           environment=spec.environment, starts_at=NOW - timedelta(days=1),
                           expires_at=NOW + timedelta(days=1), basis=spec.before)
    policy = TrustPolicy(frozenset({digest_bytes(wire(suite))}), frozenset({"business-owner"}), (grant,))
    return spec, candidate, suite, observations, policy


class VerificationAdversarialTest(unittest.TestCase):
    def setUp(self):
        self.spec, self.candidate, self.suite, self.observations, self.policy = valid_case_data()

    def run_gate(self, *, at=NOW, actor="worker"):
        return verify_observations(self.spec, self.candidate, wire(self.suite),
                                   wire(self.observations), self.policy, at=at, actor=actor)

    def repin_suite(self):
        """Only tests simulating explicit deployment approval may use this."""
        digest = digest_bytes(wire(self.suite))
        self.observations["suite_sha256"] = digest
        self.policy = TrustPolicy(frozenset({digest}), self.policy.approved_owners, self.policy.grants)

    def test_positive_reports_no_effect_or_execution_attestation(self):
        report = self.run_gate()
        self.assertEqual(report.status, "PASS")
        self.assertFalse(report.effects_authorized)
        self.assertEqual(report.scope, "provided_observations_only")

    def test_unapproved_candidate_supplied_expectations_cannot_replace_owner_examples(self):
        self.suite["cases"][0]["expected"]["rows"] = [[999]]
        self.observations["cases"][0]["actual"]["rows"] = [[999]]
        self.observations["suite_sha256"] = digest_bytes(wire(self.suite))
        self.assertIn("UNAPPROVED_EXPECTATIONS", self.run_gate().reason_codes)

    def test_each_binding_substitution_stops(self):
        for field in ("context_sha256", "candidate_sha256", "suite_sha256"):
            with self.subTest(field=field):
                original = self.observations[field]
                self.observations[field] = "0" * 64
                self.assertEqual(self.run_gate().status, "STOP")
                self.observations[field] = original
        self.observations["transition_id"] = "different-transition"
        self.assertEqual(self.run_gate().status, "STOP")

    def test_changed_requirement_invalidates_old_observations(self):
        data = self.spec.model_dump(mode="json")
        data["requirements"][0]["expectation"] = "new approved business meaning"
        self.spec = TransitionSpec.model_validate(data)
        self.assertIn("STALE_CONTEXT", self.run_gate().reason_codes)

    def test_missing_duplicate_unknown_or_empty_case_set_stops(self):
        original = copy.deepcopy(self.observations["cases"])
        for cases in (original[:1], [original[0], original[0]], [],
                      [original[0], {**original[1], "case_id": "unrequested"}]):
            self.observations["cases"] = cases
            self.assertEqual(self.run_gate().status, "STOP")

    def test_fixture_hash_or_identity_substitution_stops(self):
        for key, replacement in (("sha256", "0" * 64), ("uri", "fixture://other")):
            with self.subTest(key=key):
                fixture = self.observations["cases"][0]["fixture"]
                original = fixture[key]
                fixture[key] = replacement
                self.assertEqual(self.run_gate().status, "STOP")
                fixture[key] = original

    def test_future_capture_nonindependence_and_expiry_boundary(self):
        for field, value in (
            ("captured_at", NOW + timedelta(seconds=1)),
            ("candidate_created_at", NOW - timedelta(hours=3)),
            ("candidate_created_at", NOW - timedelta(hours=2)),
            ("captured_at", NOW - timedelta(hours=2)),
        ):
            original = self.observations[field]
            self.observations[field] = value.isoformat()
            self.assertEqual(self.run_gate().status, "STOP")
            self.observations[field] = original
        self.assertEqual(self.run_gate(at=NOW + timedelta(hours=1)).status, "STOP")

    def test_current_policy_revocation_and_wrong_actor_stop(self):
        self.assertEqual(self.run_gate(actor="other-worker").status, "STOP")
        self.policy = TrustPolicy(self.policy.approved_suite_digests, self.policy.approved_owners,
                                  self.policy.grants, frozenset({"trusted-verify"}))
        self.assertIn("VERIFY_AUTHORITY_UNAVAILABLE", self.run_gate().reason_codes)

    def test_grant_expiry_without_any_new_observation_stops(self):
        grant = self.policy.grants[0].model_copy(update={"expires_at": NOW})
        self.policy = TrustPolicy(self.policy.approved_suite_digests, self.policy.approved_owners, (grant,))
        self.assertEqual(self.run_gate().status, "STOP")

    def test_incomplete_execution_never_passes(self):
        for status in ("error", "timeout", "unsupported"):
            self.observations["cases"][0]["status"] = status
            self.assertEqual(self.run_gate().status, "STOP")
        self.observations["cases"][0]["status"] = "executed"
        self.observations["cases"][0]["actual"] = None
        self.assertEqual(self.run_gate().status, "STOP")

    def test_discrepancy_is_not_hidden_by_other_case_error(self):
        self.observations["cases"][0]["actual"]["rows"] = [[100], [999]]
        self.observations["cases"][1]["status"] = "error"
        self.assertEqual(self.run_gate().status, "FAIL")

    def test_approved_but_empty_or_missing_requirement_coverage_stops(self):
        for c in self.suite["cases"]:
            c["input_records"] = 0
        self.repin_suite()
        self.assertIn("ONLY_EMPTY_INPUTS", self.run_gate().reason_codes)
        self.suite["cases"][0]["input_records"] = 2
        for c in self.suite["cases"]:
            c["requirement_ids"] = ["unrequested-requirement"]
        self.repin_suite()
        self.assertIn("REQUIREMENT_COVERAGE_MISMATCH", self.run_gate().reason_codes)

    def test_required_case_tag_coverage_stops(self):
        self.suite["required_tags"].append("rounding-boundary")
        self.repin_suite()
        self.assertIn("MISSING_REQUIRED_CASE_TAGS", self.run_gate().reason_codes)

    def test_second_consumer_cannot_disappear_from_coverage(self):
        data = self.spec.model_dump(mode="json")
        component = copy.deepcopy(data["components"][1])
        component["component_id"] = "second-consumer"
        data["components"].append(component)
        data["consumers"].append("second-consumer")
        requirement = copy.deepcopy(data["requirements"][0])
        requirement.update(requirement_id="r2", consumer_id="second-consumer")
        data["requirements"].append(requirement)
        self.spec = TransitionSpec.model_validate(data)
        self.suite["context_sha256"] = context_digest(self.spec)
        self.observations["context_sha256"] = context_digest(self.spec)
        grant = self.policy.grants[0].model_copy(update={"component_ids": self.spec.consumers})
        self.policy = TrustPolicy(self.policy.approved_suite_digests, self.policy.approved_owners, (grant,))
        self.repin_suite()
        self.assertIn("REQUIREMENT_COVERAGE_MISMATCH", self.run_gate().reason_codes)

    def test_spec_supplied_grants_do_not_replace_deployment_authority(self):
        data = self.spec.model_dump(mode="json")
        data["grants"] = [g.model_dump(mode="json") for g in self.policy.grants]
        self.spec = TransitionSpec.model_validate(data)
        self.suite["context_sha256"] = context_digest(self.spec)
        self.observations["context_sha256"] = context_digest(self.spec)
        self.policy = TrustPolicy(self.policy.approved_suite_digests, self.policy.approved_owners, ())
        self.repin_suite()
        self.assertIn("VERIFY_AUTHORITY_UNAVAILABLE", self.run_gate().reason_codes)

    def test_owner_claim_without_owner_allowlist_is_not_approval(self):
        self.policy = TrustPolicy(self.policy.approved_suite_digests, frozenset(), self.policy.grants)
        self.assertIn("UNAPPROVED_OWNER", self.run_gate().reason_codes)

    def test_candidate_cannot_supply_a_pass_or_expected_field(self):
        self.observations["cases"][0]["status"] = "PASS"
        self.assertEqual(self.run_gate().status, "STOP")
        self.observations["cases"][0]["status"] = "executed"
        self.observations["cases"][0]["expected"] = self.suite["cases"][0]["expected"]
        self.assertEqual(self.run_gate().status, "STOP")

    def test_duplicate_json_keys_rejected_even_when_pinned(self):
        payload = b'{"format":"independent-expectations/1","format":"independent-expectations/1"}'
        policy = TrustPolicy(frozenset({digest_bytes(payload)}), self.policy.approved_owners, self.policy.grants)
        report = verify_observations(self.spec, self.candidate, payload, wire(self.observations),
                                     policy, at=NOW, actor="worker")
        self.assertEqual(report.status, "STOP")
        self.assertIn("INVALID_BUNDLE", report.reason_codes)


if __name__ == "__main__":
    unittest.main()
