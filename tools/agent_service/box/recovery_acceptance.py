"""Exact published release14e ↔ candidate, real processes and local HTTP only.

Run against a fresh test prefix/stand. This is author acceptance, not target VM,
external LIVE, an independent benchmark or a participant session.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys
import os
import fcntl
import subprocess
import time

APP = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(APP / "src"), str(APP)]
from tools.agent_service.box.acceptance import Check, Driver


class RecoveryDriver(Driver):
    @property
    def root(self):
        return Path(self.args.prefix or "/")

    def state(self):
        return json.loads((self.root / "var/lib/agent-service/.box-state.json").read_text())

    def versions(self):
        path = self.root / "var/lib/agent-service/core/graph.sqlite3"
        db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            return sorted({json.loads(row[0])["profile"] for row in db.execute("SELECT data FROM artifacts")
                           if "profile" in json.loads(row[0])})
        finally:
            db.close()

    def upgrade(self):
        before = self.comments()
        interrupted = None
        if not getattr(self, "checked_interrupted_update", False):
            code, _ = self.box(self.args.candidate, "update", "--config", self.stand["box_config"],
                               env={"AGENT_SERVICE_BOX_KILL_AT": "graph"}, expect=None)
            if code == 0:
                raise Check("update was not interrupted after the new graph task")
            if self.args.supervisor == "process":
                from tools.agent_service.box.layout import Layout
                from tools.agent_service.box.supervisor import choose

                choose(Layout.at(self.args.prefix), "process").start()
            else:
                subprocess.run(["systemctl", "start", "agent-service.service"], check=True)
            deadline = time.monotonic() + 60
            loaded_path = self.root / "var/lib/agent-service/run/loaded.json"
            while time.monotonic() < deadline:
                loaded = json.loads(loaded_path.read_text()) if loaded_path.exists() else {}
                if loaded.get("commit") == self.manifest(self.args.candidate)["code"]["commit"]:
                    interrupted = {"killed_exit": code, "loaded_after_supervisor_start": loaded}
                    break
                time.sleep(.2)
            if interrupted is None:
                raise Check("interrupted update did not leave a guarded NEW service entry")
            self.checked_interrupted_update = True
        result = self.box_json(self.args.candidate, "update", "--config", self.stand["box_config"])
        self.loaded_is(self.ready(self.args.candidate), self.args.candidate)
        backup = next(p["detail"]["backup"] for p in result["phases"] if p["phase"] == "backup")
        meta = json.loads((self.root / "var/backups/agent-service" / backup / "backup.json").read_text())
        if meta["release"]["commit"] != "14e65e8affe3b64a9ceb647f537e8af6ff7a1138":
            raise Check("backup was not made for actual release14e")
        saved_identity = json.loads((self.root / "var/backups/agent-service" / backup /
                                     "state/.box-state.json").read_text())
        if saved_identity["semantics"]["extractor_profile"] != "http-requests-4":
            raise Check("backup identity was written by the new profile")
        self.backup = backup
        release_id = self.manifest(self.args.candidate)["release_id"]
        updated = self.wait("both results carry the candidate release identity",
                            lambda c: c["pr"] and release_id in c["pr"][0]["body"]
                            and c["jira"] and f"code_version: {release_id}" in c["jira"][0]["text"])
        self.versions_in_comment(updated, self.args.candidate)
        self.one_comment_each()
        if self.comments()["creates"] != before["creates"]:
            raise Check("upgrade duplicated external comments")
        return {"backup": meta["name"], "schemas": meta["schemas"], "backup_release": meta["release"],
                "interrupted_after_graph_before_activate": interrupted,
                "backup_state_identity": saved_identity,
                "loaded_profile": self.state()["semantics"], "stored_profiles": self.versions()}

    def invalid_backups(self):
        prefix = self.root / "var/backups/agent-service"
        path = prefix / self.backup
        before = self.ready(self.args.candidate)["process"]["loaded"]["pid"]
        hidden = prefix / ("." + self.backup)
        path.rename(hidden)
        try:
            self.box(self.args.candidate, "rollback", "--to", Path(self.args.release).name, expect=1)
        finally:
            hidden.rename(path)
        db = path / "state/service/service.sqlite"
        content = db.read_bytes()
        db.write_bytes(b"broken backup")
        try:
            self.box(self.args.candidate, "rollback", "--to", Path(self.args.release).name, expect=1)
        finally:
            db.write_bytes(content)
        after = self.ready(self.args.candidate)["process"]["loaded"]["pid"]
        if before != after:
            raise Check("refused rollback replaced the current writer")
        return {"missing": "REFUSED", "corrupt": "REFUSED", "current_pid_preserved": True}

    def interrupted_rollback(self):
        before = self.comments()
        self.control("/push", {"branch": "pr-7", "deliver": False})
        self.control("/jira/summary", {"summary": "ORD-12 Reduce page size from 100 to 20 after backup"})
        points = ("restore:staged", "restore:aside", "restore:file:service/service.sqlite",
                  "restore:swapped", "rollback:before-start")
        outcomes = {}
        for point in points:
            code, _ = self.box(self.args.candidate, "rollback", "--to", Path(self.args.release).name,
                               env={"AGENT_SERVICE_BOX_KILL_AT": point}, expect=None)
            if code == 0:
                raise Check(f"fault did not interrupt {point}")
            pending = self.root / "var/lib/agent-service/.box-recovery.json"
            if not pending.exists():
                raise Check("interruption lost the durable publication hold")
            if self.comments()["creates"] != before["creates"]:
                raise Check("interrupted recovery created a comment")
            outcomes[point] = {"exit": code, "hold": json.loads(pending.read_text())["phase"]}
        self.control("/faults", {"provider": "jira", "status": 503})
        writes = self.comments()["updates"]
        try:
            self.box(self.args.candidate, "rollback", "--to", Path(self.args.release).name, expect=1)
            if self.comments()["updates"] != writes:
                raise Check("API failure allowed publication before reconciliation")
            if self.status(self.args.candidate)["scenario"]["status"] != "NOT_READY":
                raise Check("API failure was presented as READY")
        finally:
            self.control("/faults", {"provider": "jira"})
        mirror = self.root / "var/lib/agent-service/mirrors/orders.git"
        hidden = mirror.with_name("orders.git.unavailable")
        # The real systemd mirror timer correctly repairs a merely renamed mirror.
        # Hold its existing lock so this fault actually remains unavailable; do not
        # mistake successful reconciliation for a failed publication gate.
        sync_lock = os.open(mirror.parent / ".sync.lock", os.O_RDWR)
        fcntl.flock(sync_lock, fcntl.LOCK_EX)
        mirror.rename(hidden)
        try:
            self.box(self.args.candidate, "rollback", "--to", Path(self.args.release).name, expect=1)
            if self.comments()["updates"] != writes:
                raise Check("missing source allowed publication before reconciliation")
            if self.status(self.args.candidate)["scenario"]["status"] != "NOT_READY":
                raise Check("missing source was presented as READY")
        finally:
            hidden.rename(mirror)
            os.close(sync_lock)
        result = self.box_json(self.args.candidate, "rollback", "--to", Path(self.args.release).name)
        if result["mode"] != "restored_backup" or result["backup"] != self.backup:
            raise Check(f"wrong recovery selection: {result}")
        self.loaded_is(self.ready(self.args.release), self.args.release)
        head = self.comments()["heads"]["pr-7"][:12]
        legacy_id = self.manifest(self.args.release)["release_id"]
        c = self.wait("restored legacy writer reconciles the current head and Jira",
                      lambda c: c["pr"] and f"head {head}" in c["pr"][0]["body"]
                      and f"code_version: {legacy_id}" in c["jira"][0]["text"], timeout=180)
        self.one_comment_each(c)
        if [x["id"] for x in c["pr"]] != [x["id"] for x in before["pr"]] or (
                [x["id"] for x in c["jira"]] != [x["id"] for x in before["jira"]]):
            raise Check("recovery changed comment identities")
        duplicates = {}
        for _ in range(2):
            duplicates["github"] = self.control("/deliver/pr", {
                "action": "synchronize", "delivery_id": "recovery-pr-duplicate"})
            duplicates["jira"] = self.control("/deliver/jira", {
                "event": "updated", "delivery_id": "recovery-jira-duplicate"})
        if not all(result["response"].get("duplicate") for result in duplicates.values()):
            raise Check("exact event redelivery was not recognized as duplicate")
        self.one_comment_each()
        wrapper = (self.root / "usr/local/sbin/agent-service-box").read_text()
        if Path(self.args.candidate).name not in wrapper:
            raise Check("rollback replaced the supported manager with the legacy CLI")
        return {"interruptions": outcomes, "api_failure": "HELD_NO_WRITES", "source_failure": "HELD_NO_WRITES",
                "rollback": result,
                "duplicate_deliveries": duplicates,
                "current_head": head, "comment_ids": {"pr": [x["id"] for x in c["pr"]],
                                                        "jira": [x["id"] for x in c["jira"]]},
                "stored_profiles": self.versions(), "manager_preserved": True}

    def restart_recovered_writer(self):
        state = self.root / "var/lib/agent-service/service/service.sqlite"

        def generations():
            db = sqlite3.connect(f"file:{state}?mode=ro", uri=True)
            try:
                return dict(db.execute("SELECT resource_id,generation FROM resources"))
            finally:
                db.close()

        before = generations()
        creates = self.comments()["creates"]
        if self.args.supervisor == "process":
            from tools.agent_service.box.layout import Layout
            from tools.agent_service.box.supervisor import choose

            choose(Layout.at(self.args.prefix), "process").restart()
        else:
            # The system Python drives acceptance without release dependencies.
            subprocess.run(["systemctl", "restart", "agent-service.service"], check=True)
        # wait_ready polls the process identity and status, including the manager's guard.
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            try:
                self.ready(self.args.release)
                break
            except Check:
                time.sleep(1)
        self.ready(self.args.release)
        if generations() != before or self.comments()["creates"] != creates:
            raise Check("restart of a reconciled state duplicated generations/publications")
        return {"generations": before, "same_comment_ids": True, "durable_recovery_checkpoint": True}

    def reupgrade(self):
        result = self.upgrade()
        self.control("/deliver/pr", {"action": "synchronize"})
        self.control("/deliver/jira", {"event": "updated"})
        self.one_comment_each()
        return result

    def run(self):
        self.report.update(level="LOCAL_PROCESS" if self.args.supervisor == "process" else "CI_SYSTEMD",
                           legacy=self.manifest(self.args.release)["code"],
                           candidate=self.manifest(self.args.candidate)["code"], model="OFF",
                           target_vm="NOT_RUN", external_live="NOT_RUN", participant="NOT_RUN")
        for name, fn in (("fresh_legacy", self.fresh_install), ("upgrade_before_new_writer", self.upgrade),
                         ("invalid_matching_backups", self.invalid_backups),
                         ("rollback_interruptions_api_failure_external_recovery", self.interrupted_rollback),
                         ("restart_recovered_writer", self.restart_recovered_writer),
                         ("reupgrade_same_comment_ids", self.reupgrade)):
            if not self.scenario(name, fn):
                break
        if all(s["result"] == "PASS" for s in self.report["scenarios"]):
            db = sqlite3.connect((self.root / "var/lib/agent-service/service/service.sqlite").resolve().as_uri()
                                 + "?mode=ro", uri=True)
            db.row_factory = sqlite3.Row
            try:
                resources = []
                for row in db.execute("SELECT resource_id,version,generation,comment_id,snapshot FROM resources"):
                    data = dict(row)
                    snapshot = json.loads(data.pop("snapshot"))
                    data["versions"] = {k: snapshot[k] for k in
                                        ("base_sha", "head_sha", "revision", "updated_at") if k in snapshot}
                    resources.append(data)
                self.report["resource_versions"] = resources
                self.report["event_ids"] = [dict(row) for row in db.execute(
                    "SELECT provider,event_id,event_kind,state FROM events ORDER BY received_at")]
            finally:
                db.close()
        return self.finish()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("stand", "release", "candidate", "output"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--prefix")
    parser.add_argument("--supervisor", choices=["process", "systemd"])
    parser.add_argument("--call-timeout", type=int, default=900)
    args = parser.parse_args()
    if args.prefix:
        secrets = Path(args.prefix) / "etc/agent-service/secrets.env"
        secrets.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(json.loads(Path(args.stand).read_text())["secrets"], secrets)
        secrets.chmod(0o600)
    return RecoveryDriver(args).run()


if __name__ == "__main__":
    raise SystemExit(main())
