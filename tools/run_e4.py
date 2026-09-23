"""Run the preregistered E4 development scenarios; no oracle or evaluation data."""
from __future__ import annotations

import json
from pathlib import Path

from datamesh_release_protocol.distributed import run_distributed
from datamesh_release_protocol.engine import ReleaseEngine
from datamesh_release_protocol.loaders import load_baseline_policy, load_scenario
from datamesh_release_protocol.models import Scenario, ValidationMode


def three_domains() -> Scenario:
    scenario = load_scenario(Path("scenarios/development/T-03.yaml"))
    extra = scenario.obligations[0].model_copy(update={
        "obligation_id": "fintech-window-30d", "consumer_id": "fintech-reports",
        "consumer_domain": "fintech",
    })
    return scenario.model_copy(update={"scenario_id": "E4-3D-DEV", "obligations": scenario.obligations + [extra]})


def main() -> None:
    scenario = three_domains()
    policy = load_baseline_policy(Path("policies/v1-ind.yaml"))
    expected = ReleaseEngine(policy).run(scenario, ValidationMode.V2, "E4-DEV").decision.value
    cases = [
        ("normal", {}),
        ("duplicate", {"duplicate": True}),
        ("reverse_delivery", {"reverse": True}),
        ("late_domain", {"delays": {"mobility": 0.8}}),
        ("unavailable_domain", {"unavailable": frozenset({"mobility"})}),
    ]
    records = []
    for name, options in cases:
        result = run_distributed(scenario, policy, timeout_s=0.55, **options)
        result["case"] = name
        result["expected_behavior"] = "NEEDS_REVIEW" if name in {"late_domain", "unavailable_domain"} else expected
        result["passed"] = result["decision"] == result["expected_behavior"] and (
            len(result["received_domains"]) == 2 if name in {"late_domain", "unavailable_domain"}
            else len(result["received_domains"]) == 3
        )
        records.append(result)
    output = {"experiment": "E4 development process-isolation demonstration",
              "scenario_source": "development/T-03 plus one synthetic fintech obligation",
              "confirmatory": False, "timeout_s": 0.55, "baseline_decision": expected,
              "cases": records, "passed": sum(item["passed"] for item in records),
              "total": len(records)}
    dest = Path("results/e4-distributed-development.json")
    dest.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"{output['passed']}/{output['total']} cases passed: {dest}")
    if output["passed"] != output["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
