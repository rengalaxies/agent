from __future__ import annotations

from collections.abc import Callable

from .models import CheckResult, ConsumerObligation, DataContract, Migration


CheckBuilder = Callable[[DataContract, ConsumerObligation, list[Migration]], CheckResult | None]


def _result(dimension: str, ok: bool | None, code: str, **evidence: object) -> CheckResult:
    outcome = "UNKNOWN" if ok is None else ("TRUE" if ok else "FALSE")
    return CheckResult(dimension=dimension, outcome=outcome, reason_code=code, evidence=evidence)


def _valid_migration(
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


class TypedObligationInterpreter:
    """Reusable V2 interpreter for the typed ConsumerObligation model.

    The registry is fixed for a protocol version. Adding a new obligation field requires a
    new handler and a new protocol version; scenario-specific predicates are not accepted.
    """

    def __init__(self) -> None:
        self._handlers: tuple[CheckBuilder, ...] = (
            self._meaning,
            self._formula,
            self._unit_scale,
            self._time_window,
            self._identity_scope,
            self._lineage,
            self._purpose,
        )

    def evaluate(
        self,
        contract: DataContract,
        obligation: ConsumerObligation,
        migrations: list[Migration],
    ) -> list[CheckResult]:
        checks = [
            check
            for handler in self._handlers
            if (check := handler(contract, obligation, migrations)) is not None
        ]
        if not checks:
            checks.append(_result("obligation", None, "V2_EMPTY_OBLIGATION"))
        return checks

    @staticmethod
    def _meaning(
        contract: DataContract,
        obligation: ConsumerObligation,
        migrations: list[Migration],
    ) -> CheckResult | None:
        del migrations
        if obligation.required_meaning is None:
            return None
        return _result(
            "meaning",
            contract.semantic.meaning == obligation.required_meaning,
            "V2_REQUIRED_MEANING",
        )

    @staticmethod
    def _formula(
        contract: DataContract,
        obligation: ConsumerObligation,
        migrations: list[Migration],
    ) -> CheckResult | None:
        del migrations
        if obligation.required_formula is None:
            return None
        return _result(
            "formula",
            contract.semantic.formula == obligation.required_formula,
            "V2_REQUIRED_FORMULA",
        )

    @staticmethod
    def _unit_scale(
        contract: DataContract,
        obligation: ConsumerObligation,
        migrations: list[Migration],
    ) -> CheckResult | None:
        if not obligation.accepted_units:
            return None
        semantic = contract.semantic
        exact = semantic.unit in obligation.accepted_units and (
            not obligation.accepted_scales or semantic.scale in obligation.accepted_scales
        )
        migrated = any(
            _valid_migration(
                migrations,
                "unit_scale",
                f"{semantic.unit}:{semantic.scale}",
                f"{unit}:{scale}",
            )
            for unit in obligation.accepted_units
            for scale in (obligation.accepted_scales or [semantic.scale])
        )
        return _result("unit_scale", exact or migrated, "V2_CONSUMER_UNIT_SCALE")

    @staticmethod
    def _time_window(
        contract: DataContract,
        obligation: ConsumerObligation,
        migrations: list[Migration],
    ) -> CheckResult | None:
        del migrations
        if obligation.min_window_days is None:
            return None
        value = contract.semantic.calculation_window_days
        return _result(
            "time_window",
            None if value is None else value >= obligation.min_window_days,
            "V2_CONSUMER_MIN_WINDOW",
            actual=value,
            required=obligation.min_window_days,
        )

    @staticmethod
    def _identity_scope(
        contract: DataContract,
        obligation: ConsumerObligation,
        migrations: list[Migration],
    ) -> CheckResult | None:
        if not obligation.accepted_identity_scopes:
            return None
        semantic = contract.semantic
        exact = semantic.identity_scope in obligation.accepted_identity_scopes
        migrated = any(
            _valid_migration(
                migrations,
                "identity_scope",
                semantic.identity_scope,
                target,
            )
            for target in obligation.accepted_identity_scopes
        )
        return _result(
            "identity_scope",
            exact or migrated,
            "V2_CONSUMER_IDENTITY_SCOPE",
        )

    @staticmethod
    def _lineage(
        contract: DataContract,
        obligation: ConsumerObligation,
        migrations: list[Migration],
    ) -> CheckResult | None:
        del migrations
        if not obligation.allowed_sources:
            return None
        return _result(
            "lineage",
            set(contract.semantic.allowed_sources) <= set(obligation.allowed_sources),
            "V2_CONSUMER_ALLOWED_SOURCES",
        )

    @staticmethod
    def _purpose(
        contract: DataContract,
        obligation: ConsumerObligation,
        migrations: list[Migration],
    ) -> CheckResult | None:
        del migrations
        if not obligation.required_purposes:
            return None
        return _result(
            "purpose",
            set(obligation.required_purposes) <= set(contract.semantic.purposes),
            "V2_CONSUMER_REQUIRED_PURPOSES",
        )
