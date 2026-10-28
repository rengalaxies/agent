"""Versioned public contracts shared by the core, the service and later batches.

agent-graph-output 2.x. JSON Schema (schemas/agent-graph-output-2.json) covers the
structure; semantic rules below (status/reason pairs, fact backing, references)
are enforced only by this module. Readers reject an unknown major version, a
newer minor version and any unknown code: nothing unknown is displayed as a
useful (green) result. USEFUL is the service's preliminary classification, not
a confirmed benefit to a team.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import ConfigDict, Field, TypeAdapter, ValidationError, model_validator

from .contracts import GraphError, Strict, digest

SCHEMA_ID = "agent-graph-output"
SCHEMA_MAJOR = 2
# 2.1 (batch 3): runtime freshness/unknown/gap codes and Claim.subject. Additive only.
SCHEMA_MINOR = 1
SCHEMA_VERSION = f"{SCHEMA_MAJOR}.{SCHEMA_MINOR}"

Timestamp = Annotated[str, Field(
    pattern=r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d{1,9})?(Z|[+-]\d{2}:\d{2})$")]
CommitSha = Annotated[str, Field(pattern=r"^([0-9a-f]{40}|[0-9a-f]{64})$")]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
Name = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.-]{1,80}$")]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_.:/-]{1,200}$")]
Method = Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
Text = Annotated[str, Field(min_length=1, max_length=4000)]

ResultStatus = Literal["USEFUL", "PARTIAL", "ABSTAINED", "FAILED", "SUPERSEDED"]

# Allowed reason codes per status. A reason from another status is a contract error.
REASONS: dict[str, frozenset[str]] = {
    "USEFUL": frozenset({"impact_found_within_profile", "preliminary_impact_found"}),
    "PARTIAL": frozenset({
        "coverage_gaps", "source_stale", "runtime_unavailable", "model_unavailable",
        "model_step_limit", "deadline_reached", "unclassified_change", "owner_unknown",
        "budget_exhausted", "hypotheses_only"}),
    "ABSTAINED": frozenset({
        "insufficient_evidence", "no_supported_delta", "intent_unclear", "out_of_scope",
        "no_consumer_found_within_profile"}),
    "FAILED": frozenset({
        "source_unavailable", "commit_unavailable", "repository_not_allowed",
        "invalid_model_action", "model_transport_error", "incompatible_contract",
        "forbidden", "cancelled", "deadline_exceeded", "budget_exhausted", "internal_error"}),
    "SUPERSEDED": frozenset({"newer_resource_version", "newer_head", "newer_request"}),
}
ReasonCode = Literal[tuple(sorted(set().union(*REASONS.values())))]

DeltaCode = Literal[
    "OPERATION_REMOVED", "PAGE_DEFAULT_CHANGED", "PAGE_DEFAULT_UNRESOLVED",
    "UNCLASSIFIED_OPERATION_CHANGE"]
FindingCode = Literal[
    "POSSIBLE_TRUNCATION", "OPERATION_REMOVED", "RECHECK_REQUIRED", "UNCLASSIFIED_CHANGE_RECHECK"]
UsageCode = Literal[
    "SINGLE_REQUEST_OBSERVED", "CURSOR_LOOP_OBSERVED", "EXPLICIT_PAGE_SIZE", "UNKNOWN_USAGE"]
GapCode = Literal[
    # Collection and pinned Git reads.
    "source_unavailable", "directory_unreadable", "symlink_directory_omitted", "symlink_omitted",
    "submodule_omitted", "lfs_pointer_omitted", "binary_omitted", "file_limit", "not_regular_source",
    "source_unreadable", "sensitive_source", "invalid_source_path", "commit_unavailable",
    "object_unavailable",
    # Providers.
    "openapi_ref_unsupported", "page_size_default_unresolved", "invalid_contract",
    "python_parse_error", "provider_route_unsupported", "provider_declaration_conflict",
    # Consumers. Each one is a real possible call outside the grammar, never a skipped file.
    "unknown_http_client", "dynamic_or_unsupported_call", "unsupported_url", "ambiguous_mapping",
    "unmapped_call", "dynamic_parameters",
    # Requirements and other bases.
    "requirement_basis_stale", "runtime_source_unavailable", "ownership_source_unavailable",
    "runtime_window_gap"]
UnknownCode = Literal[
    "requirement_unknown", "owner_unknown", "owner_conflict", "jira_without_diff",
    "unclassified_change", "helper_semantics_unknown", "runtime_not_observed",
    "runtime_window_gap", "result_set_size_unknown", "model_hypothesis_unverified",
    "runtime_not_instrumented", "runtime_route_not_recorded", "runtime_route_conflict"]
FreshnessReason = Literal[
    "basis_changed", "age_exceeded", "partial_coverage", "current_corpus_unavailable",
    "proposal_basis_differs", "source_unavailable", "no_traffic_in_window", "sampled_source",
    "window_gap", "worktree_not_reproducible", "not_instrumented", "route_not_recorded", "route_conflict"]

EvidenceOrigin = Literal["code", "runtime", "model_hypothesis", "correction", "external_report"]
Provenance = Literal["AUTHENTIC", "UNVERIFIED", "REJECTED"]
Sufficiency = Literal["SUPPORTED_WITHIN_PROFILE", "OBSERVED_WITHIN_WINDOW", "INSUFFICIENT",
                      "NOT_ASSESSED"]
FactSufficiency = frozenset({"SUPPORTED_WITHIN_PROFILE", "OBSERVED_WITHIN_WINDOW"})


class ContractError(GraphError):
    """Incompatible or invalid document. `errors` hold only field paths and error types."""

    def __init__(self, code: str, errors: list[dict] | None = None):
        super().__init__(code)
        self.errors = errors or []


def normalize_route(route: str) -> str:
    if not isinstance(route, str) or not route.startswith("/") or any(c in route for c in "?#"):
        raise ValueError("invalid_route")
    route = re.sub(r"/{2,}", "/", route)
    return route.rstrip("/") or "/"


class Freshness(Strict):
    status: Literal["CURRENT", "STALE", "UNKNOWN"]
    checked_at: Timestamp
    reasons: list[FreshnessReason] = Field(default_factory=list, max_length=16)
    valid_from: Timestamp | None = None
    valid_until: Timestamp | None = None


# Entities: identity includes installation and environment. Same names from another
# environment or service are different entities.
class ServiceEntity(Strict):
    kind: Literal["service"] = "service"
    installation_id: Name
    environment: Name
    service: Name


class OperationEntity(Strict):
    kind: Literal["operation"] = "operation"
    installation_id: Name
    environment: Name
    service: Name
    method: Method
    route: str = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def normalized(self):
        if normalize_route(self.route) != self.route:
            raise ValueError("route_not_normalized")
        return self


class CallsiteEntity(Strict):
    kind: Literal["callsite"] = "callsite"
    installation_id: Name
    environment: Name
    service: Name
    repository: Name
    path: str = Field(min_length=1, max_length=500)
    line: int = Field(ge=1)


class TeamEntity(Strict):
    kind: Literal["team"] = "team"
    installation_id: Name
    team: Name


Entity = Annotated[Union[ServiceEntity, OperationEntity, CallsiteEntity, TeamEntity],
                   Field(discriminator="kind")]


def entity_id(entity) -> str:
    """Stable identity. Operations keep the core's existing operation_id formula."""
    e = entity if not isinstance(entity, dict) else TypeAdapter(Entity).validate_python(entity)
    if e.kind == "operation":
        return digest([e.installation_id, e.environment, e.service, e.method, e.route])
    return digest(e.model_dump())


