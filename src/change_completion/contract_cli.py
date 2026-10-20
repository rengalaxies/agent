"""Offline generate/check/bundle entry point for a replaceable contract profile."""
import argparse
import json
from pathlib import Path

from .contract_profile import check_profile, generate_candidate
from .git_bundle import export_review_bundle
from .verification import load_json


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate")
    generate.add_argument("--source", type=Path, required=True)
    generate.add_argument("--output", type=Path, required=True)
    generate.add_argument("--changes", type=Path, required=True)
    check = commands.add_parser("check")
    check.add_argument("--repository", type=Path, required=True)
    check.add_argument("--suite", type=Path, required=True)
    check.add_argument("--approved-suite-sha256", required=True)
    bundle = commands.add_parser("bundle")
    bundle.add_argument("--baseline", type=Path, required=True)
    bundle.add_argument("--candidate", type=Path, required=True)
    bundle.add_argument("--paths", nargs="+", required=True)
    bundle.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "generate":
            with args.changes.open("rb") as handle:
                changes_bytes = handle.read(1_000_001)
            report = generate_candidate(args.source, args.output, load_json(changes_bytes))
        elif args.command == "check":
            with args.suite.open("rb") as handle:
                suite = handle.read(1_000_001)
            report = check_profile(args.repository, suite, args.approved_suite_sha256)
        else:
            report = export_review_bundle(args.baseline, args.candidate, args.paths, args.output)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["status"] in {"PASS", "PREPARED", "EXPORTED"} else 1
    except (OSError, ValueError, TypeError) as exc:
        print(json.dumps({"status": "STOP", "reason_codes": [str(exc)[:160]]}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
