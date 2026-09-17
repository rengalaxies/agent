from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from typing import Any

from .models import (
    BusinessCaseModel,
    BusinessCostScenario,
    Decision,
    ScenarioRunResult,
    ValidationMode,
)


@dataclass(frozen=True)
class OutcomeRates:
    scenario_count: int
    dangerous_count: int
    admissible_count: int
    dangerous_accept_rate: float
    dangerous_reject_rate: float
    dangerous_review_rate: float
    admissible_accept_rate: float
    admissible_reject_rate: float
    admissible_review_rate: float

    @property
    def false_block_rate(self) -> float:
        return self.admissible_reject_rate + self.admissible_review_rate

    @property
    def needs_review_rate(self) -> float:
        review_count = (
            self.dangerous_count * self.dangerous_review_rate
            + self.admissible_count * self.admissible_review_rate
        )
        return review_count / self.scenario_count

    def as_dict(self) -> dict[str, int | float]:
        return {
            "scenario_count": self.scenario_count,
            "dangerous_count": self.dangerous_count,
            "admissible_count": self.admissible_count,
            "dangerous_accept_rate": _rounded(self.dangerous_accept_rate),
            "dangerous_reject_rate": _rounded(self.dangerous_reject_rate),
            "dangerous_review_rate": _rounded(self.dangerous_review_rate),
            "admissible_accept_rate": _rounded(self.admissible_accept_rate),
            "admissible_reject_rate": _rounded(self.admissible_reject_rate),
            "admissible_review_rate": _rounded(self.admissible_review_rate),
            "false_block_rate": _rounded(self.false_block_rate),
            "needs_review_rate": _rounded(self.needs_review_rate),
        }


def _rounded(value: float) -> float:
    return round(value, 6)


def _rate(results: list[ScenarioRunResult], decision: Decision) -> float:
    if not results:
        raise ValueError("cannot derive a conditional rate from an empty class")
    return sum(item.actual_decision == decision for item in results) / len(results)


def derive_outcome_rates(
    results: list[ScenarioRunResult],
) -> dict[ValidationMode, OutcomeRates]:
    report: dict[ValidationMode, OutcomeRates] = {}
    for mode in (ValidationMode.V1_IND, ValidationMode.V2):
        mode_results = [item for item in results if item.mode == mode]
        if not mode_results:
            raise ValueError(f"scored results contain no {mode.value} observations")
        identifiers = [item.scenario_id for item in mode_results]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError(f"scored results contain duplicate {mode.value} scenarios")
        if any(item.expected_decision is None for item in mode_results):
            raise ValueError("business analysis requires scored results with expected_decision")
        unsupported = {
            item.expected_decision
            for item in mode_results
            if item.expected_decision not in {Decision.ACCEPT, Decision.REJECT}
        }
        if unsupported:
            raise ValueError(f"unsupported expected decisions: {sorted(unsupported)}")

        dangerous = [
            item for item in mode_results if item.expected_decision == Decision.REJECT
        ]
        admissible = [
            item for item in mode_results if item.expected_decision == Decision.ACCEPT
        ]
        report[mode] = OutcomeRates(
            scenario_count=len(mode_results),
            dangerous_count=len(dangerous),
            admissible_count=len(admissible),
            dangerous_accept_rate=_rate(dangerous, Decision.ACCEPT),
            dangerous_reject_rate=_rate(dangerous, Decision.REJECT),
            dangerous_review_rate=_rate(dangerous, Decision.NEEDS_REVIEW),
            admissible_accept_rate=_rate(admissible, Decision.ACCEPT),
            admissible_reject_rate=_rate(admissible, Decision.REJECT),
            admissible_review_rate=_rate(admissible, Decision.NEEDS_REVIEW),
        )

    if {
        item.scenario_id for item in results if item.mode == ValidationMode.V1_IND
    } != {item.scenario_id for item in results if item.mode == ValidationMode.V2}:
        raise ValueError("V1-ind and V2 must cover the same scenario identifiers")
    return report


def _validate_against_metrics(
    rates: dict[ValidationMode, OutcomeRates], metrics: dict[str, Any]
) -> None:
    by_mode = metrics.get("by_mode")
    if not isinstance(by_mode, dict):
        raise ValueError("metrics report has no by_mode object")
    for mode, observed in rates.items():
        published = by_mode.get(mode.value)
        if not isinstance(published, dict):
            raise ValueError(f"metrics report has no {mode.value} object")
        expected_values = {
            "unsafe_accept_rate": observed.dangerous_accept_rate,
            "false_block_rate": observed.false_block_rate,
            "needs_review_rate": observed.needs_review_rate,
        }
        for metric_name, expected in expected_values.items():
            actual = published.get(metric_name)
            if not isinstance(actual, (int, float)) or not isclose(
                float(actual), expected, abs_tol=1e-6
            ):
                raise ValueError(
                    f"{mode.value} {metric_name} differs between scored results and metrics"
                )


