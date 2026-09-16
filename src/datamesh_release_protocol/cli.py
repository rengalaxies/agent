from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
import time
from pathlib import Path

from . import __version__
from .engine import ReleaseEngine
from .loaders import (
    load_baseline_policy,
    load_catalog,
    load_oracle_catalog,
    validate_oracle_coverage,
)
from .metrics import build_metrics_report
from .models import ScenarioRunResult, ValidationMode


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _catalog_hash(directory: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(directory.glob("*.yaml")):
        digest.update(path.name.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _files_hash(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths, key=lambda item: item.as_posix()):
        digest.update(path.as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def run_catalog(
    scenarios_dir: Path,
    baseline_path: Path,
    output: Path,
    manifest: Path,
    oracle_path: Path | None = None,
    metrics_path: Path | None = None,
) -> int:
    scenarios = load_catalog(scenarios_dir)
    baseline_policy = load_baseline_policy(baseline_path)
    engine = ReleaseEngine(baseline_policy)
    modes = list(ValidationMode)
    results: list[ScenarioRunResult] = []
    for scenario in scenarios:
        for mode in modes:
            started = time.perf_counter_ns()
            release = engine.run(scenario, mode, run_id="pilot-v1")
            duration_ms = (time.perf_counter_ns() - started) / 1_000_000
            results.append(
                ScenarioRunResult(
                    scenario_id=scenario.scenario_id,
                    mode=mode,
                    actual_decision=release.decision,
                    duration_ms=duration_ms,
                    release=release,
                )
            )
    oracles = None
    if oracle_path is not None:
        oracles = load_oracle_catalog(oracle_path)
        validate_oracle_coverage(scenarios, oracles)
        for result in results:
            expected = oracles[result.scenario_id].expected_decision
            result.expected_decision = expected
            result.matches_expected = result.actual_decision == expected
    _write_json(
        output,
        [result.model_dump(mode="json", exclude_none=True) for result in results],
    )
    manifest_payload = {
        "run_id": "pilot-v1",
        "protocol_version": __version__,
        "scenario_count": len(scenarios),
        "mode_count": len(modes),
        "result_count": len(results),
        "scenario_catalog_sha256": _catalog_hash(scenarios_dir),
        "baseline_policy_sha256": _file_hash(baseline_path),
        "oracle_sha256": _file_hash(oracle_path) if oracle_path is not None else None,
        "implementation_sha256": _files_hash(
            [*Path("src").rglob("*.py"), Path("services/api.py")]
        ),
        "schema_bundle_sha256": _files_hash(list(Path("schemas").glob("*.json"))),
        "metrics_definition_sha256": _file_hash(Path("docs/metrics-0.3.0.md")),
        "scenario_files": {
            path.name: _file_hash(path)
            for path in sorted(scenarios_dir.glob("*.yaml"))
        },
        "python_version": platform.python_version(),
        "platform": platform.platform(),
        "dependency_versions": {
            "pydantic": importlib.metadata.version("pydantic"),
            "PyYAML": importlib.metadata.version("PyYAML"),
        },
        "expected_labels_exposed_to_validators": False,
        "oracle_loaded_after_all_validator_runs": oracle_path is not None,
    }
    _write_json(manifest, manifest_payload)
    if oracles is None:
        summary = {
            mode.value: {
                "total": sum(1 for result in results if result.mode == mode),
                "scored": False,
            }
            for mode in modes
        }
    else:
        summary = build_metrics_report(results, oracles)
        if metrics_path is not None:
            _write_json(metrics_path, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Data Mesh release protocol runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run-catalog", help="run every scenario through every mode")
    run.add_argument("--scenarios", type=Path, required=True)
    run.add_argument("--baseline", type=Path, required=True)
    run.add_argument("--oracle", type=Path)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--metrics", type=Path)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run-catalog":
        raise SystemExit(
            run_catalog(
                scenarios_dir=args.scenarios,
                baseline_path=args.baseline,
                output=args.output,
                manifest=args.manifest,
                oracle_path=args.oracle,
                metrics_path=args.metrics,
            )
        )
    raise SystemExit(2)


if __name__ == "__main__":
    sys.exit(main())
