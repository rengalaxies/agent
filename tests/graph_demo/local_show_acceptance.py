"""CI check of the documented local commands, real Docker and HTTP, disposable credentials."""
import argparse
import base64
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen


def check(directory, image):
    directory = Path(directory).resolve()
    password = secrets.token_urlsafe(24)
    command = [sys.executable, "tools/agent_graph_demo/local_show.py", "--directory", str(directory)]

    def invoke(*args, input_text=None):
        result = subprocess.run([*command, *args], input=input_text, text=True,
                                capture_output=True, start_new_session=True, timeout=120)
        if result.returncode:
            raise RuntimeError("documented_local_command_failed: " + args[0])
        return result.stdout

    invoke("init", "--image", image, input_text=password + "\n")
    credentials = base64.b64encode(("operator:" + password).encode()).decode()

    def request(path, body=None):
        headers = {"Authorization": "Basic " + credentials, "Origin": "http://127.0.0.1:18081"}
        if body is not None:
            headers["Content-Type"] = "application/json"
        with urlopen(Request("http://127.0.0.1:18081/api/demo" + path, headers=headers,
                             data=None if body is None else json.dumps(body).encode()), timeout=10) as response:
            return json.load(response)

    def start():
        process = subprocess.Popen([*command, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   start_new_session=True)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("local_show_backend_exited")
            try:
                request("/sessions")
                return process
            except URLError:
                time.sleep(.1)
        stop_backend(process)
        raise RuntimeError("local_show_backend_timeout")

    def stop_backend(process):
        # serve is a CLI parent of the backend. Terminate its own process group only.
        import os
        import signal
        os.killpg(process.pid, signal.SIGTERM)
        process.wait(timeout=10)

    process = start()
    try:
        session = request("/sessions", {})
        sid = session["id"]
        job = request("/sessions/" + sid + "/jobs", dict(action="prepare_context",
            expected_revision=session["revision"], idempotency_key="clean-local-show-prepare",
            payload=dict(task="Inspect the existing HTTP callers")))
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            job = request("/jobs/" + job["id"])
            if job["status"] in ("SUCCEEDED", "PARTIAL"):
                break
            if job["status"] not in ("QUEUED", "RUNNING"):
                raise RuntimeError("local_show_analysis_failed")
            time.sleep(.1)
        assert job["status"] in ("SUCCEEDED", "PARTIAL")
        receipt = json.loads(invoke("run", "--session", sid, "--version", "A"))
        assert receipt["status"] == "PASS"
        invoke("observe")
        invoke("stop")
        old = request("/sessions/" + sid)
        new = request("/sessions/" + sid + "/reset", dict(expected_revision=old["revision"],
                                                        idempotency_key="clean-local-show-reset"))
        assert new["id"] != sid
        assert request("/sessions/" + sid)["jobs"], "history must survive reset"
    finally:
        try:
            invoke("stop")
        finally:
            stop_backend(process)
    process = start()
    try:
        ids = {s["id"] for s in request("/sessions")}
        assert sid in ids and new["id"] in ids, "serve must reopen the same state"
    finally:
        stop_backend(process)
    report = dict(status="PASS", level="CI", commands=["init", "serve", "run A", "observe", "stop", "reset", "serve"],
                  preserved_sessions=[sid, new["id"]], model="OFF", human_acceptance="NOT_RUN")
    (directory / "LOCAL-SHOW.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--image", required=True)
    args = parser.parse_args()
    check(args.directory, args.image)
