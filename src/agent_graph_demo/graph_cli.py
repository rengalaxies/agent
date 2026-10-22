"""Fixed argv CLI transport. No shell, inherited credentials, or model configuration."""

import hashlib
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time

from .contracts import CORE_SHA, PROFILE, DemoError
from .snapshots import atomic_json

LOCK = Path(__file__).resolve().parents[2] / "infra/agent_graph_demo/core.lock.json"


class GraphCLI:
    def __init__(self, core_root, python=sys.executable):
        self.core_root, self.python = Path(core_root), str(python)
        lock = json.loads(LOCK.read_text())
        root = self.core_root / "src/agent_graph"
        actual = {
            str(f.relative_to(root)): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in root.rglob("*.py")
        }
        if lock["sha"] != CORE_SHA or actual != lock["files"]:
            raise DemoError("core_pin_mismatch", 503)

    def invoke(
        self,
        session_root,
        command,
        *,
        context=None,
        message=None,
        task="",
        deadline,
        cancelled,
    ):
        if command not in {
            "prepare_context",
            "analyze_change",
            "dependencies",
            "evidence",
            "propose",
            "report_check",
        }:
            raise DemoError(
                "model_unavailable"
                if command == "investigate"
                else "command_forbidden",
                503,
            )
        root = Path(session_root)
        args = [
            self.python,
            "-m",
            "agent_graph",
            "--policy",
            str(root / "policy.json"),
            "--state",
            str(root / "core-state"),
            command,
        ]
        if context:
            args += ["--context", context]
        if message is not None:
            atomic_json(root / "message.json", message)
            args += ["--input", str(root / "message.json")]
        if command == "prepare_context":
            # Current CLI caps task at 2000, while web contract permits 4000.
            # Reject rather than silently truncate user intent.
            if len(task) > 2000:
                raise DemoError("core_task_limit_2000", 422)
            args += ["--task", task]
        env = {
            "PATH": os.defpath,
            "PYTHONPATH": str(self.core_root / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "LANG": "C.UTF-8",
        }
        if cancelled():
            raise DemoError("cancelled")
        if time.monotonic() >= deadline:
            raise DemoError("deadline_exceeded")
        proc = subprocess.Popen(
            args,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            cwd=root,
        )
        output = bytearray()
        try:
            with selectors.DefaultSelector() as sel:
                sel.register(proc.stdout, selectors.EVENT_READ)
                while sel.get_map():
                    if cancelled():
                        raise DemoError("cancelled")
                    if time.monotonic() >= deadline:
                        raise DemoError("deadline_exceeded")
                    for key, _ in sel.select(
                        min(0.05, max(0, deadline - time.monotonic()))
                    ):
                        chunk = os.read(key.fd, 65536)
                        if not chunk:
                            sel.unregister(key.fileobj)
                        output.extend(chunk)
                        if len(output) > 2_097_152:
                            raise DemoError("cli_output_limit")
            proc.wait(timeout=max(0.001, deadline - time.monotonic()))
            try:
                value = json.loads(
                    output, parse_constant=lambda _: (_ for _ in ()).throw(ValueError())
                )
                if not isinstance(value, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise DemoError("cli_invalid_json") from None
            if proc.returncode or value.get("status") == "ERROR":
                code = value.get("code", "cli_failed")
                raise DemoError(
                    code
                    if isinstance(code, str) and code.replace("_", "").isalnum()
                    else "cli_failed"
                )
            if "profile" in value and value["profile"] != PROFILE:
                raise DemoError("core_profile_mismatch")
            return value
        except subprocess.TimeoutExpired:
            raise DemoError("deadline_exceeded") from None
        finally:
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGTERM)
                try:
                    proc.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    os.killpg(proc.pid, signal.SIGKILL)
                    proc.wait()
            proc.stdout.close()
