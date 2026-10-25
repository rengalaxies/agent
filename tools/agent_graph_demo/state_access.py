"""Fixed operator journal operations under the web UID; never root-owned SQLite WAL files."""

import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

from agent_graph_demo.contracts import DemoError, canonical
from agent_graph_demo.store import Store

APP_UID = APP_GID = 10001


def effective_uid():
    """None where the OS has no POSIX UIDs (Windows development); never treated as root."""
    return os.geteuid() if hasattr(os, "geteuid") else None


class StateAccess:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def request(self, operation, sid, value=None):
        sid = str(uuid.UUID(sid))
        if operation not in ("session", "receipt", "external_report"):
            raise DemoError("state_operation_forbidden")
        if effective_uid() == 0:
            release = Path(__file__).resolve().parents[2]
            env = {
                "PATH": os.defpath,
                "PYTHONPATH": str(release / "src") + os.pathsep + str(release),
                "PYTHONDONTWRITEBYTECODE": "1",
                "LANG": "C.UTF-8",
            }
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "tools.agent_graph_demo.state_access",
                    operation,
                    str(self.root),
                    sid,
                ],
                input=canonical(value),
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=15,
                env=env,
                user=APP_UID,
                group=APP_GID,
                extra_groups=[APP_GID],
            )
            if result.returncode or len(result.stdout) > 2_000_000:
                raise DemoError("app_state_access_failed")
            try:
                return json.loads(result.stdout)
            except ValueError:
                raise DemoError("app_state_access_failed") from None
        store = Store(self.root)
        if operation == "session":
            return store.session(sid)
        store.session(sid)
        return store.artifact(sid, operation, value)

    def session(self, sid):
        return self.request("session", sid)

    def artifact(self, sid, kind, value):
        return self.request(kind, sid, value)


if __name__ == "__main__":
    try:
        if effective_uid() == 0:
            raise DemoError("helper_must_run_as_app_user")
        print(
            canonical(
                StateAccess(sys.argv[2]).request(
                    sys.argv[1], sys.argv[3], json.loads(sys.stdin.read(2_000_000))
                )
            )
        )
    except (DemoError, ValueError, OSError, IndexError):
        raise SystemExit(2)
