"""Disposable-container test of root operator/app UID boundaries, without Docker socket or core calls."""

import os
from pathlib import Path
import subprocess
import sys
import uuid

from agent_graph_demo.contracts import canonical
from tools.agent_graph_demo.runtime_guard import RuntimeGuard
from tools.agent_graph_demo.state_access import APP_GID, APP_UID, StateAccess


def main():
    if os.geteuid() != 0:
        raise RuntimeError(
            "Run only as simulated operator inside disposable acceptance container"
        )
    base = Path("/packaging")
    state = base / "state"
    state.mkdir(mode=0o700)
    os.chown(state, APP_UID, APP_GID)
    sid = str(uuid.uuid4())
    env = {
        "PATH": os.defpath,
        "PYTHONPATH": "/app/src:/app",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    child = """
import sys,time
from pathlib import Path
from agent_graph_demo.snapshots import Snapshots
from agent_graph_demo.store import Store
root=Path(sys.argv[1]);sid=sys.argv[2];store=Store(root)
store.create(sid,'explicit-packaging-fixture',Snapshots(root,'TEST').create(sid))
connection=store.connect();connection.execute('SELECT * FROM sessions').fetchall()
print('READY',flush=True)
time.sleep(60)
"""
    proc = subprocess.Popen(
        [sys.executable, "-c", child, str(state), sid],
        env=env,
        user=APP_UID,
        group=APP_GID,
        extra_groups=[APP_GID],
        stdout=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout.readline().strip() == "READY"
        guard = RuntimeGuard(state, base / "runtime", "sha256:" + "1" * 64, "TEST")
        with guard.exclusive():
            guard.write(guard.read(), "STOPPED")
        access = StateAccess(state)
        assert access.session(sid)["owner"] == "explicit-packaging-fixture"
        access.artifact(
            sid, "receipt", {"id": "explicit-packaging-fixture", "status": "TEST_ONLY"}
        )
        assert all(f.stat().st_uid == APP_UID for f in state.glob("web.sqlite*"))
        assert (state / "workload.lock").stat().st_uid == APP_UID
        registry = guard.registry.stat()
        assert (
            registry.st_uid == 0
            and registry.st_gid == APP_GID
            and registry.st_mode & 0o777 == 0o640
        )
        verify = """
import json,sys
from pathlib import Path
from agent_graph_demo.store import Store
root=Path(sys.argv[1]);sid=sys.argv[2]
assert Store(root/'state').artifacts(sid,'receipt')[0]['status']=='TEST_ONLY'
assert json.loads((root/'runtime/active.json').read_text())['state']=='STOPPED'
print('PASS')
"""
        out = subprocess.check_output(
            [sys.executable, "-c", verify, str(base), sid],
            env=env,
            user=APP_UID,
            group=APP_GID,
            extra_groups=[APP_GID],
            text=True,
        )
        assert out.strip() == "PASS"
        print(
            canonical(
                {
                    "status": "PASS",
                    "scope": "root operator / app UID SQLite-WAL and registry permissions; explicit test fixtures; no core/model calls",
                }
            )
        )
    finally:
        proc.terminate()
        proc.wait(timeout=5)
        proc.stdout.close()


if __name__ == "__main__":
    main()
