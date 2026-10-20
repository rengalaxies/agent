"""Package 1: declarative boundaries, not a runtime permission or safety engine."""
from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Action(StrEnum):
    DISCOVER = "discover"
    PATCH = "patch"
    VERIFY = "verify"
    EXPORT = "export"
    PUBLISH_PR = "publish_pr"
    NOTIFY = "notify"
    DEPLOY = "deploy"
    RETIRE = "retire"


class ContentRef(Contract):
    uri: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Component(Contract):
    component_id: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    profile: str = Field(min_length=1)
    artifacts: tuple[ContentRef, ...] = Field(min_length=1)


class Requirement(Contract):
    requirement_id: str = Field(min_length=1)
    consumer_id: str = Field(min_length=1)
    expectation: str = Field(min_length=1)
    basis: ContentRef
    approved_by: str = Field(min_length=1)


class Dependency(Contract):
    source: str
    target: str
    certainty: str = Field(pattern=r"^(observed|inferred|unknown)$")
    basis: ContentRef | None = None

    @model_validator(mode="after")
    def observed_needs_source(self):
        if self.certainty == "observed" and self.basis is None:
            raise ValueError("observed dependency requires a source")
        return self


class Capability(Contract):
    action: Action
    artifact_kind: str = Field(min_length=1)
    profile: str = Field(min_length=1)


class CapabilityNeed(Contract):
    component_id: str
    capability: Capability


class AdapterDeclaration(Contract):
    adapter_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    status: str = Field(pattern=r"^(planned|experimental|qualified)$")
    capabilities: tuple[Capability, ...] = Field(min_length=1)
    limits: tuple[str, ...] = Field(min_length=1)
    qualification: ContentRef | None = None

    @model_validator(mode="after")
    def qualified_needs_record(self):
        if self.status == "qualified" and self.qualification is None:
            raise ValueError("qualified declaration requires a qualification record")
        return self


class AuthorityGrant(Contract):
    grant_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    issued_by: str = Field(min_length=1)
    component_ids: tuple[str, ...] = Field(min_length=1)
    actions: tuple[Action, ...] = Field(min_length=1)
    environment: str = Field(min_length=1)
    starts_at: datetime
    expires_at: datetime
    basis: ContentRef

    @model_validator(mode="after")
    def explicit_timezone(self):
        if self.expires_at.utcoffset() is None or self.starts_at.utcoffset() is None:
            raise ValueError("grant interval requires timezones")
        if self.expires_at <= self.starts_at:
            raise ValueError("grant interval must be positive")
        return self


class TransitionSpec(Contract):
    schema_version: str = Field(default="change-completion/1", pattern=r"^change-completion/1$")
    transition_id: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    owner: str = Field(min_length=1)
    acceptor: str = Field(min_length=1)
    environment: str = Field(min_length=1)
    criticality: int = Field(ge=0, le=3)
    impact: Literal["unknown", "documentation", "local", "contract", "cross_system"] = "unknown"
    critical_risks: tuple[str, ...] = ()
    before: ContentRef
    target: ContentRef
    components: tuple[Component, ...] = Field(min_length=1)
    consumers: tuple[str, ...] = Field(min_length=1)
    requirements: tuple[Requirement, ...] = Field(min_length=1)
    dependencies: tuple[Dependency, ...] = ()
    unknowns: tuple[str, ...] = ()
    needs: tuple[CapabilityNeed, ...] = Field(min_length=1)
    grants: tuple[AuthorityGrant, ...] = ()
    allowed_actions: tuple[Action, ...] = ()
    completion_criteria: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def coherent_scope(self):
        ids = [c.component_id for c in self.components]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate component_id")
        if len(self.consumers) != len(set(self.consumers)) or not set(self.consumers) <= set(ids):
            raise ValueError("consumers must be distinct components in scope")
        req_ids = [r.requirement_id for r in self.requirements]
        if len(req_ids) != len(set(req_ids)):
            raise ValueError("duplicate requirement_id")
        if {r.consumer_id for r in self.requirements} != set(self.consumers):
            raise ValueError("each consumer requires its own approved requirements")
        for edge in self.dependencies:
            if edge.source not in ids or edge.target not in ids:
                raise ValueError("dependency outside declared scope")
        owners = {c.component_id: c.owner for c in self.components}
        if self.criticality < 2 and any(owners[e.source] != owners[e.target] for e in self.dependencies):
            raise ValueError("cross-team dependencies require at least C2")
        for need in self.needs:
            component = next((c for c in self.components if c.component_id == need.component_id), None)
            if component is None or component.profile != need.capability.profile:
                raise ValueError("capability must match component and exact profile")
        for grant in self.grants:
            if not set(grant.component_ids) <= set(ids):
                raise ValueError("grant component outside scope")
        if self.critical_risks and self.criticality != 3:
            raise ValueError("declared critical risks require C3")
        if self.impact in ("contract", "cross_system") and self.criticality < 2:
            raise ValueError("contract or cross-system impact requires at least C2")
        if self.criticality == 0 and (self.unknowns or self.impact == "unknown"
                                     or any(e.certainty != "observed" for e in self.dependencies)):
            raise ValueError("unknown impact cannot be C0")
        return self


class EvidenceBinding(Contract):
    """Version/freshness binding only; this does not establish a test's truth."""
    transition_id: str
    context: ContentRef  # Digest of code, contracts, requirements, policy and profiles.
    check: ContentRef
    result: ContentRef
    checked_at: datetime
    valid_until: datetime

    @model_validator(mode="after")
    def valid_interval(self):
        if self.checked_at.utcoffset() is None or self.valid_until.utcoffset() is None:
            raise ValueError("evidence timestamps require timezone")
        if self.valid_until <= self.checked_at:
            raise ValueError("evidence interval must be positive")
        return self

    def matches(self, transition_id: str, context: ContentRef, check: ContentRef, at: datetime) -> bool:
        if at.utcoffset() is None:
            raise ValueError("evidence lookup requires timezone")
        return (self.transition_id == transition_id and self.context == context and self.check == check
                and self.checked_at <= at < self.valid_until)


class JournalEvent(Contract):
    """Event format; persistence, append-only storage and deduplication come later."""
    event_id: str = Field(min_length=1)
    transition_id: str = Field(min_length=1)
    actor: str = Field(min_length=1)
    at: datetime
    action: str = Field(min_length=1)
    basis: ContentRef
    supersedes: str | None = None

    @model_validator(mode="after")
    def timezone_and_identity(self):
        if self.at.utcoffset() is None or self.supersedes == self.event_id:
            raise ValueError("event needs timezone and cannot supersede itself")
        return self
