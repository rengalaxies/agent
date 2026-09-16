from __future__ import annotations

from math import ceil, comb
from statistics import median

from .models import Decision, ScenarioClass, ScenarioOracle, ScenarioRunResult, ValidationMode


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(0.95 * len(ordered)) - 1)]


def score_results(
    results: list[ScenarioRunResult],
    oracles: dict[str, ScenarioOracle],
) -> dict[str, dict[str, float | int | None]]:
    report: dict[str, dict[str, float | int | None]] = {}
    for mode in ValidationMode:
        mode_results = [result for result in results if result.mode == mode]
        dangerous = [
            result
            for result in mode_results
            if oracles[result.scenario_id].scenario_class == ScenarioClass.DANGEROUS
        ]
        admissible = [
            result
            for result in mode_results
            if oracles[result.scenario_id].scenario_class == ScenarioClass.ADMISSIBLE
        ]
        exact = sum(
            result.actual_decision == oracles[result.scenario_id].expected_decision
            for result in mode_results
        )
        dangerous_safe = sum(
            result.actual_decision != Decision.ACCEPT for result in dangerous
        )
        dangerous_reject = sum(
            result.actual_decision == Decision.REJECT for result in dangerous
        )
        admissible_accept = sum(
            result.actual_decision == Decision.ACCEPT for result in admissible
        )
        needs_review = sum(
            result.actual_decision == Decision.NEEDS_REVIEW for result in mode_results
        )
        consumer_total = 0
        consumer_exact = 0
        for result in mode_results:
            expected = oracles[result.scenario_id].expected_consumer_decisions
            actual = {
                consumer.consumer_id: consumer.decision
                for local in result.release.local_verdicts
                for consumer in local.consumer_verdicts
            }
            consumer_total += len(expected)
            consumer_exact += sum(actual.get(key) == value for key, value in expected.items())
        durations = [result.duration_ms for result in mode_results]
        report[mode.value] = {
            "scenario_count": len(mode_results),
            "exact_decision_accuracy": _percent(exact, len(mode_results)),
            "dangerous_safe_detection_rate": _percent(dangerous_safe, len(dangerous)),
            "dangerous_strict_reject_rate": _percent(dangerous_reject, len(dangerous)),
            "unsafe_accept_rate": _percent(len(dangerous) - dangerous_safe, len(dangerous)),
            "admissible_accept_rate": _percent(admissible_accept, len(admissible)),
            "false_block_rate": _percent(len(admissible) - admissible_accept, len(admissible)),
            "needs_review_rate": _percent(needs_review, len(mode_results)),
            "consumer_decision_accuracy": _percent(consumer_exact, consumer_total),
            "median_latency_ms": round(median(durations), 6) if durations else None,
            "p95_latency_ms": round(_p95(durations), 6) if durations else None,
        }
    return report


def _exact_mcnemar_pvalue(improvements: int, regressions: int) -> float:
    discordant = improvements + regressions
    if discordant == 0:
        return 1.0
    tail = sum(comb(discordant, index) for index in range(min(improvements, regressions) + 1))
    return round(min(1.0, 2 * tail / (2**discordant)), 6)


def compare_v2_to_v1_ind(
    results: list[ScenarioRunResult],
    oracles: dict[str, ScenarioOracle],
) -> dict[str, float | int]:
    by_mode = {
        mode: {
            result.scenario_id: result.actual_decision
            for result in results
            if result.mode == mode
        }
        for mode in [ValidationMode.V1_IND, ValidationMode.V2]
    }
    dangerous_ids = [
        scenario_id
        for scenario_id, oracle in oracles.items()
        if oracle.scenario_class == ScenarioClass.DANGEROUS
    ]
    admissible_ids = [
        scenario_id
        for scenario_id, oracle in oracles.items()
        if oracle.scenario_class == ScenarioClass.ADMISSIBLE
    ]
    improvements = sum(
        by_mode[ValidationMode.V2][scenario_id] != Decision.ACCEPT
        and by_mode[ValidationMode.V1_IND][scenario_id] == Decision.ACCEPT
        for scenario_id in dangerous_ids
    )
    regressions = sum(
        by_mode[ValidationMode.V2][scenario_id] == Decision.ACCEPT
        and by_mode[ValidationMode.V1_IND][scenario_id] != Decision.ACCEPT
        for scenario_id in dangerous_ids
    )
    v2_safe = sum(
        by_mode[ValidationMode.V2][scenario_id] != Decision.ACCEPT
        for scenario_id in dangerous_ids
    )
    v1_safe = sum(
        by_mode[ValidationMode.V1_IND][scenario_id] != Decision.ACCEPT
        for scenario_id in dangerous_ids
    )
    v2_false_blocks = sum(
        by_mode[ValidationMode.V2][scenario_id] != Decision.ACCEPT
        for scenario_id in admissible_ids
    )
    v1_false_blocks = sum(
        by_mode[ValidationMode.V1_IND][scenario_id] != Decision.ACCEPT
        for scenario_id in admissible_ids
    )
    return {
        "dangerous_scenario_count": len(dangerous_ids),
        "safe_detection_rate_delta": round(
            v2_safe / len(dangerous_ids) - v1_safe / len(dangerous_ids), 6
        ),
        "paired_improvements": improvements,
        "paired_regressions": regressions,
        "exact_mcnemar_pvalue": _exact_mcnemar_pvalue(improvements, regressions),
        "admissible_scenario_count": len(admissible_ids),
        "false_block_rate_delta": round(
            v2_false_blocks / len(admissible_ids)
            - v1_false_blocks / len(admissible_ids),
            6,
        ),
    }


def build_metrics_report(
    results: list[ScenarioRunResult],
    oracles: dict[str, ScenarioOracle],
) -> dict[str, object]:
    return {
        "by_mode": score_results(results, oracles),
        "primary_comparison_v2_vs_v1_ind": compare_v2_to_v1_ind(results, oracles),
        "interpretation": "development regression only; not confirmatory evidence for H1",
    }
