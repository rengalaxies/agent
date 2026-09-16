from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
import sys
from pathlib import Path

from . import __version__
from .engine import ReleaseEngine
from .loaders import load_catalog
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


def run_catalog(scenarios_dir: Path, output: Path, manifest: Path) -> int:
    scenarios = load_catalog(scenarios_dir)
    engine = ReleaseEngine()
    modes = list(ValidationMode)
    results: list[ScenarioRunResult] = []
    for scenario in scenarios:
        for mode in modes:
            release = engine.run(scenario, mode, run_id="pilot-v1")
            results.append(
                ScenarioRunResult(
                    scenario_id=scenario.scenario_id,
                    mode=mode,
                    expected_decision=scenario.expected_decision,
                    actual_decision=release.decision,
                    matches_expected=release.decision == scenario.expected_decision,
                    release=release,
                )
            )
    _write_json(output, [result.model_dump(mode="json") for result in results])
    manifest_payload = {
        "run_id": "pilot-v1",
        "protocol_version": __version__,
        "scenario_count": len(scenarios),
        "mode_count": len(modes),
        "result_count": len(results),
        "scenario_catalog_sha256": _catalog_hash(scenarios_dir),
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
    }
    _write_json(manifest, manifest_payload)
    summary = {
        mode.value: {
            "matches": sum(result.matches_expected for result in results if result.mode == mode),
            "total": sum(1 for result in results if result.mode == mode),
        }
        for mode in modes
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Data Mesh release protocol runner")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run-catalog", help="run every scenario through every mode")
    run.add_argument("--scenarios", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--manifest", type=Path, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "run-catalog":
        raise SystemExit(run_catalog(args.scenarios, args.output, args.manifest))
    raise SystemExit(2)


if __name__ == "__main__":
    sys.exit(main())
