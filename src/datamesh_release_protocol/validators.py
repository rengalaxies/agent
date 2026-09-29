from __future__ import annotations

from collections.abc import Iterable

from .interpreter import TypedObligationInterpreter
from .models import (
    BaselinePolicy,
    BaselineRule,
    CheckResult,
    ConsumerObligation,
    ConsumerVerdict,
    DataContract,
    Decision,
    LocalVerdict,
    Migration,
    Scenario,
    ValidationMode,
)


_V2_INTERPRETER = TypedObligationInterpreter()


def _decision(checks: Iterable[CheckResult]) -> Decision:
    outcomes = {check.outcome for check in checks}
    if "FALSE" in outcomes:
        return Decision.REJECT
    if "UNKNOWN" in outcomes:
        return Decision.NEEDS_REVIEW
    return Decision.ACCEPT


def _result(dimension: str, ok: bool | None, code: str, **evidence: object) -> CheckResult:
    outcome = "UNKNOWN" if ok is None else ("TRUE" if ok else "FALSE")
    return CheckResult(dimension=dimension, outcome=outcome, reason_code=code, evidence=evidence)


def _schema_checks(old: DataContract, new: DataContract) -> list[CheckResult]:
    missing = sorted(set(old.schema_fields) - set(new.schema_fields))
    incompatible = sorted(
        field
        for field in set(old.schema_fields) & set(new.schema_fields)
        if old.schema_fields[field] != new.schema_fields[field]
    )
    return [
        _result(
            "schema",
            not missing and not incompatible,
            "SCHEMA_COMPATIBLE" if not missing and not incompatible else "SCHEMA_BREAKING",
            missing_fields=missing,
            incompatible_types=incompatible,
        )
    ]


def _migration(
    migrations: list[Migration], dimension: str, source: str, target: str
) -> Migration | None:
    return next(
        (
            migration
            for migration in migrations
            if migration.dimension == dimension
            and migration.source == source
            and migration.target == target
            and migration.is_valid
        ),
        None,
    )


def _baseline_rule_checks(scenario: Scenario, rule: BaselineRule) -> list[CheckResult]:
    old = scenario.old_contract.semantic
    new = scenario.new_contract.semantic
    if rule.kind == "require_migration_on_unit_change":
        changed = (old.unit, old.scale) != (new.unit, new.scale)
        migration = _migration(
            scenario.migrations,
            "unit_scale",
            f"{new.unit}:{new.scale}",
            f"{old.unit}:{old.scale}",
        )
        ok = not changed or migration is not None
        return [_result("unit_scale", ok, "BASELINE_UNIT_MIGRATION", changed=changed)]
    if rule.kind == "require_migration_on_identity_change":
        changed = old.identity_scope != new.identity_scope
        migration = _migration(
            scenario.migrations,
            "identity_scope",
            new.identity_scope,
            old.identity_scope,
        )
        ok = not changed or migration is not None
        return [_result("identity_scope", ok, "BASELINE_IDENTITY_MIGRATION", changed=changed)]
    if rule.kind == "allowed_sources":
        allowed = set(rule.value or [])
        actual = set(new.allowed_sources)
        return [_result("lineage", actual <= allowed, "BASELINE_ALLOWED_SOURCES", actual=sorted(actual))]
    if rule.kind == "required_purposes":
        required = set(rule.value or [])
        actual = set(new.purposes)
        return [_result("purpose", required <= actual, "BASELINE_REQUIRED_PURPOSES", actual=sorted(actual))]
    if rule.kind == "min_window_days":
        minimum = int(rule.value)
        return [_result("time_window", new.calculation_window_days is not None and new.calculation_window_days >= minimum, "BASELINE_MIN_WINDOW")]
    if rule.kind == "required_formula":
        return [_result("formula", new.formula == rule.value, "BASELINE_REQUIRED_FORMULA")]
    raise ValueError(f"unsupported baseline rule: {rule.kind}")


def validate(
    scenario: Scenario,
    mode: ValidationMode,
    baseline_policy: BaselinePolicy,
) -> list[LocalVerdict]:
    schema_checks = _schema_checks(scenario.old_contract, scenario.new_contract)
    by_domain: dict[str, list[ConsumerVerdict]] = {}
    for obligation in scenario.obligations:
        checks = list(schema_checks)
        if mode == ValidationMode.V1_IND:
            for rule in baseline_policy.rules_for(scenario.family_id):
                checks.extend(_baseline_rule_checks(scenario, rule))
        elif mode == ValidationMode.V2:
            checks.extend(
                _V2_INTERPRETER.evaluate(
                    scenario.new_contract,
                    obligation,
                    scenario.migrations,
                )
            )
        by_domain.setdefault(obligation.consumer_domain, []).append(
            ConsumerVerdict(
                consumer_id=obligation.consumer_id,
                decision=_decision(checks),
                checks=checks,
            )
        )
    verdicts: list[LocalVerdict] = []
    for domain_id in sorted(by_domain):
        consumer_verdicts = by_domain[domain_id]
        verdicts.append(
            LocalVerdict(
                domain_id=domain_id,
                decision=_decision_from_decisions(
                    verdict.decision for verdict in consumer_verdicts
                ),
                consumer_verdicts=consumer_verdicts,
            )
        )
    return verdicts


def _decision_from_decisions(decisions: Iterable[Decision]) -> Decision:
    values = set(decisions)
    if Decision.REJECT in values:
        return Decision.REJECT
    if Decision.NEEDS_REVIEW in values:
        return Decision.NEEDS_REVIEW
    if Decision.ACCEPT in values:
        return Decision.ACCEPT
    return Decision.NEEDS_REVIEW
