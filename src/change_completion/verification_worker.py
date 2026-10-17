"""Trusted bounded verifier entry point. No source or user Python execution."""
import resource
import sys
from pathlib import Path
resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (1_000_000, 1_000_000))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import json
from datetime import datetime
from change_completion.models import TransitionSpec, ContentRef, AuthorityGrant
from change_completion.verification import TrustPolicy, verify_observations

def main():
    raw = sys.stdin.buffer.read(4_000_001)
    if len(raw) > 4_000_000: raise ValueError("input limit")
    data = json.loads(raw)
    p = data["policy"]
    policy = TrustPolicy(frozenset(p["approved_suite_digests"]), frozenset(p["approved_owners"]),
        tuple(AuthorityGrant.model_validate(g) for g in p["grants"]), frozenset(p["revoked_grant_ids"]), p["minimum_cases"])
    result = verify_observations(TransitionSpec.model_validate(data["spec"]), ContentRef.model_validate(data["candidate"]),
        data["suite"].encode(), data["observations"].encode(), policy, at=datetime.fromisoformat(data["at"]), actor=data["actor"])
    sys.stdout.write(result.model_dump_json())

if __name__ == "__main__": main()
