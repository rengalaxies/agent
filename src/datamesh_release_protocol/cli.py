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


PURPOSES = ("development_regression", "confirmatory_e3")


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


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
    run_id: str,
    purpose: str = "development_regression",
) -> int:
    if purpose not in PURPOSES:
        raise ValueError(f"unsupported experiment purpose: {purpose}")
    scenarios = load_catalog(scenarios_dir)
    baseline_policy = load_baseline_policy(baseline_path)
    engine = ReleaseEngine(baseline_policy)
    modes = list(ValidationMode)
    results: list[ScenarioRunResult] = []
    for scenario in scenarios:
        for mode in modes:
            started = time.perf_counter_ns()
            release = engine.run(scenario, mode, run_id=run_id)
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
    _write_json(
        output,
        [result.model_dump(mode="json", exclude_none=True) for result in results],
    )
    manifest_payload = {
        "artifact_kind": "validator_run_manifest",
        "status": "validators_completed_unscored",
        "run_id": run_id,
        "purpose": purpose,
        "protocol_version": __version__,
        "scenario_count": len(scenarios),
        "mode_count": len(modes),
        "result_count": len(results),
        "scenario_catalog_sha256": _catalog_hash(scenarios_dir),
        "baseline_policy_sha256": _file_hash(baseline_path),
        "raw_results_sha256": _file_hash(output),
        "oracle_sha256": None,
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
        "oracle_loaded_by_validator_process": False,
    }
    _write_json(manifest, manifest_payload)
    summary = {
        mode.value: {
            "total": sum(1 for result in results if result.mode == mode),
            "scored": False,
        }
        for mode in modes
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _load_unscored_results(path: Path) -> list[ScenarioRunResult]:
    payload = _read_json(path)
    if not isinstance(payload, list):
        raise ValueError("raw results root must be an array")
    for index, item in enumerate(payload):
        if not isinstance(item, dict):
            raise ValueError(f"raw result {index} must be an object")
        forbidden = {"expected_decision", "matches_expected"} & set(item)
        if forbidden:
            raise ValueError(
                f"raw result {index} contains scoring fields: {sorted(forbidden)}"
            )
    return [ScenarioRunResult.model_validate(item) for item in payload]


def _validate_run_chain(
    results: list[ScenarioRunResult],
    scenarios_dir: Path,
    run_manifest: dict[str, object],
) -> None:
    if run_manifest.get("artifact_kind") != "validator_run_manifest":
        raise ValueError("unexpected run manifest artifact_kind")
    if run_manifest.get("status") != "validators_completed_unscored":
        raise ValueError("run manifest is not ready for scoring")
    if run_manifest.get("oracle_sha256") is not None:
        raise ValueError("validator run manifest must not contain an oracle hash")
    if run_manifest.get("oracle_loaded_by_validator_process") is not False:
        raise ValueError("validator process oracle isolation is not proven")
    if run_manifest.get("scenario_catalog_sha256") != _catalog_hash(scenarios_dir):
        raise ValueError("scenario catalog hash differs from the validator run")

    scenarios = load_catalog(scenarios_dir)
    expected_pairs = {
        (scenario.scenario_id, mode)
        for scenario in scenarios
        for mode in ValidationMode
    }
    actual_pairs = [(result.scenario_id, result.mode) for result in results]
    if len(actual_pairs) != len(set(actual_pairs)):
        raise ValueError("raw results contain duplicate scenario-mode pairs")
    if set(actual_pairs) != expected_pairs:
        raise ValueError("raw results do not cover every scenario-mode pair exactly once")

    run_id = run_manifest.get("run_id")
    for result in results:
        proposal = result.release.proposal
        if proposal.run_id != run_id:
            raise ValueError("raw result run_id differs from the run manifest")
        if proposal.scenario_id != result.scenario_id or proposal.mode != result.mode:
            raise ValueError("raw result identity differs from its release proposal")


def score_results(
    raw_results_path: Path,
    run_manifest_path: Path,
    scenarios_dir: Path,
    oracle_path: Path,
    output: Path,
    metrics_path: Path,
    score_manifest_path: Path,
) -> int:
    if output.resolve() == raw_results_path.resolve():
        raise ValueError("scored output must not overwrite raw results")

    run_manifest_payload = _read_json(run_manifest_path)
    if not isinstance(run_manifest_payload, dict):
        raise ValueError("run manifest root must be an object")
    expected_raw_hash = run_manifest_payload.get("raw_results_sha256")
    actual_raw_hash = _file_hash(raw_results_path)
    if expected_raw_hash != actual_raw_hash:
        raise ValueError("raw results hash differs from the run manifest")

    results = _load_unscored_results(raw_results_path)
    _validate_run_chain(results, scenarios_dir, run_manifest_payload)

    scenarios = load_catalog(scenarios_dir)
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
    purpose = str(run_manifest_payload.get("purpose"))
    if purpose not in PURPOSES:
        raise ValueError(f"unsupported run manifest purpose: {purpose}")
    report = build_metrics_report(results, oracles, purpose=purpose)
    _write_json(metrics_path, report)

    score_manifest = {
        "artifact_kind": "score_manifest",
        "status": "scored_from_immutable_raw_results",
        "run_id": run_manifest_payload["run_id"],
        "purpose": purpose,
        "protocol_version": run_manifest_payload["protocol_version"],
        "raw_results_sha256": actual_raw_hash,
        "run_manifest_sha256": _file_hash(run_manifest_path),
        "oracle_sha256": _file_hash(oracle_path),
        "scored_results_sha256": _file_hash(output),
        "metrics_sha256": _file_hash(metrics_path),
        "expected_labels_exposed_to_validators": False,
        "oracle_loaded_by_scoring_process_only": True,
    }
    _write_json(score_manifest_path, score_manifest)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Data Mesh release protocol runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser(
        "run-catalog", help="run every scenario without loading an oracle"
    )
    run.add_argument("--scenarios", type=Path, required=True)
    run.add_argument("--baseline", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--purpose", choices=PURPOSES, required=True)

    score = subparsers.add_parser(
        "score-results", help="score an immutable raw result artifact"
    )
    score.add_argument("--raw-results", type=Path, required=True)
    score.add_argument("--run-manifest", type=Path, required=True)
    score.add_argument("--scenarios", type=Path, required=True)
    score.add_argument("--oracle", type=Path, required=True)
    score.add_argument("--output", type=Path, required=True)
    score.add_argument("--metrics", type=Path, required=True)
    score.add_argument("--score-manifest", type=Path, required=True)
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
                run_id=args.run_id,
                purpose=args.purpose,
            )
        )
    if args.command == "score-results":
        raise SystemExit(
            score_results(
                raw_results_path=args.raw_results,
                run_manifest_path=args.run_manifest,
                scenarios_dir=args.scenarios,
                oracle_path=args.oracle,
                output=args.output,
                metrics_path=args.metrics,
                score_manifest_path=args.score_manifest,
            )
        )
    raise SystemExit(2)


if __name__ == "__main__":
    sys.exit(main())
