from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import AnalysisPlan, BaselinePolicy, OracleCatalog, Scenario, ScenarioOracle


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


def load_analysis_plan(path: Path) -> AnalysisPlan:
    return AnalysisPlan.model_validate(load_document(path))


def load_cluster_map(path: Path, scenarios: list[Scenario]) -> dict[str, str]:
    payload = load_document(path)
    if payload.get("scoring_only_metadata") is not True:
        raise ValueError("catalog manifest must declare scoring_only_metadata: true")
    entries = payload.get("scenarios")
    if not isinstance(entries, list):
        raise ValueError("catalog manifest scenarios must be an array")
    cluster_map: dict[str, str] = {}
    family_by_cluster: dict[str, str] = {}
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise ValueError(f"catalog manifest scenario {index} must be an object")
        scenario_id = entry.get("scenario_id")
        cluster_id = entry.get("cluster_id")
        family_id = entry.get("family_id")
        if not isinstance(scenario_id, str) or not isinstance(cluster_id, str):
            raise ValueError("every catalog scenario requires scenario_id and cluster_id")
        if scenario_id in cluster_map:
            raise ValueError(f"duplicate catalog scenario_id: {scenario_id}")
        if not cluster_id:
            raise ValueError(f"empty cluster_id for {scenario_id}")
        if cluster_id in family_by_cluster and family_by_cluster[cluster_id] != family_id:
            raise ValueError(f"cluster {cluster_id} crosses scenario families")
        family_by_cluster[cluster_id] = str(family_id)
        cluster_map[scenario_id] = cluster_id

    expected_ids = {scenario.scenario_id for scenario in scenarios}
    if set(cluster_map) != expected_ids:
        missing = sorted(expected_ids - set(cluster_map))
        extra = sorted(set(cluster_map) - expected_ids)
        raise ValueError(f"cluster coverage mismatch: missing={missing}, extra={extra}")
    for scenario in scenarios:
        entry_family = next(
            entry.get("family_id")
            for entry in entries
            if entry.get("scenario_id") == scenario.scenario_id
        )
        if entry_family != scenario.family_id:
            raise ValueError(f"catalog family mismatch for {scenario.scenario_id}")
    return cluster_map


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
