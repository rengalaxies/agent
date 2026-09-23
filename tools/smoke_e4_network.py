"""Three independent domain server processes on loopback (not three environments)."""
from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from datamesh_release_protocol.network import coordinate
from run_e4 import three_domains


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def main() -> None:
    domains = ("fintech", "retail", "mobility")
    ports = {domain: port() for domain in domains}
    urls = {domain: f"http://127.0.0.1:{ports[domain]}" for domain in domains}
    keys = {domain: secrets.token_hex(32) for domain in domains}
    env = dict(os.environ, PYTHONPATH="src", **{f"E4_{d.upper()}_KEY": keys[d] for d in domains})
    processes = {}
    try:
        for domain in domains:
            processes[domain] = subprocess.Popen([sys.executable, "tools/e4_network.py", "serve",
                "--domain", domain, "--port", str(ports[domain]), "--key-env", f"E4_{domain.upper()}_KEY"],
                env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        for domain in domains:
            for _ in range(100):
                if processes[domain].poll() is not None:
                    raise RuntimeError(f"server {domain} exited: {processes[domain].stderr.read().decode()}")
                try:
                    with socket.create_connection(("127.0.0.1", ports[domain]), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.05)
            else:
                raise RuntimeError(f"server {domain} did not start")
        scenario = three_domains()
        with tempfile.TemporaryDirectory(prefix="e4-network-") as temp:
            def run(case, **kwargs):
                return coordinate(scenario, case, urls, keys, Path(temp) / f"{case}.sqlite", **kwargs)
            normal = run("normal", timeout_s=2)
            duplicate = run("duplicate", timeout_s=2, duplicate=True)
            delayed = run("delayed", timeout_s=0.4, delays={"mobility": 1.0})
            processes["mobility"].terminate()
            processes["mobility"].wait(timeout=2)
            unavailable = run("unavailable", timeout_s=1)
        checks = {
            "three_processes_accept": normal["decision"] == "ACCEPT" and len(normal["received_domains"]) == 3,
            "duplicate_is_idempotent": duplicate["decision"] == "ACCEPT" and duplicate["duplicates"] == 3,
            "deadline_fails_safe": delayed["decision"] == "NEEDS_REVIEW" and delayed["missing_domains"] == ["mobility"],
            "domain_outage_fails_safe": unavailable["decision"] == "NEEDS_REVIEW" and unavailable["missing_domains"] == ["mobility"],
        }
        result = {"experiment": "E4-N loopback process smoke", "three_separate_environments": False,
                  "confirmatory": False, "cases": {"normal": normal, "duplicate": duplicate,
                  "delayed": delayed, "unavailable": unavailable}, "checks": checks,
                  "passed": sum(checks.values()), "total": len(checks)}
        dest = Path("results/e4-network-loopback.json")
        dest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"{result['passed']}/{result['total']} loopback checks passed: {dest}")
        if not all(checks.values()):
            raise SystemExit(1)
    finally:
        for process in processes.values():
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
            process.stderr.close()


if __name__ == "__main__":
    main()
