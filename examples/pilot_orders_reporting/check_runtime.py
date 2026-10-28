"""Independent execution of trusted authored apps over real loopback HTTP.

The analyzer never runs this harness and receives no expected consumer map.
Run with FastAPI, uvicorn and requests installed. No Jira/GitHub calls are made.
Usage: python examples/pilot_orders_reporting/check_runtime.py <prepared-directory>
"""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request


def check(root):
    root = Path(root).resolve()
    outcomes = []
    for branch, consumer_branch, count in (("main", "main", 60), ("pilot-page-limit", "main", 20),
                                         ("pilot-restored", "main", 60), ("pilot-docs-only", "main", 60),
                                         ("pilot-page-limit", "pilot-explicit-limit", 60)):
        with tempfile.TemporaryDirectory() as directory:
            work = Path(directory)
            text = subprocess.check_output(["git", "-C", str(root / "orders"), "show", f"{branch}:api.py"], text=True)
            (work / "api.py").write_text(text)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            base = f"http://127.0.0.1:{port}"
            process = subprocess.Popen([sys.executable, "-m", "uvicorn", "api:app", "--host", "127.0.0.1",
                                        "--port", str(port), "--log-level", "error"], cwd=work)
            try:
                for _ in range(100):
                    try:
                        with urllib.request.urlopen(base + "/openapi.json", timeout=1):
                            break
                    except (urllib.error.URLError, TimeoutError):
                        if process.poll() is not None:
                            raise RuntimeError("fixture_server_failed")
                        time.sleep(0.05)
                else:
                    raise RuntimeError("fixture_server_timeout")
                source = subprocess.check_output(["git", "-C", str(root / "reporting"), "show", f"{consumer_branch}:client.py"], text=True)
                (work / "client.py").write_text(source)
                spec = importlib.util.spec_from_file_location("pilot_reporting", work / "client.py")
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                module.BASE_URL = base
                ids = [row["id"] for row in module.load_day("2026-10-28")]
                assert ids == list(range(1, count + 1)), (branch, ids)
                outcomes.append({"branch": branch, "consumer_branch": consumer_branch, "ids": ids,
                                 "status": "PASS", "transport": "real loopback HTTP"})
            finally:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
    return {"level": "LOCAL", "author_written": True, "service_tests_executed_consumer": False, "outcomes": outcomes}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(json.dumps(check(sys.argv[1]), indent=2))
