"""Local/CI disposable Docker + Chromium acceptance, never a deployment or model run."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import base64

from agent_graph_demo.contracts import CORE_SHA, PROFILE, DemoError, now
from agent_graph_demo.snapshots import atomic_json
from agent_graph_demo.store import Store
from tests.graph_demo.browser_acceptance import journey
from tests.graph_demo.operator_acceptance import guard_probes
from tools.agent_graph_demo.runtime_guard import RuntimeGuard
from tools.agent_graph_demo.run_scenario import run


def acceptance(core_root, image, output, product_sha="WORKTREE"):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    state = output / "state"
    runtime = output / "runtime"
    operator = dict(
        state_root=str(state),
        runtime_root=str(runtime),
        image=image,
        product_sha=product_sha,
    )
    guard = RuntimeGuard(state, runtime, image, product_sha)
    # Do not silently recover uncertain work or interfere with another installation.
    if guard.registry.exists():
        if guard.read()["state"] != "STOPPED":
            raise DemoError("previous_acceptance_needs_explicit_operator_stop")
        guard.refresh(guard.read()["generation"])
    else:
        guard.reconcile(0)
    password = secrets.token_urlsafe(24)
    auth = output / "auth.json"
    atomic_json(
        auth,
        {
            "users": [
                dict(
                    subject="acceptance",
                    role="operator",
                    password_sha256=hashlib.sha256(password.encode()).hexdigest(),
                )
            ]
        },
    )
    auth.chmod(0o600)
    web = output / "web.json"
    atomic_json(
        web,
        dict(
            state_root=str(state),
            core_root=str(Path(core_root).resolve()),
            auth_config_path=str(auth),
            runtime_registry_path=str(guard.registry),
            product_sha=product_sha,
            allowed_origins=["http://127.0.0.1:18081"],
        ),
    )
    log = (output / "backend.log").open("w")
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "PYTHONPATH", "LANG")}
    env["PYTHONPATH"] = str(Path.cwd() / "src") + os.pathsep + str(Path.cwd())
    proc = subprocess.Popen(
        [sys.executable, "-m", "agent_graph_demo", "--config", str(web)],
        env=env,
        stdout=log,
        stderr=log,
    )
    report = {
        "status": "UNRUN",
        "product_sha": product_sha,
        "core_sha": CORE_SHA,
        "core_accepted_main": True,
        "profile": PROFILE,
        "runtime_image": image,
        "model_mode": "UNAVAILABLE_NO_CALLS",
        "started_at": now(),
        "limitations": [
            "Model integration is not exercised by this application acceptance.",
            "Target VM RAM/CPU/TLS and restart delivery remain unmeasured.",
        ],
    }
    try:
        credentials = base64.b64encode(("acceptance:" + password).encode()).decode()

        def request(path, body=None):
            headers = {
                "Authorization": "Basic " + credentials,
                "Origin": "http://127.0.0.1:18081",
            }
            if body is not None:
                headers["Content-Type"] = "application/json"
            req = Request(
                "http://127.0.0.1:18081/api/demo" + path,
                data=json.dumps(body).encode() if body is not None else None,
                headers=headers,
            )
            with urlopen(req, timeout=15) as r:
                return json.loads(r.read())

        ready = time.monotonic() + 15
        while True:
            if proc.poll() is not None:
                raise DemoError("backend_start_failed")
            try:
                request("/sessions")
                break
            except (URLError, HTTPError):
                if time.monotonic() > ready:
                    raise DemoError("backend_readiness_timeout")
                time.sleep(0.1)
        store = Store(state)
        browser = journey(
            "http://127.0.0.1:18081", "acceptance", password, operator, output, store
        )
        report["browser"] = browser
        report["runtime_guards"] = guard_probes(
            operator, browser["session_id"], "E", output
        )
        assert request("/sessions"), "actual backend stopped during guard probes"
        # Five sequential sessions share one runtime, preserve history and leave zero containers after stop.
        sid = browser["session_id"]
        shown = [sid]
        for i in range(4):
            old = request("/sessions/" + sid)
            new = request(
                "/sessions/" + sid + "/reset",
                dict(
                    expected_revision=old["revision"],
                    idempotency_key="acceptance-reset-" + str(i),
                ),
            )
            sid = new["id"]
            shown.append(sid)
            receipt = run(
                operator, sid, "A", guard.read()["generation"], output / "receipts"
            )
            assert receipt["status"] == "PASS"
            guard.stop(sid, guard.read()["generation"])
            assert not guard.inventory()
        assert len(request("/sessions")) >= 5
        assert store.jobs(shown[0])[0]["result_ref"]
        report.update(
            status="PASS", sequential_sessions=shown, sandbox_projects_after_stop=0
        )
        return report
    except BaseException:
        report["status"] = "FAIL"
        raise
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        log.close()
        # Cleanup only through the exact pinned registry; UNKNOWN intentionally needs explicit reconciliation.
        r = guard.read()
        if r["state"] == "RUNNING":
            guard.stop(r["session_id"], r["generation"])
        report["finished_at"] = now()
        atomic_json(output / "ACCEPTANCE.json", report)
        # Credentials/config and private state are not report artifacts.
        auth.unlink(missing_ok=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--mode", choices=["local"], default="local")
    p.add_argument("--core-root", type=Path, required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--product-sha", default="WORKTREE")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        result = acceptance(a.core_root, a.image, a.output, a.product_sha)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "report": str(a.output / "ACCEPTANCE.json"),
                }
            )
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "code": exc.code
                    if isinstance(exc, DemoError)
                    else "acceptance_failed",
                }
            )
        )
        raise SystemExit(1)
