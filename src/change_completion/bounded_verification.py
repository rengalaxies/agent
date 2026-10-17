"""Verification supervisor. Trusted Python verifier, never candidate Python."""
from datetime import datetime
import json
from pathlib import Path
import subprocess
import sys
import tempfile

from .models import ContentRef, TransitionSpec
from .verification import VerificationReport, context_digest


def bounded_verify(spec, candidate, suite_bytes, observation_bytes, policy, *, at, actor, timeout_seconds=5):
    def stopped(reason):
        return VerificationReport(transition_id=spec.transition_id, candidate_sha256=candidate.sha256,
            context_sha256=context_digest(spec), suite_sha256=None, observations_sha256=None,
            checked_at=at, status="STOP", reason_codes=(reason,), cases=())
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 30:
        return stopped("VERIFIER_INVALID_TIMEOUT")
    try:
        payload = json.dumps({"spec": spec.model_dump(mode="json"), "candidate": candidate.model_dump(mode="json"),
            "suite": suite_bytes.decode(), "observations": observation_bytes.decode(),
            "policy": {"approved_suite_digests": list(policy.approved_suite_digests),
                "approved_owners": list(policy.approved_owners), "grants": [g.model_dump(mode="json") for g in policy.grants],
                "revoked_grant_ids": list(policy.revoked_grant_ids), "minimum_cases": policy.minimum_cases},
            "at": at.isoformat(), "actor": actor}, allow_nan=False).encode()
        if len(payload) > 4_000_000:
            return stopped("VERIFIER_INPUT_LIMIT")
        with tempfile.TemporaryDirectory() as cwd, tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
            process = subprocess.Popen([sys.executable, "-I", str(Path(__file__).with_name("verification_worker.py"))],
                stdin=subprocess.PIPE, stdout=out, stderr=err, cwd=cwd,
                env={"LANG": "C", "LC_ALL": "C"}, close_fds=True, start_new_session=True)
            try:
                process.communicate(payload, timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill(); process.communicate()
                if process.stdin: process.stdin.close()
                return stopped("VERIFIER_WALL_TIME_LIMIT")
            if process.stdin: process.stdin.close()
            if process.returncode:
                return stopped("VERIFIER_WORKER_FAILED")
            out.seek(0); response = out.read(1_000_001)
            if len(response) > 1_000_000:
                return stopped("VERIFIER_OUTPUT_LIMIT")
            report = VerificationReport.model_validate_json(response)
            if (report.transition_id != spec.transition_id or report.candidate_sha256 != candidate.sha256
                    or report.context_sha256 != context_digest(spec)):
                return stopped("VERIFIER_BINDING_MISMATCH")
            return report
    except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
        return stopped("VERIFIER_UNAVAILABLE")
