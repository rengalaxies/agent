"""E4-N domain service / coordinator CLI. Secrets are only read from environment."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from datamesh_release_protocol.network import coordinate, serve
from run_e4 import three_domains


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="action", required=True)
    domain = sub.add_parser("serve")
    domain.add_argument("--domain", required=True, choices=["fintech", "retail", "mobility"])
    domain.add_argument("--host", default="127.0.0.1")
    domain.add_argument("--port", type=int, required=True)
    domain.add_argument("--key-env", required=True)
    domain.add_argument("--policy", type=Path, default=Path("policies/v1-ind.yaml"))
    run = sub.add_parser("run")
    run.add_argument("--config", type=Path, required=True)
    run.add_argument("--run-id", required=True)
    run.add_argument("--journal", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    run.add_argument("--timeout", type=float, default=2.0)
    run.add_argument("--delay-domain", choices=["fintech", "retail", "mobility"])
    run.add_argument("--delay-seconds", type=float, default=0)
    run.add_argument("--duplicate", action="store_true")
    args = parser.parse_args()
    if args.action == "serve":
        key = os.environ.get(args.key_env)
        if not key:
            parser.error(f"missing secret in environment: {args.key_env}")
        serve(args.domain, args.host, args.port, key, args.policy)
    else:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        endpoints = {domain: settings["url"] for domain, settings in config["domains"].items()}
        keys = {domain: os.environ.get(settings["key_env"], "") for domain, settings in config["domains"].items()}
        delays = {args.delay_domain: args.delay_seconds} if args.delay_domain else None
        result = coordinate(three_domains(), args.run_id, endpoints, keys, args.journal,
                            timeout_s=args.timeout, delays=delays, duplicate=args.duplicate)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{result['decision']}: {args.output}")


if __name__ == "__main__":
    main()
