"""Autonomy is explicit delegation, not absence of human clicks."""
from dataclasses import FrozenInstanceError, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import unittest

from change_completion.action_policy import (
    ActionClass, ActionRequest, EffectQualification, Mandate, ScopedApproval, evaluate_action,
)
from change_completion.models import Action, AuthorityGrant, TransitionSpec
from change_completion.verification import context_digest

NOW = datetime(2026, 10, 16, 18, tzinfo=timezone.utc)
DIGEST = "a" * 64
ROOT = Path(__file__).resolve().parents[2] / "examples/product/execution"


class ActionPolicyTest(unittest.TestCase):
    def setUp(self):
        self.spec = TransitionSpec.model_validate_json((ROOT / "transition.json").read_bytes())
        self.spec = self.spec.model_copy(update={"allowed_actions": tuple(Action), "unknowns": ()})
        self.request = ActionRequest("worker", Action.PUBLISH_PR, frozenset({"analytics"}),
                                     self.spec.environment, context_digest(self.spec), NOW, True, package_sha256=DIGEST, executor_version="executor/1")
        self.grant = AuthorityGrant(grant_id="g", actor="worker", issued_by="operator",
            component_ids=("analytics", "audit"), actions=tuple(Action),
            environment=self.spec.environment, starts_at=NOW-timedelta(days=1),
            expires_at=NOW+timedelta(days=1), basis=self.spec.before)
        self.mandate = Mandate((self.grant,), frozenset({"operator"}),
                               effect_qualifications=tuple(EffectQualification("sqlite-select/1", action,
                                    self.spec.environment, "executor/1", "c"*64)
                                    for action in (Action.DEPLOY, Action.RETIRE)))

    def decide(self, **changes):
        changes.setdefault("context_sha256", context_digest(self.spec))
        return evaluate_action(self.spec, replace(self.request, **changes), self.mandate)

    def approval(self, actor, scope=("analytics",), **changes):
        item = ScopedApproval(actor, Action.DEPLOY, frozenset(scope), context_digest(self.spec),
                              NOW-timedelta(hours=1), NOW+timedelta(hours=1), package_sha256=DIGEST)
        return replace(item, **changes)

    def test_c3_pr_and_notification_are_not_deployment(self):
        self.spec = self.spec.model_copy(update={"criticality": 3, "unknowns": ("owner unknown",)})
        self.assertTrue(self.decide().allowed)
        self.assertEqual(self.decide().action_class, ActionClass.PROPOSE)
        self.assertTrue(self.decide(action=Action.NOTIFY, evidence_current=False).allowed)
        self.assertFalse(self.decide(action=Action.DEPLOY).allowed)

    def test_authority_does_not_come_from_candidate_spec(self):
        self.spec = self.spec.model_copy(update={"grants": (self.grant,)})
        self.assertFalse(evaluate_action(self.spec, self.request, Mandate()).allowed)
        self.mandate = replace(self.mandate, trusted_issuers=frozenset({"someone-else"}))
        self.assertIn("live_authority_missing", self.decide().reason_codes)

    def test_expiry_revocation_actor_environment_and_scope(self):
        for change in ({"at": self.grant.expires_at}, {"actor": "other"},
                       {"environment": "production"}, {"component_ids": frozenset({"events"})}):
            with self.subTest(change=change):
                self.assertFalse(self.decide(**change).allowed)
        self.mandate = replace(self.mandate, revoked_grant_ids=frozenset({"g"}))
        self.assertFalse(self.decide().allowed)

    def test_invalid_request_fails_closed(self):
        for change in ({"component_ids": frozenset()}, {"component_ids": frozenset({"outside"})},
                       {"at": NOW.replace(tzinfo=None)}, {"context_sha256": "bad"},
                       {"action": "deploy"}, {"action": "merge"}):
            with self.subTest(change=change):
                self.assertFalse(self.decide(**change).allowed)

    def test_allowed_actions_is_a_ceiling_not_a_grant(self):
        self.spec = self.spec.model_copy(update={"allowed_actions": (Action.DISCOVER,)})
        self.assertIn("action_not_delegated", self.decide().reason_codes)

    def test_c2_only_affected_owners_and_acceptor(self):
        approvals = (self.approval("analytics-owner"), self.approval(self.spec.acceptor))
        decision = self.decide(action=Action.DEPLOY, approvals=approvals)
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.required_approvers, frozenset({"analytics-owner", self.spec.acceptor}))
        self.assertNotIn("audit-owner", decision.required_approvers)

    def test_multicomponent_owners_approve_own_scope(self):
        scopes = frozenset({"analytics", "audit"})
        approvals = (self.approval("analytics-owner"), self.approval("audit-owner", ("audit",)),
                     self.approval(self.spec.acceptor, scopes))
        self.assertTrue(self.decide(action=Action.DEPLOY, component_ids=scopes, approvals=approvals).allowed)
        self.assertFalse(self.decide(action=Action.DEPLOY, component_ids=scopes, approvals=approvals[:-1]).allowed)

    def test_approval_cannot_be_reused_after_context_expiry_scope_or_action_change(self):
        good = self.approval("analytics-owner")
        acceptor = self.approval(self.spec.acceptor)
        for bad in (replace(good, context_sha256="b"*64), replace(good, expires_at=NOW),
                    replace(good, component_ids=frozenset({"audit"})), replace(good, action=Action.RETIRE)):
            self.assertFalse(self.decide(action=Action.DEPLOY, approvals=(bad, acceptor)).allowed)

    def test_c3_additional_risk_acceptance(self):
        self.spec = self.spec.model_copy(update={"criticality": 3})
        approvals = (self.approval("analytics-owner"), self.approval(self.spec.acceptor))
        self.assertIn("risk_approval_missing", self.decide(action=Action.DEPLOY, approvals=approvals).reason_codes)
        self.mandate = replace(self.mandate, risk_approvers=frozenset({"risk-officer"}))
        self.assertTrue(self.decide(action=Action.DEPLOY,
            approvals=approvals+(self.approval("risk-officer"),)).allowed)

    def test_low_risk_automation_still_requires_current_evidence_and_authority(self):
        self.spec = self.spec.model_copy(update={"criticality": 1})
        self.assertTrue(self.decide(action=Action.DEPLOY).allowed)
        self.assertFalse(self.decide(action=Action.DEPLOY, evidence_current=False).allowed)
        self.mandate = Mandate()
        self.assertFalse(self.decide(action=Action.DEPLOY).allowed)

    def test_unknowns_block_effects_and_worker_cannot_self_approve(self):
        self.spec = self.spec.model_copy(update={"unknowns": ("unresolved",), "criticality": 1})
        self.assertIn("unresolved_impact", self.decide(action=Action.RETIRE).reason_codes)
        self.assertTrue(self.decide(action=Action.PATCH, evidence_current=False).allowed)
        self.spec = self.spec.model_copy(update={"unknowns": (), "criticality": 2, "acceptor": "worker"})
        approvals = (self.approval("analytics-owner"), self.approval("worker"))
        self.assertFalse(self.decide(action=Action.DEPLOY, approvals=approvals).allowed)

    def test_request_identity_cannot_be_mutated(self):
        with self.assertRaises(FrozenInstanceError):
            self.request.actor = "admin"

    def test_spec_context_and_unknown_impact_fail_closed(self):
        self.assertIn("context_mismatch", self.decide(context_sha256="b"*64).reason_codes)
        self.spec = self.spec.model_copy(update={"impact": "unknown", "criticality": 1})
        self.assertIn("unresolved_impact", self.decide(action=Action.DEPLOY).reason_codes)

    def test_effect_execution_profiles_are_not_qualified_by_default(self):
        self.spec = self.spec.model_copy(update={"criticality": 1})
        self.mandate = replace(self.mandate, effect_qualifications=())
        self.assertIn("effect_profile_unqualified", self.decide(action=Action.DEPLOY).reason_codes)
        self.assertTrue(self.decide().allowed)

    def test_mutable_constructor_inputs_are_defensively_copied(self):
        components = {"analytics"}
        request = replace(self.request, component_ids=components)
        components.add("events")
        self.assertEqual(request.component_ids, frozenset({"analytics"}))
        issuers = {"operator"}
        mandate = Mandate([self.grant], issuers)
        issuers.clear()
        self.assertEqual(mandate.trusted_issuers, frozenset({"operator"}))

    def test_candidate_swap_invalidates_same_spec_approvals(self):
        approvals = (self.approval("analytics-owner"), self.approval(self.spec.acceptor))
        self.assertTrue(self.decide(action=Action.DEPLOY, approvals=approvals).allowed)
        swapped = self.decide(action=Action.DEPLOY, approvals=approvals, package_sha256="b"*64)
        self.assertFalse(swapped.allowed)
        self.assertIn("affected_human_approval_missing", swapped.reason_codes)
        missing = self.decide(action=Action.DEPLOY, approvals=approvals, package_sha256=None)
        self.assertIn("current_package_required", missing.reason_codes)
        legacy = tuple(replace(approval, package_sha256=None) for approval in approvals)
        self.assertFalse(self.decide(action=Action.DEPLOY, approvals=legacy).allowed)

    def test_proposal_api_remains_compatible_without_package(self):
        self.assertTrue(self.decide(package_sha256=None).allowed)
        self.assertTrue(self.decide(action=Action.NOTIFY, evidence_current=False, package_sha256=None).allowed)

    def test_effect_qualification_binds_action_environment_version_and_record(self):
        self.spec = self.spec.model_copy(update={"criticality": 1})
        qualification = self.mandate.effect_qualifications[0]
        for bad in (replace(qualification, action=Action.RETIRE),
                    replace(qualification, environment="another"),
                    replace(qualification, executor_version="executor/2"),
                    replace(qualification, record_sha256="bad")):
            self.mandate = replace(self.mandate, effect_qualifications=(bad,))
            self.assertIn("effect_profile_unqualified", self.decide(action=Action.DEPLOY).reason_codes)

    def test_c3_risk_approver_is_an_additional_independent_person(self):
        self.spec = self.spec.model_copy(update={"criticality": 3})
        approvals = (self.approval("analytics-owner"), self.approval(self.spec.acceptor))
        self.mandate = replace(self.mandate, risk_approvers=frozenset({"analytics-owner", self.spec.acceptor, "worker"}))
        self.assertIn("risk_approval_missing", self.decide(action=Action.DEPLOY, approvals=approvals).reason_codes)
