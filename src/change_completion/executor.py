"""Bounded execution of the internal SQLite SELECT profile.

This is a restricted SQL language runner, not a general OS/code sandbox.
Only the trusted worker runs as Python; candidates are never Python programs.
"""
import json
import math
from pathlib import Path
import os
import subprocess
import sys
import tempfile

MAX_INPUT_BYTES = 1_000_000
MAX_OUTPUT_BYTES = 1_000_000


def _result(status, reason):
    return {"status": status, "actual": None, "reason_codes": [reason]}


def execute_select(sql: str, fixture: dict, *, timeout_seconds=2) -> dict:
    """Execute one SELECT with bounded fixtures, output and wall time."""
    if (type(sql) is not str or not sql.strip() or len(sql) > 65_536
            or type(fixture) is not dict):
        return _result("unsupported", "invalid_input")
    if (type(timeout_seconds) not in (int, float) or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 30):
        return _result("unsupported", "invalid_timeout")
    try:
        payload = json.dumps({"sql": sql, "fixture": fixture}, allow_nan=False).encode()
    except (ValueError, TypeError, RecursionError):
        return _result("unsupported", "invalid_input")
    if len(payload) > MAX_INPUT_BYTES:
        return _result("unsupported", "input_limit")
    worker = Path(__file__).with_name("sql_worker.py").resolve()
    try:
        with tempfile.TemporaryDirectory(prefix="change-select-") as cwd:
            # Worker writes only a bounded JSON response. File-backed output avoids
            # communicate() buffering an arbitrary stdout stream in the parent.
            with tempfile.TemporaryFile() as output, tempfile.TemporaryFile() as errors:
                proc = subprocess.Popen(
                    [sys.executable, "-I", "-S", str(worker)], stdin=subprocess.PIPE,
                    stdout=output, stderr=errors, cwd=cwd, close_fds=True,
                    env={"LC_ALL": "C", "LANG": "C"}, start_new_session=True,
                )
                try:
                    proc.communicate(payload, timeout=timeout_seconds)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.communicate()
                    if proc.stdin is not None:
                        proc.stdin.close()
                    return _result("timeout", "wall_time_limit")
                if proc.returncode != 0:
                    return _result("error", "worker_failed")
                output.seek(0)
                raw = output.read(MAX_OUTPUT_BYTES + 1)
                if len(raw) > MAX_OUTPUT_BYTES:
                    return _result("unsupported", "output_limit")
                result = json.loads(raw)
                if (type(result) is not dict or result.get("status") not in
                        {"executed", "error", "timeout", "unsupported"}):
                    return _result("error", "invalid_worker_response")
                return result
    except (OSError, ValueError, RecursionError):
        return _result("error", "worker_unavailable")
