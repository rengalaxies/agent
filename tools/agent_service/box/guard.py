"""Stable manager-owned entry for both current and known legacy service releases.

The old release stays immutable. Calling its own box/launch directly bypasses
this supported path; it has not been retroactively made safe.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
import ctypes

MANAGER = Path(__file__).resolve().parents[4]
sys.path[:0] = [str(MANAGER / "app/src"), str(MANAGER / "app")]


def run_preflight(command):
    if not sys.platform.startswith("linux"):
        raise RuntimeError("guarded_recovery_requires_linux")
    parent = os.getpid()
    libc = ctypes.CDLL(None, use_errno=True)

    def parent_death():
        # Linux deployment only. Also close the fork/parent-death race before
        # the interpreter opens any state. An orphan must not write during restore.
        if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != parent:
            os._exit(1)

    child = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, preexec_fn=parent_death)

    def stop_child(signum, frame):
        child.terminate()
        try:
            child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()
        raise SystemExit(128 + signum)

    previous = signal.signal(signal.SIGTERM, stop_child)
    try:
        stdout, stderr = child.communicate(timeout=300)
        return subprocess.CompletedProcess(command, child.returncode, stdout, stderr)
    except BaseException:
        if child.poll() is None:
            child.kill()
            child.wait()
        raise
    finally:
        signal.signal(signal.SIGTERM, previous)


def main():
    from tools.agent_service.box import recovery, release, state
    from tools.agent_service.box.layout import venv_python

    parser = argparse.ArgumentParser()
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--run", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", required=True)
    args = parser.parse_args()
    manifest, digest = release.verify_tree(args.target, wheels=False)
    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    if (cfg.get("analysis") or {}).get("code_version") != manifest["release_id"]:
        raise release.ReleaseError("recovery_configuration_mismatch")
    root = Path(cfg["state_path"]).parents[1]
    if state.restore_unfinished(root):
        raise release.ReleaseError("restore_unfinished")
    value = recovery.check_start(root, manifest, digest)
    ok, _ = state.compatible(manifest["contracts"]["state"], state.schemas(root))
    if not ok:
        raise release.ReleaseError("state_schema_mismatch")
    # This program runs with target imports in a separate interpreter. It may
    # recover/enqueue but never calls step(), run_until_idle() or any publisher.
    if value.get("reconcile_required"):
        check = run_preflight([str(venv_python(args.target / "venv")), "-I", "-B",
                                str(MANAGER / "app/tools/agent_service/box/preflight.py"),
                                str(args.target), str(args.config), digest,
                                value.get("recovery_token", "update")])
        if check.returncode:
            # Only safe reason codes; never copy arbitrary connector exception text.
            try:
                code = json.loads(check.stdout)["code"]
            except (ValueError, KeyError):
                code = "recovery_preflight_crashed"
            print(f"recovery_reconciliation_failed:{code}: publisher remains stopped", flush=True)
            return 1
    command = [str(venv_python(args.target / "venv")), "-I", "-B",
               str(args.target / "app/tools/agent_service/box/launch.py"),
               "--config", str(args.config), "--run", args.run, "--host", args.host, "--port", args.port]
    os.execv(command[0], command)


if __name__ == "__main__":
    raise SystemExit(main())
