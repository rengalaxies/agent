"""Real disposable Docker lifecycle with explicitly labelled injected fault boundaries."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
import uuid

from agent_graph_demo.contracts import DemoError
from agent_graph_demo.snapshots import atomic_json
from tools.agent_graph_demo.run_scenario import run
from tools.agent_graph_demo.runtime_guard import RuntimeGuard


def guard_probes(operator, sid, version, output):
    output = Path(output)
    guard = RuntimeGuard(
        operator["state_root"],
        operator["runtime_root"],
        operator["image"],
        operator["product_sha"],
    )
    controls = []
    try:
        for project in ("agent-graph-demo", "unrelated-demo-control"):
            name = "graph-demo-control-" + uuid.uuid4().hex
            cid = guard.docker(
                "run",
                "-d",
                "--name",
                name,
                "--network",
                "none",
                "--read-only",
                "--cap-drop",
                "ALL",
                "--security-opt",
                "no-new-privileges:true",
                "--pids-limit",
                "16",
                "--memory",
                "32m",
                "--label",
                "com.docker.compose.project=" + project,
                operator["image"],
                "python",
                "-c",
                "import time;time.sleep(600)",
            ).strip()
            controls.append(cid)
        expected = guard.read()["generation"]
        with ThreadPoolExecutor(2) as pool:
            results = list(
                pool.map(
                    lambda _: run(
                        operator, sid, version, expected, output / "receipts"
                    ),
                    range(2),
                )
            )
        assert sorted(r["status"] for r in results) == ["ERROR", "PASS"]
        assert (
            next(r for r in results if r["status"] == "ERROR")["error_code"]
            == "runtime_generation_conflict"
        )
        own = guard.active(guard.inventory())
        assert (
            len({c["Config"]["Labels"]["com.docker.compose.project"] for c in own}) == 1
        )
        stats = guard.docker(
            "stats", "--no-stream", "--format", "{{json .}}", *(c["Id"] for c in own)
        )
        provider = next(
            c
            for c in own
            if c["Config"]["Labels"]["com.docker.compose.service"] == "orders"
        )
        invalid = guard.docker(
            "exec",
            provider["Id"],
            "python",
            "-c",
            "import urllib.request,urllib.error\nfor q in ('cursor=251','cursor=-1','page_size=0'):\n try: urllib.request.urlopen('http://127.0.0.1:8000/orders?'+q);raise AssertionError('expected 422')\n except urllib.error.HTTPError as e: assert e.code==422\nprint('PASS')",
        )
        assert invalid.strip() == "PASS"
        # This is an injected down exception, not a claimed real daemon outage.
        with patch.object(
            guard, "down", side_effect=DemoError("injected_down_failure")
        ):
            try:
                guard.stop(sid, guard.read()["generation"])
            except DemoError as exc:
                assert exc.code == "injected_down_failure"
            else:
                raise AssertionError("stop must fail")
        assert guard.read()["state"] == "UNKNOWN"
        blocked = run(
            operator, sid, version, guard.read()["generation"], output / "receipts"
        )
        assert (
            blocked["status"] == "ERROR"
            and blocked["error_code"] == "runtime_reconciliation_required"
        )
        guard.reconcile(guard.read()["generation"])
        assert not guard.inventory()
        # Kill a separate process after the real STARTING journal write, before Docker up.
        cfg = output / "operator-probe.json"
        atomic_json(cfg, operator)
        marker = output / "starting-marker"
        marker.unlink(missing_ok=True)
        code = """
import json,sys,time
from pathlib import Path
from tools.agent_graph_demo.runtime_guard import RuntimeGuard
from tools.agent_graph_demo.run_scenario import run
c=json.loads(Path(sys.argv[1]).read_text());marker=Path(sys.argv[2]);original=RuntimeGuard.docker
def intercepted(self,*args,**kw):
 if args[0]=='compose' and 'up' in args:
  marker.touch()
  while True:time.sleep(.05)
 return original(self,*args,**kw)
RuntimeGuard.docker=intercepted
run(c,sys.argv[3],sys.argv[4],int(sys.argv[5]),Path(sys.argv[6]))
"""
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                code,
                str(cfg),
                str(marker),
                sid,
                version,
                str(guard.read()["generation"]),
                str(output / "receipts"),
            ],
            env=os.environ,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            deadline = time.monotonic() + 20
            while (
                not marker.exists()
                and proc.poll() is None
                and time.monotonic() < deadline
            ):
                time.sleep(0.03)
            assert marker.exists(), "STARTING marker missing"
            assert guard.read()["state"] == "STARTING"
            proc.kill()
            proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        blocked = run(
            operator, sid, version, guard.read()["generation"], output / "receipts"
        )
        assert (
            blocked["status"] == "ERROR"
            and blocked["error_code"] == "runtime_reconciliation_required"
        )
        guard.reconcile(guard.read()["generation"])
        assert not guard.inventory()
        for cid in controls:
            assert json.loads(guard.docker("inspect", cid))[0]["State"]["Running"]
        return {
            "status": "PASS",
            "checks": [
                "two concurrent activations: one CAS winner",
                "exact-project control fixtures preserved",
                "HTTP invalid cursor/page size returns 422",
                "injected down exception -> UNKNOWN -> blocked activation -> explicit reconcile",
                "real process kill after STARTING write, before up -> blocked activation -> explicit reconcile",
            ],
            "steady_provider_stats": [json.loads(line) for line in stats.splitlines()],
            "measurement_scope": "Samples after checks; not peak workload or target-VM measurements.",
        }
    finally:
        for cid in controls:
            guard.docker("rm", "-f", cid)
