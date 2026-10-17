"""Verify pinned independent expectations against captured observations.

This module does not execute a candidate, attest an adapter, approve deployment,
or establish business truth. TrustPolicy must come from the deployment, not the
candidate. A subsequent executor must capture actual results in a sandbox.
"""
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
import json
from typing import Any, Literal

from pydantic import Field, StrictBool, StrictInt, ValidationError, model_validator

from .comparison import Column, Table, compare_tables
from .models import Action, AuthorityGrant, ContentRef, Contract, TransitionSpec

VERSION = "tabular-observations/1"
MAX_BUNDLE_BYTES = 1_000_000


def digest_bytes(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def context_digest(spec: TransitionSpec) -> str:
    """Bind every declared artifact, requirement, profile, policy and authority."""
    return digest_bytes(json.dumps(spec.model_dump(mode="json"), sort_keys=True,
                                   ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode())


def _unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError("duplicate JSON key")
        out[key] = value
    return out


def load_json(payload: bytes) -> dict:
    if type(payload) is not bytes or len(payload) > MAX_BUNDLE_BYTES:
        raise ValueError("bundle size or type")
    def invalid_constant(value):
        raise ValueError("nonfinite JSON constant")
    result = json.loads(payload, object_pairs_hook=_unique_object, parse_constant=invalid_constant)
    if type(result) is not dict:
        raise ValueError("bundle must be an object")
    return result


class ColumnRecord(Contract):
    name: str = Field(min_length=1)
    kind: Literal["int", "float", "decimal", "str", "bool"]
    nullable: StrictBool = True
    abs_tol: Any = 0
    rel_tol: Any = 0


class TableRecord(Contract):
    columns: tuple[ColumnRecord, ...] = Field(min_length=1, max_length=128)
    rows: tuple[tuple[Any, ...], ...] = Field(max_length=200)

    def table(self) -> Table:
        columns = tuple(Column(c.name, c.kind, c.nullable, c.abs_tol, c.rel_tol) for c in self.columns)
        rows = []
        for row in self.rows:
            values = []
            for index, value in enumerate(row):
                if index < len(self.columns) and self.columns[index].kind == "decimal" and value is not None:
                    # Decimal is an explicit wire type, encoded as text to avoid binary loss.
                    if type(value) is not str or len(value) > 1100:
                        raise ValueError("decimal wire value must be bounded text")
                    value = Decimal(value)
                values.append(value)
            rows.append(tuple(values))
        return Table(columns, tuple(rows))


class ExpectedCase(Contract):
    case_id: str = Field(min_length=1)
    requirement_ids: tuple[str, ...] = Field(min_length=1)
    fixture: ContentRef
    input_records: StrictInt = Field(ge=0)
    tags: tuple[str, ...] = Field(min_length=1)
    expected: TableRecord
    ordered: StrictBool = False
    numeric_equivalence: StrictBool = False


class ExpectationSuite(Contract):
    format: Literal["independent-expectations/1"]
    transition_id: str
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1)
    origin: Literal["owner_examples", "independent_reference"]
    prepared_at: datetime
    valid_until: datetime
    required_tags: tuple[str, ...] = Field(min_length=1)
    cases: tuple[ExpectedCase, ...] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def interval(self):
        if (self.prepared_at.utcoffset() is None or self.valid_until.utcoffset() is None
                or self.valid_until <= self.prepared_at):
            raise ValueError("invalid suite interval")
        return self


class ObservationCase(Contract):
    case_id: str
    fixture: ContentRef
    status: Literal["executed", "error", "timeout", "unsupported"]
    actual: TableRecord | None = None


class ObservationBundle(Contract):
    format: Literal["captured-observations/1"]
    transition_id: str
    context_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    suite_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_created_at: datetime
    captured_at: datetime
    cases: tuple[ObservationCase, ...] = Field(min_length=1, max_length=50)


@dataclass(frozen=True)
class TrustPolicy:
    approved_suite_digests: frozenset[str]
    approved_owners: frozenset[str]
    grants: tuple[AuthorityGrant, ...]
    revoked_grant_ids: frozenset[str] = frozenset()
    minimum_cases: int = 2


class CaseVerdict(Contract):
    case_id: str
    status: Literal["PASS", "FAIL", "STOP"]
    reason_codes: tuple[str, ...] = ()


class VerificationReport(Contract):
    verifier: Literal["tabular-observations/1"] = VERSION
    scope: Literal["provided_observations_only"] = "provided_observations_only"
    transition_id: str
    candidate_sha256: str
    context_sha256: str
    suite_sha256: str | None
    observations_sha256: str | None
    checked_at: datetime
    status: Literal["PASS", "FAIL", "STOP"]
    reason_codes: tuple[str, ...]
    cases: tuple[CaseVerdict, ...]
    effects_authorized: Literal[False] = False


def verify_observations(spec: TransitionSpec, candidate: ContentRef, suite_bytes: bytes,
                        observation_bytes: bytes, policy: TrustPolicy, *, at: datetime,
                        actor: str) -> VerificationReport:
    """No candidate-provided expected outputs or declared PASS values are trusted."""
    if at.utcoffset() is None:
        raise ValueError("verification time requires timezone")
    context = context_digest(spec)
    suite_hash = observed_hash = None
    reasons: list[str] = []
    verdicts: list[CaseVerdict] = []

    def finish(status):
        return VerificationReport(transition_id=spec.transition_id, candidate_sha256=candidate.sha256,
                                  context_sha256=context, suite_sha256=suite_hash,
                                  observations_sha256=observed_hash, checked_at=at, status=status,
                                  reason_codes=tuple(dict.fromkeys(reasons)), cases=tuple(verdicts))

    if (type(suite_bytes) is not bytes or type(observation_bytes) is not bytes
            or len(suite_bytes) > MAX_BUNDLE_BYTES or len(observation_bytes) > MAX_BUNDLE_BYTES):
        reasons.append("BUNDLE_SIZE_OR_TYPE_LIMIT")
        return finish("STOP")
    suite_hash, observed_hash = digest_bytes(suite_bytes), digest_bytes(observation_bytes)
    if suite_hash not in policy.approved_suite_digests:
        reasons.append("UNAPPROVED_EXPECTATIONS")
        return finish("STOP")
    try:
        suite = ExpectationSuite.model_validate(load_json(suite_bytes))
        observations = ObservationBundle.model_validate(load_json(observation_bytes))
    except (ValueError, TypeError, ValidationError, RecursionError):
        reasons.append("INVALID_BUNDLE")
        return finish("STOP")
    if suite.approved_by not in policy.approved_owners:
        reasons.append("UNAPPROVED_OWNER")
    if suite.transition_id != spec.transition_id or observations.transition_id != spec.transition_id:
        reasons.append("TRANSITION_MISMATCH")
    if suite.context_sha256 != context or observations.context_sha256 != context:
        reasons.append("STALE_CONTEXT")
    if observations.candidate_sha256 != candidate.sha256 or observations.suite_sha256 != suite_hash:
        reasons.append("ARTIFACT_BINDING_MISMATCH")
    times = (observations.candidate_created_at, observations.captured_at)
    if any(t.utcoffset() is None for t in times):
        reasons.append("INVALID_OBSERVATION_TIME")
    elif not suite.prepared_at < observations.candidate_created_at <= observations.captured_at <= at < suite.valid_until:
        reasons.append("STALE_OR_NONINDEPENDENT_EXPECTATIONS")
    if type(policy.minimum_cases) is not int or policy.minimum_cases < 1 or len(suite.cases) < policy.minimum_cases:
        reasons.append("INSUFFICIENT_CASES")
    if not any(c.input_records > 0 for c in suite.cases):
        reasons.append("ONLY_EMPTY_INPUTS")
    wanted = {r.requirement_id for r in spec.requirements}
    covered = {r for c in suite.cases for r in c.requirement_ids}
    if covered != wanted:
        reasons.append("REQUIREMENT_COVERAGE_MISMATCH")
    if not set(suite.required_tags) <= {t for c in suite.cases for t in c.tags}:
        reasons.append("MISSING_REQUIRED_CASE_TAGS")
    expected_ids = [c.case_id for c in suite.cases]
    actual_ids = [c.case_id for c in observations.cases]
    if len(set(expected_ids)) != len(expected_ids) or len(set(actual_ids)) != len(actual_ids) or set(expected_ids) != set(actual_ids):
        reasons.append("CASE_SET_MISMATCH")
    if spec.unknowns or any(e.certainty != "observed" for e in spec.dependencies):
        reasons.append("UNRESOLVED_SCOPE")
    # These grants come from the trusted caller policy, not from the candidate/spec body.
    for consumer in spec.consumers:
        if Action.VERIFY not in spec.allowed_actions or not any(
            g.grant_id not in policy.revoked_grant_ids and g.actor == actor
            and g.environment == spec.environment and consumer in g.component_ids
            and Action.VERIFY in g.actions and g.starts_at <= at < g.expires_at for g in policy.grants
        ):
            reasons.append("VERIFY_AUTHORITY_UNAVAILABLE")
    if reasons:
        return finish("STOP")
    actual_by_id = {c.case_id: c for c in observations.cases}
    for case in suite.cases:
        observed = actual_by_id[case.case_id]
        if observed.fixture != case.fixture:
            verdicts.append(CaseVerdict(case_id=case.case_id, status="STOP", reason_codes=("FIXTURE_BINDING_MISMATCH",)))
            continue
        if observed.status != "executed" or observed.actual is None:
            verdicts.append(CaseVerdict(case_id=case.case_id, status="STOP", reason_codes=("EXECUTION_NOT_COMPLETED",)))
            continue
        try:
            expected_table = case.expected.table()
        except (ValueError, InvalidOperation, OverflowError):
            verdicts.append(CaseVerdict(case_id=case.case_id, status="STOP", reason_codes=("INVALID_EXPECTED_TABLE",)))
            continue
        try:
            actual_table = observed.actual.table()
        except (ValueError, InvalidOperation, OverflowError):
            verdicts.append(CaseVerdict(case_id=case.case_id, status="FAIL", reason_codes=("INVALID_ACTUAL_TABLE",)))
            continue
        comparison = compare_tables(expected_table, actual_table, ordered=case.ordered,
                                    numeric_equivalence=case.numeric_equivalence)
        verdicts.append(CaseVerdict(case_id=case.case_id, status=comparison.status, reason_codes=comparison.reason_codes))
    # A demonstrated discrepancy is retained even when another case is unknown.
    status = "FAIL" if any(v.status == "FAIL" for v in verdicts) else "STOP" if any(v.status == "STOP" for v in verdicts) else "PASS"
    return finish(status)
