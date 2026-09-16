from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from .models import Scenario


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


def load_catalog(directory: Path) -> list[Scenario]:
    paths = sorted([*directory.glob("*.yaml"), *directory.glob("*.yml"), *directory.glob("*.json")])
    if not paths:
        raise ValueError(f"no scenarios found in {directory}")
    scenarios = [load_scenario(path) for path in paths]
    identifiers = [scenario.scenario_id for scenario in scenarios]
    if len(identifiers) != len(set(identifiers)):
        raise ValueError("scenario_id values must be unique")
    return scenarios
