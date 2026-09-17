from __future__ import annotations

from collections import defaultdict
from math import ceil, comb
from random import Random
from statistics import NormalDist, median

from .models import (
    AnalysisPlan,
    Decision,
    ScenarioClass,
    ScenarioOracle,
    ScenarioRunResult,
    ValidationMode,
)


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 6)


def _p95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, ceil(0.95 * len(ordered)) - 1)]


def _quantile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _wilson_interval(
    successes: int, total: int, confidence_level: float
) -> dict[str, float | int | str]:
    if total < 1:
        raise ValueError("cannot calculate a proportion interval without observations")
    z = NormalDist().inv_cdf(0.5 + confidence_level / 2)
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    half_width = (
        z
        * ((proportion * (1 - proportion) / total + z * z / (4 * total * total)) ** 0.5)
        / denominator
    )
    return {
        "lower": round(max(0.0, center - half_width), 6),
        "upper": round(min(1.0, center + half_width), 6),
        "confidence_level": confidence_level,
        "method": "wilson_score",
        "observation_count": total,
    }


def _cluster_bootstrap_interval(
    values_by_scenario: dict[str, float],
    cluster_ids: dict[str, str],
    *,
    confidence_level: float,
    resamples: int,
    seed: int,
) -> dict[str, float | int | str]:
    by_cluster: dict[str, list[float]] = defaultdict(list)
    for scenario_id, value in values_by_scenario.items():
        by_cluster[cluster_ids[scenario_id]].append(value)
    clusters = sorted(by_cluster)
    if not clusters:
        raise ValueError("cannot bootstrap an empty scenario set")

    rng = Random(seed)
    estimates: list[float] = []
    for _ in range(resamples):
        sampled = [rng.choice(clusters) for _ in clusters]
        values = [value for cluster in sampled for value in by_cluster[cluster]]
        estimates.append(sum(values) / len(values))

    tail = (1 - confidence_level) / 2
    return {
        "lower": round(_quantile(estimates, tail), 6),
        "upper": round(_quantile(estimates, 1 - tail), 6),
        "confidence_level": confidence_level,
        "method": "percentile_cluster_bootstrap",
        "cluster_count": len(clusters),
        "resamples": resamples,
    }


def score_results(
    results: list[ScenarioRunResult],
    oracles: dict[str, ScenarioOracle],
    cluster_ids: dict[str, str],
    analysis_plan: AnalysisPlan,
) -> dict[str, dict[str, object]]:
    report: dict[str, dict[str, object]] = {}
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
        if len({cluster_ids[item.scenario_id] for item in dangerous}) != len(dangerous):
            raise ValueError("dangerous scenarios must contribute at most once per cluster")
        if len({cluster_ids[item.scenario_id] for item in admissible}) != len(admissible):
            raise ValueError("admissible scenarios must contribute at most once per cluster")
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
            "confidence_intervals_95": {
                "dangerous_safe_detection_rate": _wilson_interval(
                    dangerous_safe,
                    len(dangerous),
                    analysis_plan.confidence_level,
                ),
                "false_block_rate": _wilson_interval(
                    len(admissible) - admissible_accept,
                    len(admissible),
                    analysis_plan.confidence_level,
                ),
                "needs_review_rate": _wilson_interval(
                    needs_review,
                    len(mode_results),
                    analysis_plan.confidence_level,
                ),
            },
        }
    return report


def _exact_mcnemar_pvalue(improvements: int, regressions: int) -> float:
    discordant = improvements + regressions
    if discordant == 0:
        return 1.0
    tail = sum(comb(discordant, index) for index in range(min(improvements, regressions) + 1))
    return round(min(1.0, 2 * tail / (2**discordant)), 6)


def _exact_cluster_sign_flip_pvalue(
    differences: dict[str, float], cluster_ids: dict[str, str]
) -> float:
    contributions: dict[str, int] = defaultdict(int)
    for scenario_id, difference in differences.items():
        contributions[cluster_ids[scenario_id]] += int(difference)
    nonzero = [abs(value) for value in contributions.values() if value]
    if not nonzero:
        return 1.0

    distribution = {0: 1}
    for contribution in nonzero:
        updated: dict[int, int] = defaultdict(int)
        for total, count in distribution.items():
            updated[total + contribution] += count
            updated[total - contribution] += count
        distribution = dict(updated)
    observed = abs(sum(contributions.values()))
    extreme = sum(count for total, count in distribution.items() if abs(total) >= observed)
    return round(extreme / (2 ** len(nonzero)), 6)