# Evidence: origin, provenance (was the text really read), sufficiency (does it
# support the claim) and freshness are separate fields, never one "verified" flag.
class _Evidence(Strict):
    id: Identifier
    provenance: Provenance
    sufficiency: Sufficiency
    freshness: Freshness
    visibility: list[Name] = Field(min_length=1, max_length=64,
                                   description="Repository/source ids a reader must be granted.")


class CodeEvidence(_Evidence):
    origin: Literal["code"] = "code"
    snapshot: Literal["GIT_COMMIT", "WORKTREE"]
    repository: Name
    commit: CommitSha | None
    blob: CommitSha | None
    content_sha256: Sha256
    path: str = Field(min_length=1, max_length=500)
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)

    @model_validator(mode="after")
    def pinned(self):
        if self.end_line < self.start_line:
            raise ValueError("invalid_range")
        if (self.snapshot == "GIT_COMMIT") != (self.commit is not None and self.blob is not None):
            raise ValueError("snapshot_identity_mismatch")
        if self.snapshot == "WORKTREE" and "worktree_not_reproducible" not in self.freshness.reasons:
            raise ValueError("worktree_must_be_marked")
        return self


class RuntimeAggregates(Strict):
    requests: int | None = Field(default=None, ge=0)
    errors: int | None = Field(default=None, ge=0)
    sampled: bool | None = None