def _mode_cost(
    rates: OutcomeRates,
    scenario: BusinessCostScenario,
    mode: ValidationMode,
) -> dict[str, float]:
    dangerous_proposals = scenario.proposal_count * scenario.dangerous_change_share
    admissible_proposals = scenario.proposal_count - dangerous_proposals
    escaped_count = dangerous_proposals * rates.dangerous_accept_rate
    false_reject_count = admissible_proposals * rates.admissible_reject_rate
    review_count = (
        dangerous_proposals * rates.dangerous_review_rate
        + admissible_proposals * rates.admissible_review_rate
    )
    escaped_cost = escaped_count * scenario.escaped_dangerous_change_cost_reu
    false_reject_cost = false_reject_count * scenario.false_reject_cost_reu
    review_cost = review_count * scenario.manual_review_cost_reu
    fixed_cost = scenario.fixed_cost_reu_by_mode[mode]
    total = escaped_cost + false_reject_cost + review_cost + fixed_cost
    return {
        "expected_escaped_dangerous_changes": _rounded(escaped_count),
        "expected_false_rejections": _rounded(false_reject_count),
        "expected_manual_reviews": _rounded(review_count),
        "escaped_change_cost_reu": _rounded(escaped_cost),
        "false_reject_cost_reu": _rounded(false_reject_cost),
        "manual_review_cost_reu": _rounded(review_cost),
        "fixed_cost_reu": _rounded(fixed_cost),
        "total_cost_reu": _rounded(total),
    }


def _break_even(
    rates: dict[ValidationMode, OutcomeRates], scenario: BusinessCostScenario
) -> dict[str, float | str | None]:
    v1 = rates[ValidationMode.V1_IND]
    v2 = rates[ValidationMode.V2]
    dangerous_proposals = scenario.proposal_count * scenario.dangerous_change_share
    escaped_reduction = dangerous_proposals * (
        v1.dangerous_accept_rate - v2.dangerous_accept_rate
    )

    def non_incident_cost(mode: ValidationMode, item: OutcomeRates) -> float:
        admissible_proposals = scenario.proposal_count - dangerous_proposals
        reviews = (
            dangerous_proposals * item.dangerous_review_rate
            + admissible_proposals * item.admissible_review_rate
        )
        return (
            admissible_proposals
            * item.admissible_reject_rate
            * scenario.false_reject_cost_reu
            + reviews * scenario.manual_review_cost_reu
            + scenario.fixed_cost_reu_by_mode[mode]
        )

    v1_other = non_incident_cost(ValidationMode.V1_IND, v1)
    v2_other = non_incident_cost(ValidationMode.V2, v2)
    if escaped_reduction <= 0:
        status = (
            "v2_always_no_more_expensive"
            if v2_other <= v1_other
            else "no_finite_break_even_without_escape_reduction"
        )
        return {
            "status": status,
            "escaped_changes_avoided": _rounded(max(escaped_reduction, 0)),
            "incident_cost_reu": None,
        }
    threshold = (v2_other - v1_other) / escaped_reduction
    return {
        "status": "v2_already_cheaper_at_zero_incident_cost"
        if threshold <= 0
        else "finite_threshold",
        "escaped_changes_avoided": _rounded(escaped_reduction),
        "incident_cost_reu": _rounded(max(threshold, 0)),
    }


def build_business_case_report(
    results: list[ScenarioRunResult],
    metrics: dict[str, Any],
    model: BusinessCaseModel,
) -> dict[str, Any]:
    purpose = metrics.get("purpose")
    if purpose not in {"development_regression", "confirmatory_e3"}:
        raise ValueError("metrics report has unsupported or missing purpose")
    rates = derive_outcome_rates(results)
    _validate_against_metrics(rates, metrics)

    scenario_reports = []
    for scenario in model.scenarios:
        by_mode = {
            mode.value: _mode_cost(rates[mode], scenario, mode)
            for mode in model.compared_modes
        }
        v1_total = by_mode[ValidationMode.V1_IND.value]["total_cost_reu"]
        v2_total = by_mode[ValidationMode.V2.value]["total_cost_reu"]
        scenario_reports.append(
            {
                "scenario_id": scenario.scenario_id,
                "label": scenario.label,
                "description": scenario.description,
                "assumptions": {
                    "proposal_count": scenario.proposal_count,
                    "dangerous_change_share": scenario.dangerous_change_share,
                    "escaped_dangerous_change_cost_reu": (
                        scenario.escaped_dangerous_change_cost_reu
                    ),
                    "false_reject_cost_reu": scenario.false_reject_cost_reu,
                    "manual_review_cost_reu": scenario.manual_review_cost_reu,
                    "fixed_cost_reu_by_mode": {
                        mode.value: value
                        for mode, value in scenario.fixed_cost_reu_by_mode.items()
                    },
                },
                "by_mode": by_mode,
                "comparison": {
                    "v2_savings_reu": _rounded(v1_total - v2_total),
                    "lower_cost_mode": (
                        ValidationMode.V2.value
                        if v2_total < v1_total
                        else ValidationMode.V1_IND.value
                        if v1_total < v2_total
                        else "equal"
                    ),
                },
                "break_even": _break_even(rates, scenario),
            }
        )

    return {
        "artifact_kind": "business_case_sensitivity_report",
        "model_id": model.model_id,
        "model_version": model.model_version,
        "cost_unit": model.cost_unit,
        "experiment_purpose": purpose,
        "claim_scope": "scenario_analysis_only",
        "realized_roi_supported": False,
        "warning": (
            "Development rates are regression evidence only; the report is not an E3 "
            "result or an empirical ROI estimate."
            if purpose == "development_regression"
            else "E3 rates describe the fixed synthetic catalog; cost assumptions remain "
            "scenario inputs and do not establish realized ROI."
        ),
        "assumptions": model.assumptions,
        "observed_rates_by_mode": {
            mode.value: rates[mode].as_dict() for mode in model.compared_modes
        },
        "scenarios": scenario_reports,
    }
