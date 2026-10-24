"""Fixed argv CLI transport. No shell, inherited credentials, or model configuration.

The demo runs the core it ships: by default the `agent_graph` package this
application imports. Before the first command the subprocess reports
`core_identity` (profile, output schema and a digest of the core files it
actually loaded) and it must equal the application's own core. An external
checkout of another commit therefore fails closed instead of being tested in
place of the shipped core. One process serves one core command; citations are
validated in one `evidence_batch` process per job, never one per citation.
"""

import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time

import agent_graph

from .contracts import PROFILE, DemoError
from .snapshots import atomic_json

COMMANDS = {"prepare_context", "analyze_change", "dependencies", "evidence", "evidence_batch", "propose",
            "report_check", "core_identity"}
OUTPUT_LIMIT = 2_097_152


def bundled_core_root():
    """Directory that holds the agent_graph package this application imports."""
    return Path(agent_graph.__file__).resolve().parents[1]


class GraphCLI:
    def __init__(self, core_root=None, python=sys.executable):
        # core_root keeps the old meaning "checkout whose src/ holds agent_graph".
        if core_root is None:
            source = bundled_core_root()
        else:
            source = Path(core_root) / "src"
            if not (source / "agent_graph" / "__init__.py").is_file():
                raise DemoError("core_pin_mismatch", 503)
        self.source, self.python = source, str(python)
        self.expected = agent_graph.core_identity()
        self.verified = None
        self.processes = 0  # started core processes; lets tests prove there is no per-citation fan-out

    def _env(self):
        env = {"PATH": os.defpath, "PYTHONPATH": str(self.source), "PYTHONDONTWRITEBYTECODE": "1",
               "LANG": "C.UTF-8"}
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
        return env

    def _verify(self, *, deadline, cancelled):
        if self.verified is None:
            identity = self._run([self.python, "-m", "agent_graph", "core_identity"], Path(self.source),
                                 deadline=deadline, cancelled=cancelled)
            self.verified = identity == self.expected
        if not self.verified:
            raise DemoError("core_pin_mismatch", 503)

    def identity(self):
        return dict(self.expected)

    def invoke(self, session_root, command, *, context=None, message=None, task="", deadline, cancelled):
        if command not in COMMANDS - {"core_identity"}:
            raise DemoError("model_unavailable" if command == "investigate" else "command_forbidden", 503)
        root = Path(session_root)
        args = [self.python, "-m", "agent_graph", "--policy", str(root / "policy.json"),
                "--state", str(root / "core-state"), command]
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
        self._verify(deadline=deadline, cancelled=cancelled)
        value = self._run(args, root, deadline=deadline, cancelled=cancelled)
        if "profile" in value and value["profile"] != PROFILE:
            raise DemoError("core_profile_mismatch")
        return value

    def _run(self, args, cwd, *, deadline, cancelled):
        if cancelled():
            raise DemoError("cancelled")
        if time.monotonic() >= deadline:
            raise DemoError("deadline_exceeded")
        extra = (dict(start_new_session=True) if os.name == "posix"
                 else dict(creationflags=subprocess.CREATE_NEW_PROCESS_GROUP))
        proc = subprocess.Popen(args, env=self._env(), stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL, cwd=cwd, **extra)
        self.processes += 1
        output, overflow = bytearray(), threading.Event()

        def pump():
            # A thread instead of selectors: Windows cannot select on pipes.
            while True:
                chunk = proc.stdout.read1(65536) if hasattr(proc.stdout, "read1") else proc.stdout.read(65536)
                if not chunk:
                    return
                output.extend(chunk)
                if len(output) > OUTPUT_LIMIT:
                    overflow.set()
                    return

        reader = threading.Thread(target=pump, daemon=True)
        reader.start()
        try:
            while reader.is_alive() or proc.poll() is None:
                if cancelled():
                    raise DemoError("cancelled")
                if time.monotonic() >= deadline:
                    raise DemoError("deadline_exceeded")
                if overflow.is_set():
                    raise DemoError("cli_output_limit")
                reader.join(min(0.05, max(0, deadline - time.monotonic())))
                if not reader.is_alive():
                    try:
                        proc.wait(timeout=max(0.001, min(0.05, deadline - time.monotonic())))
                    except subprocess.TimeoutExpired:
                        continue
            if overflow.is_set():
                raise DemoError("cli_output_limit")
            try:
                value = json.loads(output, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
                if not isinstance(value, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise DemoError("cli_invalid_json") from None
            if proc.returncode or value.get("status") == "ERROR":
                code = value.get("code", "cli_failed")
                raise DemoError(code if isinstance(code, str) and code.replace("_", "").isalnum() else "cli_failed")
            return value
        finally:
            if proc.poll() is None:
                _terminate(proc)
            reader.join(1)
            proc.stdout.close()


def _terminate(proc):
    if os.name == "posix":
        os.killpg(proc.pid, signal.SIGTERM)
        try:
            proc.wait(timeout=0.5)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
    else:
        proc.kill()  # the core CLI starts no children
        proc.wait()