class RuntimeEvidence(_Evidence):
    origin: Literal["runtime"] = "runtime"
    source: Name
    source_version: str | None = Field(default=None, max_length=200)
    consumer: ServiceEntity
    provider: ServiceEntity
    window_start: Timestamp
    window_end: Timestamp
    # Only when the source reports them; a service edge is not an API dependency.
    method: Method | None = None
    route: str | None = Field(default=None, max_length=500)
    aggregates: RuntimeAggregates | None = None


class HypothesisEvidence(_Evidence):
    origin: Literal["model_hypothesis"] = "model_hypothesis"
    model_configuration_id: Identifier
    supporting_refs: list[Identifier] = Field(max_length=16)
    unknowns: list[UnknownCode] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def never_sufficient(self):
        if self.sufficiency in FactSufficiency:
            raise ValueError("hypothesis_cannot_be_sufficient")
        return self


class CorrectionEvidence(_Evidence):
    origin: Literal["correction"] = "correction"
    correction_id: Identifier
    actor: Name


class ExternalReportEvidence(_Evidence):
    origin: Literal["external_report"] = "external_report"
    reporter: Name
    artifact_sha256: Sha256
    independently_verified: Literal[False] = False


Evidence = Annotated[Union[CodeEvidence, RuntimeEvidence, HypothesisEvidence, CorrectionEvidence,
                           ExternalReportEvidence], Field(discriminator="origin")]


class GraphRelationship(Strict):
    id: Identifier
    kind: Literal["declares", "calls", "owns", "may_affect"]
    source: Entity
    target: Entity
    status: Literal["ACTIVE", "STALE", "CONFLICT", "RETRACTED", "TOMBSTONED"]
    origins: list[EvidenceOrigin] = Field(min_length=1, max_length=5)
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=64)
    freshness: Freshness
    change_origin: Literal["code_scan", "runtime_sync", "ownership_sync", "model_proposal",
                           "correction", "migration"]
    visibility: list[Name] = Field(min_length=1, max_length=64)


class Owner(Strict):
    """A named team is an addressee, never an approver. Unknown owners stay unknown."""
    status: Literal["KNOWN", "UNKNOWN", "CONFLICT"]
    teams: list[TeamEntity] = Field(max_length=8)
    source: Literal["service_catalog", "codeowners", "installation_mapping"] | None
    source_version: str | None = Field(default=None, max_length=200)
    checked_at: Timestamp | None = None

    @model_validator(mode="after")
    def consistent(self):
        expected = {"KNOWN": lambda n: n == 1, "UNKNOWN": lambda n: n == 0,
                    "CONFLICT": lambda n: n >= 2}[self.status]
        if not expected(len(self.teams)) or (self.status != "UNKNOWN" and self.source is None):
            raise ValueError("owner_status_mismatch")
        return self


