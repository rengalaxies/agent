"""JSON CLI transport for local developer/coding-agent subprocesses."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from pydantic import ValidationError

from .contracts import GraphError, Policy, load_json
from .engine import Graph
from .inference import investigate
from .store import Store
from . import core_identity


def markdown(value):
    # Plain text only. No HTML, links or instructions from source content rendered.
    lines = ["# Advisory graph result", "", f"Context/result: {value.get('id', value.get('context_id', ''))}"]
    for key in ("coverage", "freshness", "gaps", "unknowns", "findings", "dependencies"):
        if key in value:
            lines += ["", key, "", "```json", json.dumps(value[key], ensure_ascii=True, indent=2), "```"]
    lines += ["", "No tests executed by this module. Release remains a team decision."]
    return "\n".join(lines) + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--policy", help="Operator-owned configuration, outside analyzed sources (required)")
    p.add_argument("--state", help="Private directory (0700), one trusted OS user (required)")
    p.add_argument("--format", choices=["json", "markdown"], default="json")
    sub = p.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare_context")
    prep.add_argument("--task", default="")
    prep.add_argument("--operation")
    pin_help = "repository=commit for a git repository; repeatable. Never a branch or ref."
    prep.add_argument("--revision", action="append", default=[], help=pin_help)
    sub.add_parser("core_identity", help="Profile, schema versions and digest of the loaded core files")
    for command in ("dependencies", "evidence", "evidence_batch", "propose", "report_check", "investigate",
                    "analyze_change"):
        cmd = sub.add_parser(command)
        if command not in ("report_check", "evidence_batch"):
            cmd.add_argument("--context", required=True)
        if command in ("evidence", "evidence_batch", "propose", "report_check"):
            cmd.add_argument("--input", required=True, help="JSON message file; never an executable")
        if command == "dependencies":
            cmd.add_argument("--operation")
        if command == "analyze_change":
            cmd.add_argument("--revision", action="append", default=[], help=pin_help)
    args = p.parse_args(argv)
    store = None
    if args.command == "core_identity":
        print(json.dumps(core_identity(), ensure_ascii=True, sort_keys=True))
        return 0
    if not args.policy or not args.state:
        p.error("--policy and --state are required")
    try:
        policy = Policy.model_validate(load_json(Path(args.policy).read_text()))
        # Resolve operator-declared relative roots against the policy file, not cwd.
        for repo in policy.repositories:
            root = Path(repo.root)
            if not root.is_absolute():
                repo.root = str((Path(args.policy).absolute().parent / root).absolute())
        revisions = {}
        for pin in getattr(args, "revision", []):
            repo, sep, commit = pin.partition("=")
            if not sep or repo in revisions:
                raise GraphError("invalid_revision")
            revisions[repo] = commit
        store = Store(args.state)
        graph = Graph(policy, store)
        if args.command == "prepare_context":
            c = graph.prepare_context(args.task, args.operation, revisions or None)
            result = graph.dependencies(c["id"], args.operation)
        elif args.command == "dependencies":
            result = graph.dependencies(args.context, args.operation)
        elif args.command == "analyze_change":
            result = graph.analyze_change(args.context, revisions=revisions or None)
        elif args.command == "investigate":
            result = investigate(graph, args.context)
        else:
            value = load_json(Path(args.input).read_text())
            if args.command == "evidence":
                result = graph.get_evidence(args.context, value)
            elif args.command == "evidence_batch":
                result = graph.evidence_batch(value.get("items") if isinstance(value, dict) else None)
            elif args.command == "propose":
                result = graph.propose(args.context, value)
            else:
                result = graph.report_check(value)
        print(markdown(result) if args.format == "markdown" else json.dumps(result, ensure_ascii=True, allow_nan=False))
        return 0
    except (GraphError, ValidationError, OSError, ValueError, RecursionError) as exc:
        code = exc.code if isinstance(exc, GraphError) else "invalid_input_or_state"
        print(json.dumps(dict(status="ERROR", code=code)))
        return 2
    finally:
        if store:
            store.close()


if __name__ == "__main__":
    sys.exit(main())