def compare_v2_to_v1_ind(
    results: list[ScenarioRunResult],
    oracles: dict[str, ScenarioOracle],
    cluster_ids: dict[str, str],
    analysis_plan: AnalysisPlan,
) -> dict[str, object]:
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
    dangerous_differences = {
        scenario_id: float(
            by_mode[ValidationMode.V2][scenario_id] != Decision.ACCEPT
        )
        - float(by_mode[ValidationMode.V1_IND][scenario_id] != Decision.ACCEPT)
        for scenario_id in dangerous_ids
    }
    false_block_differences = {
        scenario_id: float(
            by_mode[ValidationMode.V2][scenario_id] != Decision.ACCEPT
        )
        - float(by_mode[ValidationMode.V1_IND][scenario_id] != Decision.ACCEPT)
        for scenario_id in admissible_ids
    }
    improvements = sum(value > 0 for value in dangerous_differences.values())
    regressions = sum(value < 0 for value in dangerous_differences.values())
    return {
        "dangerous_scenario_count": len(dangerous_ids),
        "dangerous_cluster_count": len({cluster_ids[item] for item in dangerous_ids}),
        "safe_detection_rate_delta": round(
            sum(dangerous_differences.values()) / len(dangerous_ids), 6
        ),
        "safe_detection_rate_delta_ci95": _cluster_bootstrap_interval(
            dangerous_differences,
            cluster_ids,
            confidence_level=analysis_plan.confidence_level,
            resamples=analysis_plan.cluster_bootstrap_resamples,
            seed=analysis_plan.bootstrap_seed + 1001,
        ),
        "paired_improvements": improvements,
        "paired_regressions": regressions,
        "exact_cluster_sign_flip_pvalue": _exact_cluster_sign_flip_pvalue(
            dangerous_differences, cluster_ids
        ),
        "unadjusted_exact_mcnemar_pvalue": _exact_mcnemar_pvalue(
            improvements, regressions
        ),
        "admissible_scenario_count": len(admissible_ids),
        "admissible_cluster_count": len({cluster_ids[item] for item in admissible_ids}),
        "false_block_rate_delta": round(
            sum(false_block_differences.values()) / len(admissible_ids), 6
        ),
        "false_block_rate_delta_ci95": _cluster_bootstrap_interval(
            false_block_differences,
            cluster_ids,
            confidence_level=analysis_plan.confidence_level,
            resamples=analysis_plan.cluster_bootstrap_resamples,
            seed=analysis_plan.bootstrap_seed + 1002,
        ),
        "cluster_adjustment": "cluster_id from the scoring-only catalog manifest",
    }


def _assess_h1(
    by_mode: dict[str, dict[str, object]],
    comparison: dict[str, object],
    analysis_plan: AnalysisPlan,
    purpose: str,
) -> dict[str, object]:
    thresholds = analysis_plan.h1_thresholds
    delta_ci = comparison["safe_detection_rate_delta_ci95"]
    assert isinstance(delta_ci, dict)
    v2 = by_mode[ValidationMode.V2.value]
    criteria = {
        "minimum_effect_met": (
            float(comparison["safe_detection_rate_delta"])
            >= thresholds.minimum_safe_detection_rate_delta
        ),
        "ci_excludes_zero": float(delta_ci["lower"]) > 0,
        "cluster_adjusted_pvalue_met": (
            float(comparison["exact_cluster_sign_flip_pvalue"]) <= analysis_plan.alpha
        ),
        "false_block_bound_met": (
            float(v2["false_block_rate"]) <= thresholds.maximum_false_block_rate
        ),
        "needs_review_bound_met": (
            float(v2["needs_review_rate"]) <= thresholds.maximum_needs_review_rate
        ),
    }
    all_met = all(criteria.values())
    eligible = purpose == "confirmatory_e3"
    if not eligible:
        status = "not_assessed_development_only"
    else:
        status = "supports_h1" if all_met else "does_not_support_h1"
    return {
        "eligible_for_confirmatory_claim": eligible,
        "status": status,
        "all_criteria_met": all_met,
        "criteria": criteria,
        "thresholds": thresholds.model_dump(mode="json"),
        "alpha": analysis_plan.alpha,
    }


def build_metrics_report(
    results: list[ScenarioRunResult],
    oracles: dict[str, ScenarioOracle],
    cluster_ids: dict[str, str],
    analysis_plan: AnalysisPlan,
    purpose: str = "development_regression",
) -> dict[str, object]:
    interpretations = {
        "development_regression": "development regression only; not confirmatory evidence for H1",
        "confirmatory_e3": "confirmatory E3 result; interpret only under the frozen protocol and stated validity limits",
    }
    if purpose not in interpretations:
        raise ValueError(f"unsupported experiment purpose: {purpose}")
    by_mode = score_results(results, oracles, cluster_ids, analysis_plan)
    comparison = compare_v2_to_v1_ind(
        results, oracles, cluster_ids, analysis_plan
    )
    return {
        "purpose": purpose,
        "analysis_plan_id": analysis_plan.plan_id,
        "by_mode": by_mode,
        "primary_comparison_v2_vs_v1_ind": comparison,
        "h1_assessment": _assess_h1(
            by_mode, comparison, analysis_plan, purpose
        ),
        "interpretation": interpretations[purpose],
    }