# Request: the application's validated input to an analysis.
class JiraTrigger(Strict):
    project: Name
    key: Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9_]{0,30}-[1-9][0-9]{0,9}$")]
    revision: str = Field(min_length=1, max_length=100)
    updated_at: Timestamp
    # Untrusted text from configured fields only; it never grants authority.
    text_fields: dict[Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]{0,39}$")],
                      Annotated[str, Field(max_length=20000)]] = Field(max_length=8)


class PullRequestTrigger(Strict):
    provider: Literal["github"]
    repository: Name
    pr_id: int = Field(ge=1)
    base_sha: CommitSha
    head_sha: CommitSha


class SourceEvent(Strict):
    event_id: Identifier
    resource_version: str = Field(min_length=1, max_length=200)


class AccessScope(Strict):
    view_id: Sha256
    repositories: list[Name] = Field(min_length=1, max_length=64)
    runtime_sources: list[Name] = Field(default_factory=list, max_length=16)


VersionString = Annotated[str, Field(pattern=r"^(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})$")]


class _Document(Strict):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)
    schema_id: Literal["agent-graph-output"] = Field(default=SCHEMA_ID, alias="schema")
    schema_version: VersionString = SCHEMA_VERSION


class AnalysisRequest(_Document):
    kind: Literal["analysis_request"] = "analysis_request"
    installation_id: Name
    environment: Name
    request_id: Identifier
    trigger_kind: Literal["jira", "pr", "replay"]
    source_event: SourceEvent
    jira: JiraTrigger | None = None
    pr: PullRequestTrigger | None = None
    replay_of: Identifier | None = None
    repository_revisions: dict[Name, CommitSha] = Field(min_length=1, max_length=64)
    graph_version: Identifier
    constitution_version: Identifier
    model_configuration_id: Identifier | None
    deadline: Timestamp
    access_scope: AccessScope

    @model_validator(mode="after")
    def trigger(self):
        if self.trigger_kind == "jira" and (self.jira is None or self.pr is not None):
            raise ValueError("jira_trigger_mismatch")
        if self.trigger_kind == "pr":
            if self.pr is None:
                raise ValueError("pr_trigger_mismatch")
        if self.trigger_kind == "replay" and self.replay_of is None:
            raise ValueError("replay_requires_origin")
        if self.pr is not None and self.repository_revisions.get(self.pr.repository) != self.pr.head_sha:
            raise ValueError("pr_head_not_pinned")
        if not set(self.repository_revisions) <= set(self.access_scope.repositories):
            raise ValueError("repository_outside_scope")
        return self


# Result.
class SnapshotUse(Strict):
    repository: Name
    mode: Literal["GIT_COMMIT", "WORKTREE"]
    commit: CommitSha | None
    tree: CommitSha | None
    role: Literal["base", "head", "consumer"]

    @model_validator(mode="after")
    def pinned(self):
        if (self.mode == "GIT_COMMIT") != (self.commit is not None and self.tree is not None):
            raise ValueError("snapshot_identity_mismatch")
        return self


class Claim(Strict):
    id: Identifier
    kind: Literal["fact", "hypothesis"]
    statement: Text
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=32)
    applicability: Text
    uncertainty: Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]
    unknowns: list[UnknownCode] = Field(default_factory=list, max_length=16)
    # 2.1: what the claim is about. A fact about an operation needs evidence that
    # names that operation; a runtime service edge without a route does not.
    subject: Entity | None = None


class Delta(Strict):
    operation: OperationEntity
    code: DeltaCode
    before: int | str | None
    after: int | str | None
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=32)


class Finding(Strict):
    code: FindingCode
    consumer: ServiceEntity
    usage: UsageCode
    callsite: CallsiteEntity
    dependency_freshness: Literal["CURRENT", "STALE"]
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=32)
    requirement_ids: list[Identifier] = Field(default_factory=list, max_length=16)
    test_executed: Literal[False] = False
    compatibility_confirmed: Literal[False] = False


