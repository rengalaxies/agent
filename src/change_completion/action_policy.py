"""Pure scoped authorization; callers load mandates/evidence from trusted state.

Does not derive authority from code, create approvals, execute effects or prove
business correctness. Remote effects require an immediate caller-side recheck.
"""
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType

from .models import Action, AuthorityGrant, TransitionSpec
from .verification import context_digest


class ActionClass(StrEnum):
    READ = "read"
    PREPARE = "prepare"
    PROPOSE = "propose"
    CONSEQUENTIAL = "consequential"


ACTION_CLASSES = MappingProxyType({
    Action.DISCOVER: ActionClass.READ,
    Action.VERIFY: ActionClass.READ,
    Action.PATCH: ActionClass.PREPARE,
    Action.EXPORT: ActionClass.PREPARE,
    Action.PUBLISH_PR: ActionClass.PROPOSE,
    Action.NOTIFY: ActionClass.PROPOSE,
    Action.DEPLOY: ActionClass.CONSEQUENTIAL,
    Action.RETIRE: ActionClass.CONSEQUENTIAL,
})


@dataclass(frozen=True)
class ScopedApproval:
    """Authenticated human approval of one action, scope and evidence context."""
    actor: str
    action: Action
    component_ids: frozenset[str]
    context_sha256: str
    starts_at: datetime
    expires_at: datetime
    package_sha256: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "component_ids", frozenset(self.component_ids))


@dataclass(frozen=True)
class EffectQualification:
    """Operator-approved executor qualification for one effect and environment."""
    profile: str
    action: Action
    environment: str
    executor_version: str
    record_sha256: str


@dataclass(frozen=True)
class Mandate:
    """Operator-controlled policy, never candidate repository instructions."""
    grants: tuple[AuthorityGrant, ...] = ()
    trusted_issuers: frozenset[str] = frozenset()
    revoked_grant_ids: frozenset[str] = frozenset()
    risk_approvers: frozenset[str] = frozenset()
    effect_qualifications: tuple[EffectQualification, ...] = ()

    def __post_init__(self):
        object.__setattr__(self, "grants", tuple(self.grants))
        object.__setattr__(self, "effect_qualifications", tuple(self.effect_qualifications))
        for name in ("trusted_issuers", "revoked_grant_ids", "risk_approvers"):
            object.__setattr__(self, name, frozenset(getattr(self, name)))


@dataclass(frozen=True)
class ActionRequest:
    actor: str
    action: Action
    component_ids: frozenset[str]
    environment: str
    context_sha256: str
    at: datetime
    evidence_current: bool = False
    approvals: tuple[ScopedApproval, ...] = ()
    package_sha256: str | None = None
    executor_version: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "component_ids", frozenset(self.component_ids))
        object.__setattr__(self, "approvals", tuple(self.approvals))


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    action_class: ActionClass | None
    reason_codes: tuple[str, ...]
    required_approvers: frozenset[str] = frozenset()


def _digest(value: str) -> bool:
    return (isinstance(value, str) and len(value) == 64
            and all(c in "0123456789abcdef" for c in value))


def _aware(value: datetime) -> bool:
    return isinstance(value, datetime) and value.utcoffset() is not None


def evaluate_action(spec: TransitionSpec, request: ActionRequest,
                    mandate: Mandate) -> PolicyDecision:
    """Deny by default; C2/C3 effects need only affected owners plus acceptor.

    Proposals never authorize merge/deploy. C3 effects additionally need a named
    risk approver separate from owners, acceptor and executor. Every tier needs an explicit live grant for every component.
    Unknown impact blocks effects, not discovery/preparation/proposals. PATCH
    means sandbox preparation only, never a write into a production repository.
    DEPLOY/RETIRE are denied unless affected profiles are explicitly qualified.
    Consequential approvals bind the exact candidate/evidence package, not only
    the transition spec. The caller computes this digest from trusted artifacts.
    """
    action_class = ACTION_CLASSES.get(request.action) if isinstance(request.action, Action) else None
    reasons = []
    required: set[str] = set()
    if not isinstance(request.action, Action) or action_class is None:
        return PolicyDecision(False, None, ("unsupported_action",))
    if (not request.actor or not request.environment or not _aware(request.at)
            or not _digest(request.context_sha256)
            or not isinstance(request.component_ids, frozenset)
            or not request.component_ids):
        return PolicyDecision(False, action_class, ("invalid_request",))
    if request.context_sha256 != context_digest(spec):
        return PolicyDecision(False, action_class, ("context_mismatch",))
    components = {c.component_id: c for c in spec.components}
    if not request.component_ids <= components.keys():
        return PolicyDecision(False, action_class, ("scope_outside_transition",))
    if request.environment != spec.environment:
        reasons.append("environment_mismatch")
    if request.action not in spec.allowed_actions:
        reasons.append("action_not_delegated")
    covered = set()
    for grant in mandate.grants:
        if (grant.actor == request.actor and grant.issued_by in mandate.trusted_issuers
                and grant.grant_id not in mandate.revoked_grant_ids
                and grant.environment == request.environment
                and request.action in grant.actions
                and grant.starts_at <= request.at < grant.expires_at):
            covered.update(grant.component_ids)
    if not request.component_ids <= covered:
        reasons.append("live_authority_missing")
    consequential = action_class == ActionClass.CONSEQUENTIAL
    if consequential or request.action in (Action.PUBLISH_PR, Action.EXPORT):
        if request.evidence_current is not True:
            reasons.append("current_evidence_required")
    if consequential:
        if not _digest(request.package_sha256):
            reasons.append("current_package_required")
        qualified_profiles = {q.profile for q in mandate.effect_qualifications
            if isinstance(q.action, Action) and q.action == request.action
            and q.environment == request.environment and q.executor_version
            and q.executor_version == request.executor_version and _digest(q.record_sha256)}
        if any(components[c].profile not in qualified_profiles for c in request.component_ids):
            reasons.append("effect_profile_unqualified")
        if spec.impact == "unknown" or spec.unknowns or any(e.certainty != "observed" and
                               (e.source in request.component_ids or e.target in request.component_ids)
                               for e in spec.dependencies):
            reasons.append("unresolved_impact")
        if spec.criticality >= 2:
            required.update(components[c].owner for c in request.component_ids)
            required.add(spec.acceptor)
        valid_approvals = tuple(approval for approval in request.approvals
            if (isinstance(approval.action, Action) and approval.action == request.action
                and _aware(approval.starts_at) and _aware(approval.expires_at)
                and approval.starts_at <= request.at < approval.expires_at
                and approval.context_sha256 == request.context_sha256
                and _digest(approval.package_sha256)
                and approval.package_sha256 == request.package_sha256
                and isinstance(approval.component_ids, frozenset)
                and approval.actor != request.actor))

        def approved(actor, scope):
            covered_scope = set()
            for approval in valid_approvals:
                if approval.actor == actor:
                    covered_scope.update(approval.component_ids)
            return scope <= covered_scope

        missing = False
        for actor in required:
            scope = (request.component_ids if actor == spec.acceptor else
                     frozenset(c for c in request.component_ids if components[c].owner == actor))
            if not approved(actor, scope):
                missing = True
        if missing:
            reasons.append("affected_human_approval_missing")
        if spec.criticality == 3:
            distinct_risk_actors = mandate.risk_approvers - required - {request.actor}
            if not any(approved(actor, request.component_ids) for actor in distinct_risk_actors):
                reasons.append("risk_approval_missing")
    return PolicyDecision(not reasons, action_class, tuple(reasons), frozenset(required))
