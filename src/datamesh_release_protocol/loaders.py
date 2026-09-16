from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import BaselinePolicy, OracleCatalog, Scenario, ScenarioOracle


def load_document(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as source:
        if path.suffix.lower() == ".json":
            payload = json.load(source)
        elif path.suffix.lower() in {".yaml", ".yml"}:
            payload = yaml.safe_load(source)
        else:
            raise ValueError(f"unsupported document type: {path.suffix}")
    if not isinstance(payload, dict):
        raise ValueError(f"document root must be an object: {path}")
    return payload


def load_scenario(path: Path) -> Scenario:
    return Scenario.model_validate(load_document(path))


def load_baseline_policy(path: Path) -> BaselinePolicy:
    return BaselinePolicy.model_validate(load_document(path))


def load_oracle_catalog(path: Path) -> dict[str, ScenarioOracle]:
    catalog = OracleCatalog.model_validate(load_document(path))
    return {label.scenario_id: label for label in catalog.labels}


def load_catalog(directory: Path) -> list[Scenario]:
    paths = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml"), *directory.glob("*.json")])
    if not paths:
        raise ValueError(f"no scenarios found in {directory}")
    scenarios = [load_scenario(path) for path in paths]
    identifiers = [scenario.scenario_id for scenario in scenarios]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("scenario_id values must be unique")
    return scenarios


def validate_oracle_coverage(
    scenarios: list[Scenario], oracles: dict[str, ScenarioOracle]
) -> None:
    scenario_ids = {scenario.scenario_id for scenario in scenarios}
    if scenario_ids != set(oracles):
        missing = sorted(scenario_ids - set(oracles))
        extra = sorted(set(oracles) - scenario_ids)
        raise ValueError(f"oracle coverage mismatch: missing={missing}, extra={extra}")
    for scenario in scenarios:
        consumer_ids = {item.consumer_id for item in scenario.obligations}
        oracle_ids = set(oracles[scenario.scenario_id].expected_consumer_decisions)
        if consumer_ids != oracle_ids:
            raise ValueError(
                f"oracle consumer coverage mismatch for {scenario.scenario_id}: "
                f"expected={sorted(consumer_ids)}, actual={sorted(oracle_ids)}"
            )