class Gap(Strict):
    code: GapCode
    repository: Name | None = None
    path: str | None = Field(default=None, max_length=500)
    evidence_refs: list[Identifier] = Field(default_factory=list, max_length=8)


class Unknown(Strict):
    code: UnknownCode
    subject: Identifier | None = None


class AffectedService(Strict):
    service: ServiceEntity
    owner: Owner
    relationship_refs: list[Identifier] = Field(min_length=1, max_length=32)


class ImpactPath(Strict):
    relationship_refs: list[Identifier] = Field(min_length=1, max_length=16)
    summary: Text


class TeamCheck(Strict):
    consumer: ServiceEntity
    text: Text
    claim_refs: list[Identifier] = Field(min_length=1, max_length=16)


class SourceFreshness(Strict):
    source_kind: Literal["git", "runtime", "jira", "ownership", "model"]
    source_id: Name
    freshness: Freshness


class ModelUse(Strict):
    configuration_id: Identifier
    model: str = Field(min_length=1, max_length=200)
    protocol: str = Field(min_length=1, max_length=40)


class Costs(Strict):
    """None means unknown, never zero."""
    model_calls: int = Field(ge=0)
    prompt_tokens: int | None = Field(ge=0)
    completion_tokens: int | None = Field(ge=0)
    reserved_micro: int | None = Field(ge=0)
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")] | None


class Timings(Strict):
    started_at: Timestamp
    finished_at: Timestamp
    seconds: dict[Name, Annotated[float, Field(ge=0)]] = Field(default_factory=dict, max_length=32)


