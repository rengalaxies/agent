"""Offline replay of supplied observations; never executes candidate code."""
import argparse
from datetime import datetime, timezone
from pathlib import Path
import json

from .models import AuthorityGrant, ContentRef, Contract, TransitionSpec
from .verification import MAX_BUNDLE_BYTES, TrustPolicy, digest_bytes, load_json, verify_observations


class TrustConfig(Contract):
    approved_suite_digests: frozenset[str]
    approved_owners: frozenset[str]
    grants: tuple[AuthorityGrant, ...]
    revoked_grant_ids: frozenset[str] = frozenset()
    minimum_cases: int = 2


def read_bounded(path: str) -> bytes:
    with Path(path).open("rb") as stream:
        payload = stream.read(MAX_BUNDLE_BYTES + 1)
    if len(payload) > MAX_BUNDLE_BYTES:
        raise ValueError("file limit")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("transition", "candidate", "expectations", "observations", "trust", "actor"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--at", help="Explicit replay clock (ISO8601); omit for current UTC")
    args = parser.parse_args(argv)
    try:
        spec = TransitionSpec.model_validate(load_json(read_bounded(args.transition)))
        trust = TrustConfig.model_validate(load_json(read_bounded(args.trust)))
        policy = TrustPolicy(**{name: getattr(trust, name) for name in TrustConfig.model_fields})
        candidate_bytes = read_bounded(args.candidate)
        candidate = ContentRef(uri=Path(args.candidate).name, sha256=digest_bytes(candidate_bytes))
        at = datetime.fromisoformat(args.at) if args.at else datetime.now(timezone.utc)
        result = verify_observations(spec, candidate, read_bounded(args.expectations),
                                     read_bounded(args.observations), policy, at=at, actor=args.actor)
        print(result.model_dump_json(indent=2))
        return {"PASS": 0, "FAIL": 1, "STOP": 2}[result.status]
    except (OSError, ValueError, TypeError, RecursionError):
        print(json.dumps({"status": "STOP", "reason_codes": ["INVALID_REPLAY_INPUT"],
                          "effects_authorized": False}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
