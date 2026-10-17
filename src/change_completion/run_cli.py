"""Run the internal SQL profile, or inspect its private local history."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path

from .adapters import read_repository_file
from .models import TransitionSpec
from .providers import ClientPatchProvider
from .runtime import run_transition
from .store import RunStore
from .verification import TrustPolicy, load_json
from .verify_cli import TrustConfig


def operator_path(value):
    path = Path(value).absolute()
    if any(parent.is_symlink() for parent in (path, *path.parents)):
        raise ValueError("operator_path_symlink")
    return path


def read_operator_file(value):
    path = operator_path(value)
    return read_repository_file(path.parent, path.name)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    run = subs.add_parser("run")
    for key in ("repository", "transition", "expectations", "fixtures", "trust", "state", "actor"):
        run.add_argument("--"+key, required=True)
    run.add_argument("--retry-of", help="Failed run retained as immutable parent")
    run.add_argument("--retry-key", help="Operator idempotency key for this explicit attempt")
    run.add_argument("--provider-config", help="Explicit operator-owned HTTP gateway configuration")
    run.add_argument("--at", help="Synthetic demo clock only; not for production authorization")
    history = subs.add_parser("history")
    history.add_argument("--state", required=True)
    history.add_argument("--run-id", required=True)
    recover = subs.add_parser("reconcile")
    for key in ("state", "run-id", "actor", "reason"):
        recover.add_argument("--"+key, required=True)
    recover.add_argument("--worker-stopped", action="store_true")
    args = parser.parse_args(argv)
    try:
        state = operator_path(args.state)
        if args.command == "reconcile":
            print(json.dumps(RunStore(state / "runs.sqlite3").reconcile_interrupted(args.run_id, actor=args.actor, reason=args.reason, worker_stopped=args.worker_stopped)))
            return 0
        if args.command == "history":
            if not (state / "runs.sqlite3").is_file():
                raise KeyError("unknown_state")
            print(json.dumps(RunStore(state / "runs.sqlite3").get(args.run_id), ensure_ascii=False, indent=2))
            return 0
        repository = operator_path(args.repository)
        if state.resolve().is_relative_to(repository.resolve()):
            raise ValueError("state_must_be_outside_repository")
        # The candidate repository cannot set its expectations, policy or fixtures.
        for item in (args.transition, args.expectations, args.trust, args.fixtures, args.provider_config):
            if item and operator_path(item).resolve().is_relative_to(repository.resolve()):
                raise ValueError("control_artifact_inside_repository")
        spec = TransitionSpec.model_validate(load_json(read_operator_file(args.transition)))
        suite = read_operator_file(args.expectations)
        fixture_root = operator_path(args.fixtures)

        def policy_loader():
            config = TrustConfig.model_validate(load_json(read_operator_file(args.trust)))
            return TrustPolicy(**{k: getattr(config, k) for k in TrustConfig.model_fields})

        provider = None
        if args.provider_config:
            config = load_json(read_operator_file(args.provider_config))
            allowed = {"endpoint", "model", "allowed_endpoints", "allow_source_transfer", "allow_loopback_http", "key_env", "timeout_seconds"}
            if not set(config) <= allowed:
                raise ValueError("unknown_provider_config")
            env = config.pop("key_env", None)
            if env:
                config["api_key"] = os.environ.get(env)
                if not config["api_key"]:
                    raise ValueError("model_credential_unavailable")
            config["allowed_endpoints"] = frozenset(config.get("allowed_endpoints", []))
            provider = ClientPatchProvider(**config)
        kwargs = {}
        if args.at:
            at = datetime.fromisoformat(args.at)
            kwargs["clock"] = lambda: at
        result = run_transition(repository, spec, suite,
                                lambda uri: read_repository_file(fixture_root, uri), policy_loader,
                                RunStore(state / "runs.sqlite3"), actor=args.actor, provider=provider, retry_of=args.retry_of, retry_key=args.retry_key, **kwargs)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return {"READY_FOR_REVIEW": 0, "FAIL": 1, "STOP": 2}[result["status"]]
    except (OSError, ValueError, TypeError, KeyError, RuntimeError):
        print(json.dumps({"status": "STOP", "reason_codes": ["invalid_or_unavailable_operator_input"], "effects_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