class AnalysisResult(_Document):
    kind: Literal["analysis_result"] = "analysis_result"
    profile: Name
    code_version: str = Field(min_length=1, max_length=200)
    constitution_version: Identifier
    installation_id: Name
    environment: Name
    request_id: Identifier
    event_id: Identifier
    resource_version: str = Field(min_length=1, max_length=200)
    correlation_id: Identifier
    trigger_kind: Literal["jira", "pr", "replay"]
    snapshots: list[SnapshotUse] = Field(max_length=64)
    graph_version: Identifier
    status: ResultStatus
    reason_code: ReasonCode
    superseded_by: Identifier | None = None
    usefulness_confirmed: Literal[False] = False
    summary: Text
    affected: list[AffectedService] = Field(default_factory=list, max_length=64)
    impact_paths: list[ImpactPath] = Field(default_factory=list, max_length=64)
    checks: list[TeamCheck] = Field(default_factory=list, max_length=64)
    claims: list[Claim] = Field(default_factory=list, max_length=128)
    deltas: list[Delta] = Field(default_factory=list, max_length=128)
    findings: list[Finding] = Field(default_factory=list, max_length=256)
    gaps: list[Gap] = Field(default_factory=list, max_length=512)
    unknowns: list[Unknown] = Field(default_factory=list, max_length=64)
    source_freshness: list[SourceFreshness] = Field(default_factory=list, max_length=64)
    evidence: list[Evidence] = Field(default_factory=list, max_length=512)
    relationships: list[GraphRelationship] = Field(default_factory=list, max_length=512)
    model: ModelUse | None
    costs: Costs
    timings: Timings

    @model_validator(mode="after")
    def semantics(self):
        if self.reason_code not in REASONS[self.status]:
            raise ValueError("reason_not_allowed_for_status")
        if (self.status == "SUPERSEDED") != (self.superseded_by is not None):
            raise ValueError("superseded_by_mismatch")
        evidence = {e.id: e for e in self.evidence}
        relationships = {r.id for r in self.relationships}
        claims = {c.id for c in self.claims}
        if len(evidence) != len(self.evidence) or len(claims) != len(self.claims):
            raise ValueError("duplicate_identifier")
        refs = ([r for c in self.claims for r in c.evidence_refs]
                + [r for d in self.deltas for r in d.evidence_refs]
                + [r for f in self.findings for r in f.evidence_refs]
                + [r for g in self.gaps for r in g.evidence_refs]
                + [r for x in self.relationships for r in x.evidence_refs]
                + [r for e in self.evidence if e.origin == "model_hypothesis" for r in e.supporting_refs])
        if any(r not in evidence for r in refs):
            raise ValueError("unknown_evidence_ref")
        if any(r not in relationships for a in self.affected for r in a.relationship_refs) or any(
                r not in relationships for p in self.impact_paths for r in p.relationship_refs):
            raise ValueError("unknown_relationship_ref")
        if any(r not in claims for c in self.checks for r in c.claim_refs):
            raise ValueError("unknown_claim_ref")
        for claim in self.claims:
            cited = [evidence[r] for r in claim.evidence_refs]
            if claim.kind == "fact" and not any(
                    e.origin != "model_hypothesis" and e.provenance == "AUTHENTIC"
                    and e.sufficiency in FactSufficiency for e in cited):
                raise ValueError("fact_without_sufficient_evidence")
            subject = claim.subject
            if claim.kind == "fact" and subject is not None and subject.kind == "operation" and not any(
                    e.provenance == "AUTHENTIC" and e.sufficiency in FactSufficiency and (
                        e.origin == "code" or e.origin == "runtime" and e.method == subject.method
                        and e.route == subject.route and e.provider.service == subject.service)
                    for e in cited):
                raise ValueError("fact_without_operation_evidence")
            if any(e.provenance == "REJECTED" for e in cited):
                raise ValueError("claim_cites_rejected_evidence")
        if self.status == "USEFUL" and not self.claims:
            raise ValueError("useful_without_claims")
        if self.status == "PARTIAL" and not (self.gaps or self.unknowns):
            raise ValueError("partial_without_gaps_or_unknowns")
        if self.status in ("FAILED", "SUPERSEDED") and self.claims:
            raise ValueError("claims_on_non_result")
        if self.trigger_kind == "jira" and self.deltas:
            raise ValueError("jira_result_has_no_diff")
        return self


Document = Annotated[Union[AnalysisRequest, AnalysisResult], Field(discriminator="kind")]
_DOCUMENT = TypeAdapter(Document)


def _field_names():
    names = set()
    def visit(model):
        for name, field in model.model_fields.items():
            names.update({name, field.alias} - {None})
    for model in (AnalysisRequest, AnalysisResult, JiraTrigger, PullRequestTrigger, SourceEvent,
                  AccessScope, SnapshotUse, Claim, Delta, Finding, Gap, Unknown, AffectedService,
                  ImpactPath, TeamCheck, SourceFreshness, ModelUse, Costs, Timings, Freshness,
                  ServiceEntity, OperationEntity, CallsiteEntity, TeamEntity, CodeEvidence,
                  RuntimeEvidence, HypothesisEvidence, CorrectionEvidence, ExternalReportEvidence,
                  RuntimeAggregates, GraphRelationship, Owner):
        visit(model)
    # Discriminator tags pydantic adds to locations.
    return names | {"service", "operation", "callsite", "team", "code", "runtime",
                    "model_hypothesis", "correction", "external_report"}


_SAFE_SEGMENTS = _field_names()


def safe_errors(exc: ValidationError) -> list[dict]:
    """Field path and error type only. Input values, messages and unknown keys are dropped."""
    result = []
    for error in exc.errors(include_url=False, include_input=False, include_context=False):
        path = []
        loc = error["loc"]
        if loc and loc[0] in ("analysis_request", "analysis_result"):
            loc = loc[1:]  # Union tag added by pydantic, not a document field.
        for part in loc:
            path.append(str(part) if type(part) is int or part in _SAFE_SEGMENTS else "*")
        reason = None
        if error["type"] == "value_error":
            message = str(error.get("msg", ""))
            match = re.search(r"([a-z_]{3,60})$", message)
            reason = match.group(1) if match else None
        result.append(dict(path=".".join(path), type=error["type"], **({"rule": reason} if reason else {})))
    return result[:32]


