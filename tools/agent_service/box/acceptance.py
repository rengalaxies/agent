"""Acceptance of the INSTALLED box against the long-running test stand (teststand.py).

    sudo python3 acceptance.py --stand DIR/stand.json --release A --update C --schema-update B --output report.json
    python acceptance.py ... --prefix SCRATCH --supervisor process      (development machine, no systemd)

Host Python, standard library only: it drives the box exactly as an owner
would (``<release>/box ...``) and observes the stand's GitHub/Jira comments.
Releases: A = the release under test, C = A with only a newer version
(same state schema), B = A with a service store schema bump.

Every scenario records pass/fail, the box exit codes and wall-clock seconds.
The report says which supervisor ran: ``process`` results are not a Linux
or systemd acceptance.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request


class Check(Exception):
    pass


def _service_processes() -> list[int] | None:
    """PIDs running the box's service entry (Linux /proc only)."""
    proc = Path("/proc")
    if not proc.is_dir():
        return None
    found = []
    for entry in proc.iterdir():
        if entry.name.isdigit():
            try:
                cmdline = (entry / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if any(part.endswith(b"/box/launch.py") for part in cmdline):
                found.append(int(entry.name))
    return found


def _rss_kib(pid: int) -> int | None:
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    except OSError:
        return None
    return None


def _kill_tree(proc: subprocess.Popen):
    if os.name == "nt":
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    proc.wait()


class Driver:
    def __init__(self, args):
        self.args = args
        self.stand = json.loads(Path(args.stand).read_text(encoding="utf-8"))
        self.report = {"supervisor": args.supervisor or "systemd", "scenarios": [], "box_calls": []}
        self.secrets = Path(args.prefix or "/") / "etc/agent-service/secrets.env"

    # -- plumbing ----------------------------------------------------------

    def box(self, release: str, *args: str, env: dict | None = None, expect: int | tuple | None = 0) -> tuple[int, str]:
        command = [sys.executable, str(Path(release) / "box"), *args]
        if self.args.prefix:
            command += ["--prefix", self.args.prefix]
        if self.args.supervisor:
            command += ["--supervisor", self.args.supervisor]
        started = time.monotonic()
        # Output goes to a file, not a pipe: a service the box starts must never keep this driver waiting for EOF.
        with tempfile.TemporaryFile() as log:
            kwargs = {"start_new_session": True} if os.name != "nt" else {
                "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            proc = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})}, **kwargs)
            try:
                returncode = proc.wait(timeout=self.args.call_timeout)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                returncode = None
            log.seek(0)
            text = log.read().decode("utf-8", "replace")
        call = {"args": [Path(release).name, *args], "exit": returncode,
                "seconds": round(time.monotonic() - started, 2)}
        self.report["box_calls"].append(call)
        if returncode is None:
            raise Check(f"box {' '.join(args)} did not finish in {self.args.call_timeout} s:\n{text[-3000:]}")
        expected = (expect,) if isinstance(expect, int) else expect
        if expected is not None and returncode not in expected:
            raise Check(f"box {' '.join(args)} exit {returncode}, expected {expect}:\n{text[-3000:]}")
        return returncode, text

    def box_json(self, release: str, *args: str, expect=0) -> dict:
        _, text = self.box(release, *args, "--json", expect=expect)
        start = text.find("{")
        return json.loads(text[start:]) if start >= 0 else {}

    def control(self, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(self.stand["control"] + path, method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def comments(self) -> dict:
        return self.control("/comments")

    def wait(self, what: str, predicate, timeout=90):
        deadline = time.time() + timeout
        last = None
        while time.time() < deadline:
            last = self.comments()
            if predicate(last):
                return last
            time.sleep(1)
        raise Check(f"timeout waiting for {what}; last comments: "
                    + json.dumps({k: last[k] for k in ("creates", "updates")} if last else None))

    def status(self, release: str) -> dict:
        return self.box_json(release, "status", expect=(0, 2))

    def counts(self) -> tuple[int, int]:
        c = self.comments()
        return c["creates"]["github"], c["creates"]["jira"]

    def one_comment_each(self, c=None):
        c = c or self.comments()
        if len(c["pr"]) != 1 or len(c["jira"]) != 1:
            raise Check(f"expected one service comment per resource, got pr={len(c['pr'])} jira={len(c['jira'])}")
        if c["creates"]["github"] != 1 or c["creates"]["jira"] != 1:
            raise Check(f"comment created more than once: {c['creates']}")

    def ready(self, release: str, name: str | None = None) -> dict:
        s = self.status(release)
        if s["scenario"]["status"] != "READY":
            raise Check(f"not READY: {s['process']['problems'] + s['scenario']['reasons']}")
        loaded = s["process"]["loaded"]
        manifest = json.loads((Path(release if name is None else name) / "manifest.json").read_text(encoding="utf-8"))
        if loaded["release"] != manifest["name"] or loaded["core"] != manifest["contracts"]["core"]:
            raise Check(f"running {loaded['release']} differs from expected {manifest['name']}")
        return s

    def scenario(self, name: str, fn):
        started = time.monotonic()
        entry = {"scenario": name}
        try:
            entry["detail"] = fn() or {}
            entry["result"] = "PASS"
        except Exception as exc:  # the report keeps going so one failure does not hide the others
            entry["result"] = "FAIL"
            entry["error"] = str(exc)[-4000:]
            entry["trace"] = traceback.format_exc()[-2000:]
        entry["seconds"] = round(time.monotonic() - started, 1)
        self.report["scenarios"].append(entry)
        print(f"[{entry['result']}] {name} ({entry['seconds']} s)" + (f": {entry.get('error', '')[:300]}"
                                                                     if entry["result"] == "FAIL" else ""), flush=True)
        return entry["result"] == "PASS"

    # -- scenarios ---------------------------------------------------------

    def fresh_install(self):
        A = self.args.release
        t = time.monotonic()
        run = self.box_json(A, "install", "--config", self.stand["box_config"])
        seconds = round(time.monotonic() - t, 1)
        s = self.ready(A)
        # The worker reconciles on start: open PR #7 and ORD-12 get their first comments without a webhook.
        c = self.wait("first comments from reconciliation", lambda c: len(c["pr"]) == 1 and len(c["jira"]) == 1)
        self.one_comment_each(c)
        return {"install_wall_seconds": seconds, "machine_seconds": run.get("machine_seconds"),
                "phase_seconds": {p["phase"]: p["seconds"] for p in run.get("phases", [])},
                "release": s["release"], "loaded": s["process"]["loaded"],
                "graph": s["scenario"]["graph"], "service_rss_kib": _rss_kib(s["process"]["loaded"]["pid"])}

    def end_to_end(self):
        pr7 = self.comments()["heads"]["pr-7"]
        r = self.control("/push", {"branch": "pr-7"})
        if r["status"] not in (200, 202):
            raise Check(f"webhook rejected: {r}")
        c = self.wait("PR comment for the pr-7 head",
                      lambda c: c["pr"] and f"head {pr7[:12]}" in c["pr"][0]["body"]
                      and "PAGE_DEFAULT_CHANGED 100 -> 20" in c["pr"][0]["body"])
        self.one_comment_each(c)
        r = self.control("/deliver/jira", {"event": "created"})
        return {"pr_first_line": c["pr"][0]["first_line"], "jira_delivery": r["status"],
                "updates": c["updates"]}

    def reinstall(self):
        A = self.args.release
        before = self.status(A)
        before_comments = self.comments()
        out = self.box_json(A, "install", "--config", self.stand["box_config"])
        start = next(p for p in out["phases"] if p["phase"] == "start")
        if start["detail"]["action"] != "kept":
            raise Check(f"second install touched the running service: {start['detail']['action']}")
        after = self.ready(A)
        if after["process"]["loaded"]["pid"] != before["process"]["loaded"]["pid"]:
            raise Check("service process replaced by a no-change install")
        services = _service_processes()
        if services is not None and len(services) != 1:
            raise Check(f"expected one service process, found {len(services)}")
        mirrors = next(p for p in out["phases"] if p["phase"] == "mirrors")["detail"]["repositories"]
        if any(m.get("action") != "fetched" for m in mirrors):
            raise Check("mirrors cloned again")
        configure = next(p for p in out["phases"] if p["phase"] == "configure")["detail"]
        if configure["changed"]:
            raise Check(f"configuration rewritten: {configure['changed']}")
        if after["scenario"]["graph"]["relationships"] != before["scenario"]["graph"]["relationships"]:
            raise Check("graph relationships changed on reinstall")
        self.one_comment_each()
        if self.comments()["creates"] != before_comments["creates"]:
            raise Check("reinstall created comments")
        return {"machine_seconds": out.get("machine_seconds"), "pid": after["process"]["loaded"]["pid"]}

    def interrupted(self):
        A = self.args.release
        results = {}
        for point in ("configure", "mirrors:start", "graph", "start", "smoke:start"):
            code, _ = self.box(A, "install", "--config", self.stand["box_config"],
                               env={"AGENT_SERVICE_BOX_KILL_AT": point}, expect=None)
            if code == 0:
                raise Check(f"fault hook at {point} did not interrupt the installer")
            out = self.box_json(A, "install", "--config", self.stand["box_config"])
            if out["state"] != "DONE" or not out.get("resumed_after"):
                raise Check(f"rerun after {point} did not finish as a resumed run")
            s = self.ready(A)
            results[point] = {"killed_exit": code, "resumed_after": out["resumed_after"]["last_phase"].get("phase"),
                              "pid": s["process"]["loaded"]["pid"]}
        self.one_comment_each()
        return results

    def service_crash(self):
        A = self.args.release
        pid = self.status(A)["process"]["loaded"]["pid"]
        if self.args.supervisor == "process":
            os.kill(pid, signal.SIGTERM)
            time.sleep(2)
            self.box(A, "install", "--config", self.stand["box_config"])
            restarted_by = "box install (process supervisor has no restart)"
        else:
            subprocess.run(["systemctl", "kill", "-s", "KILL", "agent-service.service"], check=True)
            restarted_by = "systemd Restart=on-failure"
        deadline = time.time() + 60
        while True:
            s = self.status(A)
            if s["scenario"]["status"] == "READY" and s["process"]["loaded"]["pid"] != pid:
                break
            if time.time() > deadline:
                raise Check("service did not come back after kill")
            time.sleep(2)
        self.one_comment_each()
        return {"killed_pid": pid, "new_pid": s["process"]["loaded"]["pid"], "restarted_by": restarted_by}

    def doctor_bad_credentials(self):
        A = self.args.release
        original = self.secrets.read_bytes()
        wrong = "wrong-token-" + os.urandom(6).hex()
        text = original.decode().replace("GITHUB_TOKEN=", "GITHUB_TOKEN_UNUSED=")
        self.secrets.write_bytes((text + f"\nGITHUB_TOKEN={wrong}\n").encode())
        try:
            code, out = self.box(A, "doctor", expect=1)
            _, raw = self.box(A, "doctor", "--json", expect=1)
            if wrong in out or wrong in raw:
                raise Check("doctor printed the secret value")
            if "учётные данные" not in out:
                raise Check(f"doctor did not explain the credential problem:\n{out[-1500:]}")
            report = json.loads(raw[raw.find("{"):])
            if not any(r.startswith("probe:github") and r.endswith("connection_unauthorized")
                       for r in report["scenario"]["reasons"]):
                raise Check(f"doctor reasons lack the GitHub credential probe: {report['scenario']['reasons']}")
        finally:
            self.secrets.write_bytes(original)
        self.box(A, "doctor")
        return {"doctor_exit_with_wrong_token": code,
                "reasons": [r for r in report["scenario"]["reasons"] if r.startswith("probe:")]}

    def backup_restore(self):
        A = self.args.release
        meta = self.box_json(A, "backup", "--label", "acceptance")
        before = self.comments()
        self.control("/jira/summary", {"summary": "Reduce the default Orders page size from 100 to 20 (backup test)"})
        self.control("/deliver/jira", {"event": "updated"})
        self.wait("Jira comment update after the summary change",
                  lambda c: c["updates"]["jira"] > before["updates"]["jira"])
        restored = self.box_json(A, "restore", meta["name"])
        s = self.ready(A)
        # The Jira change made after the backup comes back through reconciliation, as an update of the same comment.
        self.wait("reconciliation re-publishes after restore",
                  lambda c: c["updates"]["jira"] > before["updates"]["jira"] + 1, timeout=180)
        self.one_comment_each()
        return {"backup": meta["name"], "backup_counts": meta["counts"], "restored": restored["restored"],
                "safety_backup": restored["safety_backup"], "queue_after": s["scenario"]["queue"]}

    def update_and_rollback(self, new: str, expect_mode: str):
        A = self.args.release
        out = self.box_json(new, "install", "--config", self.stand["box_config"])
        phases = {p["phase"]: p for p in out["phases"]}
        if "backup" not in phases:
            raise Check("update did not take a pre-update backup")
        self.ready(new)
        before = self.comments()
        self.control("/jira/summary", {"summary": f"ORD-12 changed while {Path(new).name} runs"})
        self.control("/deliver/jira", {"event": "updated"})
        self.wait("event processed by the updated release", lambda c: c["updates"]["jira"] > before["updates"]["jira"])
        rollback = self.box_json(new, "rollback")
        if rollback["mode"] != expect_mode:
            raise Check(f"rollback mode {rollback['mode']}, expected {expect_mode}")
        self.ready(A)
        if expect_mode == "restored_backup":
            self.wait("reconciliation after restoring the pre-update backup",
                      lambda c: c["updates"]["jira"] > before["updates"]["jira"] + 1, timeout=180)
        self.one_comment_each()
        return {"update_machine_seconds": out.get("machine_seconds"), "backup": phases["backup"]["detail"],
                "rollback": rollback}

    def run(self) -> int:
        self.report["started_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        plan = [("fresh_install", self.fresh_install),
                ("end_to_end_on_installed_release", self.end_to_end),
                ("reinstall_is_idempotent", self.reinstall),
                ("interrupted_install_is_finished_by_rerun", self.interrupted),
                ("service_killed_comes_back", self.service_crash),
                ("doctor_wrong_credentials", self.doctor_bad_credentials),
                ("backup_restore", self.backup_restore)]
        if self.args.update:
            plan.append(("update_same_schema_then_rollback",
                         lambda: self.update_and_rollback(self.args.update, "release_only")))
        if self.args.schema_update:
            plan.append(("update_schema_change_then_rollback",
                         lambda: self.update_and_rollback(self.args.schema_update, "restored_backup")))
        only = set(self.args.only.split(",")) if self.args.only else None
        for name, fn in plan:
            if only is None or name in only:
                if not self.scenario(name, fn) and name == "fresh_install":
                    break
        return self.finish()

    def finish(self) -> int:
        self.report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        self.report["passed"] = all(s["result"] == "PASS" for s in self.report["scenarios"])
        Path(self.args.output).write_text(json.dumps(self.report, indent=2, ensure_ascii=False) + "\n",
                                          encoding="utf-8")
        return 0 if self.report["passed"] else 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stand", required=True)
    parser.add_argument("--release", required=True, help="extracted release A")
    parser.add_argument("--update", help="extracted release C (same schema)")
    parser.add_argument("--schema-update", help="extracted release B (schema bump)")
    parser.add_argument("--prefix")
    parser.add_argument("--supervisor", choices=["systemd", "process"])
    parser.add_argument("--output", required=True)
    parser.add_argument("--call-timeout", type=int, default=900, help="seconds per box command")
    parser.add_argument("--only", help="comma-separated scenarios (debugging an existing installation)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")
    return Driver(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
