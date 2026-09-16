from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Decision(StrEnum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class ValidationMode(StrEnum):
    V0 = "V0"
    V1_IND = "V1-ind"
    V1_ORACLE = "V1-oracle"
    V2 = "V2"


class ProtocolState(StrEnum):
    RECEIVED = "RECEIVED"
    SNAPSHOT_LOCKED = "SNAPSHOT_LOCKED"
    LOCALLY_VALIDATED = "LOCALLY_VALIDATED"
    NEGOTIATING = "NEGOTIATING"
    DECIDED = "DECIDED"
    COMMITTED = "COMMITTED"
    QUARANTINED = "QUARANTINED"
    ESCALATED = "ESCALATED"


class ScenarioClass(StrEnum):
    DANGEROUS = "dangerous"
    ADMISSIBLE = "admissible"


class SemanticProfile(StrictModel):
    meaning: str
    description: str | None = None
    formula: str
    unit: str | None = None
    scale: int | None = None
    calculation_window_days: int | None = Field(default=None, gt=0)
    identity_scope: str
    allowed_sources: list[str] = Field(min_length=1)
    purposes: list[str] = Field(min_length=1)
    valid_time: str = "event_time"


class DataContract(StrictModel):
    product_id: str
    contract_version: str
    owner_domain: str
    schema_fields: dict[str, str] = Field(min_length=1)
    semantic: SemanticProfile


class Migration(StrictModel):
    dimension: Literal["unit_scale", "identity_scope"]
    source: str
    target: str
    expression: str
    validated_examples: int = Field(ge=0)
    bijective: bool = False

    @property
    def is_valid(self) -> bool:
        if self.validated_examples < 1:
            return False
        if self.dimension == "identity_scope" and not self.bijective:
            return False
        return True


class ConsumerObligation(StrictModel):
    obligation_id: str
    obligation_version: str
    consumer_id: str
    consumer_domain: str
    product_id: str
    required_meaning: str | None = None
    required_formula: str | None = None
    accepted_units: list[str] = Field(default_factory=list)
    accepted_scales: list[int] = Field(default_factory=list)
    min_window_days: int | None = Field(default=None, gt=0)
    accepted_identity_scopes: list[str] = Field(default_factory=list)
    allowed_sources: list[str] = Field(default_factory=list)
    required_purposes: list[str] = Field(default_factory=list)


class BaselineRule(StrictModel):
    rule_id: str
    kind: Literal[
        "require_migration_on_unit_change",
        "require_migration_on_identity_change",
        "allowed_sources",
        "required_purposes",
        "min_window_days",
        "required_formula",
    ]
    value: Any | None = None


class BaselinePolicy(StrictModel):
    policy_id: str
    version: str
    family_rules: dict[
        Literal["F1", "F2", "F3", "F4", "F5", "F6"],
        list[BaselineRule],
    ] = Field(default_factory=dict)

    def rules_for(self, family_id: str) -> list[BaselineRule]:
        return list(self.family_rules.get(family_id, []))

    @model_validator(mode="after")
    def check_complete_capability_matrix(self) -> "BaselinePolicy":
        expected_families = {"F1", "F2", "F3", "F4", "F5", "F6"}
        if set(self.family_rules) != expected_families:
            raise ValueError("family_rules must define F1 through F6 exactly once")
        rules = [rule for items in self.family_rules.values() for rule in items]
        rule_ids = [rule.rule_id for rule in rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("baseline rule_id values must be unique")
        for rule in rules:
            if rule.kind in {"allowed_sources", "required_purposes"} and not isinstance(
                rule.value, list
            ):
                raise ValueError(f"{rule.kind} requires a list value")
            if rule.kind == "min_window_days" and (
                not isinstance(rule.value, int) or rule.value < 1
            ):
                raise ValueError("min_window_days requires a positive integer value")
            if rule.kind == "required_formula" and not isinstance(rule.value, str):
                raise ValueError("required_formula requires a string value")
        return self


class Scenario(StrictModel):
    scenario_id: str
    family_id: Literal["F1", "F2", "F3", "F4", "F5", "F6"]
    split: Literal["development", "evaluation"]
    description: str
    old_contract: DataContract
    new_contract: DataContract
    obligations: list[ConsumerObligation] = Field(min_length=1)
    migrations: list[Migration] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_internal_consistency(self) -> "Scenario":
        product_ids = {
            self.old_contract.product_id,
            self.new_contract.product_id,
            *(obligation.product_id for obligation in self.obligations),
        }
        if len(product_ids) != 1:
            raise ValueError("contract and obligation product_id values must match")
        consumer_ids = [obligation.consumer_id for obligation in self.obligations]
        if len(consumer_ids) != len(set(consumer_ids)):
            raise ValueError("consumer_id values must be unique inside a scenario")
        obligation_ids = [obligation.obligation_id for obligation in self.obligations]
        if len(obligation_ids) != len(set(obligation_ids)):
            raise ValueError("obligation_id values must be unique inside a scenario")
        if self.old_contract.contract_version == self.new_contract.contract_version:
            raise ValueError("old and new contract versions must differ")
        return self


class ScenarioOracle(StrictModel):
    scenario_id: str
    scenario_class: ScenarioClass
    expected_decision: Decision
    expected_consumer_decisions: dict[str, Decision]
    rationale: str = Field(min_length=1)

    @model_validator(mode="after")
    def check_expected_class(self) -> "ScenarioOracle":
        expected_from_class = (
            Decision.REJECT
            if self.scenario_class == ScenarioClass.DANGEROUS
            else Decision.ACCEPT
        )
        if self.expected_decision != expected_from_class:
            raise ValueError("expected_decision contradicts scenario_class")
        return self


class OracleCatalog(StrictModel):
    catalog_id: str
    split: Literal["development", "evaluation"]
    labels: list[ScenarioOracle] = Field(min_length=1)

    @model_validator(mode="after")
    def check_unique_scenarios(self) -> "OracleCatalog":
        identifiers = [label.scenario_id for label in self.labels]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("oracle scenario_id values must be unique")
        return self


class ChangeProposal(StrictModel):
    proposal_id: str
    run_id: str
    scenario_id: str
    mode: ValidationMode
    product_id: str
    old_contract_version: str
    new_contract_version: str
    snapshot_id: str


class CheckResult(StrictModel):
    dimension: str
    outcome: Literal["TRUE", "FALSE", "UNKNOWN"]
    reason_code: str
    evidence: dict[str, Any] = Field(default_factory=dict)


class ConsumerVerdict(StrictModel):
    consumer_id: str
    decision: Decision
    checks: list[CheckResult]


class LocalVerdict(StrictModel):
    domain_id: str
    decision: Decision
    consumer_verdicts: list[ConsumerVerdict] = Field(min_length=1)


class ReleaseDecision(StrictModel):
    proposal: ChangeProposal
    decision: Decision
    terminal_state: ProtocolState
    local_verdicts: list[LocalVerdict]
    reason_codes: list[str]
    state_trace: list[ProtocolState]


class ScenarioRunResult(StrictModel):
    scenario_id: str
    mode: ValidationMode
    actual_decision: Decision
    duration_ms: float = Field(ge=0)
    release: ReleaseDecision
    expected_decision: Decision | None = None
    matches_expected: bool | None = None