def check_version(document) -> None:
    if not isinstance(document, dict) or document.get("schema") != SCHEMA_ID:
        raise ContractError("unknown_schema")
    version = document.get("schema_version")
    match = re.fullmatch(r"(0|[1-9][0-9]{0,3})\.(0|[1-9][0-9]{0,3})", version) if isinstance(version, str) else None
    if not match:
        raise ContractError("invalid_schema_version")
    major, minor = int(match.group(1)), int(match.group(2))
    if major != SCHEMA_MAJOR:
        raise ContractError("unsupported_schema_major")
    if minor > SCHEMA_MINOR:
        # One release ships producer and reader together; a newer minor is a mixed install.
        raise ContractError("newer_schema_minor")


def parse_document(document):
    """Validate an untrusted document. Raises ContractError with safe diagnostics only."""
    check_version(document)
    try:
        return _DOCUMENT.validate_python(document)
    except ValidationError as exc:
        errors = safe_errors(exc)
        code = "unknown_code" if any(e["type"] in ("literal_error", "enum") for e in errors) else "invalid_document"
        raise ContractError(code, errors) from None


def dump_document(model) -> dict:
    return model.model_dump(mode="json", by_alias=True)


def display_verdict(document) -> dict:
    """What a UI/API may show. Anything not fully understood is INCOMPATIBLE, never green."""
    try:
        parsed = parse_document(document)
    except ContractError as exc:
        return dict(display="INCOMPATIBLE", green=False, reason_code=exc.code, errors=exc.errors)
    if not isinstance(parsed, AnalysisResult):
        return dict(display="INCOMPATIBLE", green=False, reason_code="not_a_result", errors=[])
    return dict(display=parsed.status, green=parsed.status == "USEFUL",
                reason_code=parsed.reason_code, errors=[])


def _codes(literal) -> frozenset:
    return frozenset(literal.__args__)


CORE_CODE_FIELDS = (("findings", "code", _codes(FindingCode)), ("findings", "usage", _codes(UsageCode)),
                    ("deltas", "code", _codes(DeltaCode)), ("gaps", "code", _codes(GapCode)),
                    ("dependencies", "usage", _codes(UsageCode)))


def check_core_codes(document: dict) -> None:
    """Reader check for core (agent-graph-1) outputs consumed by the application.

    Every finding/delta/gap/usage code must be one this release knows; otherwise
    ContractError("unknown_code") with the field path, never a silent fallback.
    """
    if not isinstance(document, dict):
        raise ContractError("invalid_document")
    errors = []
    for key, field, known in CORE_CODE_FIELDS:
        items = document.get(key, [])
        if not isinstance(items, list):
            errors.append(dict(path=key, type="list_type"))
            continue
        for index, item in enumerate(items):
            if isinstance(item, dict) and field in item and item[field] not in known:
                errors.append(dict(path=f"{key}.{index}.{field}", type="literal_error"))
    if errors:
        raise ContractError("unknown_code", errors[:32])


def json_schema() -> dict:
    schema = _DOCUMENT.json_schema(by_alias=True)
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"https://github.com/rengalaxies/agent/schemas/agent-graph-output-{SCHEMA_MAJOR}.json",
            "title": f"{SCHEMA_ID} {SCHEMA_VERSION}",
            "description": ("Structure only. Status/reason pairs, fact backing, references and version "
                            "rules are enforced by agent_graph.output_contracts."),
            **schema}


if __name__ == "__main__":
    import json
    import sys
    sys.stdout.write(json.dumps(json_schema(), ensure_ascii=True, indent=2, sort_keys=True) + "\n")
