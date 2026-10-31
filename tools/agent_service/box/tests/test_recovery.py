"""Author regressions: schema equality never licenses an unknown writer."""

import json
from pathlib import Path
import tempfile
import os
import signal
import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace
import unittest
from unittest import mock

from tools.agent_service.box import cli, config, recovery, release
from tools.agent_service.box import state as box_state
from tools.agent_service.box.layout import Layout
from tools.agent_service.box.tests.test_state import make_state, RELEASE_V1
from tools.agent_service.box.preflight import legacy_reopen
from agent_service.queue import ServiceStore


def manifest(name, profile):
    return {"name": name, "release_id": name, "code": {"commit": "a" * 40}, "contracts": {
        "state": RELEASE_V1, "recovery": {"protocol": 1, "state_semantics": {
            "extractor_profile": profile, "graph_schema": "agent-graph-1", "output_schema": "2.1"}}}}


class RollbackBoundary(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.layout = Layout.at(tmp.name)
        make_state(self.layout.state)
        self.old, self.new = manifest("old", "http-requests-4"), manifest("new", "http-requests-6")
        self.box = cli.Box.__new__(cli.Box)
        self.box.layout, self.box.release = self.layout, self.layout.release("new")
        self.box.manifest, self.box.manifest_sha = self.new, "b" * 64
        self.box.supervisor = mock.Mock()
        self.box.out = lambda *args: None
        self.box.save({"active": recovery.record(self.new, "b" * 64),
                       "history": [recovery.record(self.old, "c" * 64)]})
        for name in ("old", "new"):
            self.layout.bindings(name).mkdir(parents=True)
            config.write_json(self.layout.bindings(name) / "service.json", {
                "analysis": {"code_version": name}, "state_path": str(self.layout.state / "service/service.sqlite"),
                "core": {"state_dir": str(self.layout.state / "core"),
                         "policy_path": str(self.layout.bindings(name) / "policy.json")}})
            (self.layout.bindings(name) / "box.yaml").write_text("{}")
        recovery.identify(self.layout.state, self.new, "b" * 64)
        self.cfg = SimpleNamespace()
        self.box.current_config = lambda: self.cfg

    def test_equal_schema_different_semantics_without_backup_never_starts_target(self):
        started = []

        def activate(cfg, target, info):
            started.append(info["name"])
            return {"process_ready": True, "problems": []}

        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate", side_effect=activate):
            with self.assertRaises(cli.Failed):
                self.box.rollback(self.cfg, "old")
        self.assertEqual(started, [])
        self.assertEqual(recovery.read_identity(self.layout.state)["semantics"]["extractor_profile"],
                         "http-requests-6")

    def test_unknown_legacy_manifest_refuses_before_activation(self):
        del self.old["contracts"]["recovery"]
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate") as activate:
            with self.assertRaises(cli.Failed):
                self.box.rollback(self.cfg, "old")
        activate.assert_not_called()

    def test_update_does_not_restart_old_writer_after_provenance_refusal(self):
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)):
            with self.assertRaisesRegex(cli.Failed, "provenance"):
                self.box.pre_update_backup(recovery.record(self.old, "c" * 64))
        self.box.supervisor.stop.assert_called_once()
        self.box.supervisor.start.assert_not_called()

    def test_equal_semantics_keeps_queue_and_history_without_backup(self):
        self.old["contracts"]["recovery"] = self.new["contracts"]["recovery"]
        before = box_state.counts(self.layout.state)
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(cli.rel, "load_manifest", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate", return_value={"process_ready": True, "problems": []}):
            result = self.box.rollback(self.cfg, "old")
        self.assertEqual(result["mode"], "release_only")
        self.assertEqual(box_state.counts(self.layout.state), before)
        self.assertFalse(self.layout.backups.exists())

    def test_release_only_selects_target_owner_configuration_too(self):
        self.old["contracts"]["recovery"] = self.new["contracts"]["recovery"]
        self.layout.config.write_text('{"owner_config":"new"}')
        (self.layout.bindings("old") / "box.yaml").write_text('{"owner_config":"old"}')
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate", return_value={"process_ready": True, "problems": []}):
            self.box.rollback(self.cfg, "old")
        self.assertEqual(json.loads(self.layout.config.read_text())["owner_config"], "old")

    def test_status_during_recovery_never_opens_sqlite_through_old_readiness_task(self):
        recovery.hold(self.layout.state, {"phase": "RESTORING", "target": recovery.record(self.old, "c" * 64)})
        process = {"live": False, "process_ready": False, "problems": ["held"], "loaded": None}
        with mock.patch.object(self.box, "process_level", return_value=process), \
                mock.patch.object(self.box, "task") as task, \
                mock.patch.object(self.box, "active_manifest", return_value=self.new):
            status = self.box.readiness({"host": "127.0.0.1", "port": 1})
        task.assert_not_called()
        self.assertEqual(status["scenario"]["status"], "NOT_READY")
        self.assertIn("graph:recovery_held", status["scenario"]["reasons"])

    def test_status_with_mismatched_writer_never_opens_old_sqlite_task(self):
        process = {"live": False, "process_ready": False, "problems": [], "loaded": None}
        with mock.patch.object(self.box, "process_level", return_value=process), \
                mock.patch.object(self.box, "task") as task, \
                mock.patch.object(cli.rel, "load_manifest", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "active_manifest", return_value=self.old):
            status = self.box.readiness({"host": "127.0.0.1", "port": 1})
        task.assert_not_called()
        self.assertIn("graph:state_semantics_mismatch", status["scenario"]["reasons"])

    def matching_backup(self):
        self.layout.config.write_text("{}")
        config.write_json(self.layout.bindings("old") / "policy.json", {})
        recovery.identify(self.layout.state, self.old, "c" * 64)
        meta = box_state.create(self.layout, label="pre-update", release=recovery.record(self.old, "c" * 64))
        recovery.identify(self.layout.state, self.new, "b" * 64)
        return meta

    def test_damaged_matching_backup_refuses_before_stop_or_start(self):
        meta = self.matching_backup()
        path = self.layout.backups / meta["name"] / "state/service/service.sqlite"
        path.write_bytes(b"corrupt")
        before = box_state.counts(self.layout.state)
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate") as activate:
            with self.assertRaises(cli.Failed):
                self.box.rollback(self.cfg, "old")
        self.assertEqual(box_state.counts(self.layout.state), before)
        self.box.supervisor.stop.assert_not_called()
        activate.assert_not_called()

    def test_backup_with_same_name_but_wrong_manifest_cannot_authorize_writer(self):
        meta = self.matching_backup()
        path = self.layout.backups / meta["name"] / "backup.json"
        meta["release"]["manifest_sha256"] = "e" * 64
        path.write_text(json.dumps(meta))
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate") as activate:
            with self.assertRaises(cli.Failed):
                self.box.rollback(self.cfg, "old")
        activate.assert_not_called()

    def test_interrupted_update_reuses_original_verified_backup_after_new_state_was_opened(self):
        meta = self.matching_backup()
        journal = self.box.journal()
        journal["update"] = {"state": "IN_PROGRESS", "from": "old", "to": "new", "backup": meta["name"]}
        self.box.save(journal)
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)):
            result = self.box.pre_update_backup(recovery.record(self.old, "c" * 64))
        self.assertTrue(result["reused"])
        self.box.supervisor.stop.assert_not_called()

    def test_interrupted_update_cannot_reuse_a_backup_of_another_release(self):
        meta = self.matching_backup()
        journal = self.box.journal()
        journal["update"] = {"state": "IN_PROGRESS", "from": "old", "to": "new", "backup": meta["name"]}
        self.box.save(journal)
        meta["release"]["manifest_sha256"] = "f" * 64
        (self.layout.backups / meta["name"] / "backup.json").write_text(json.dumps(meta))
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)):
            with self.assertRaises(box_state.BackupError):
                self.box.pre_update_backup(recovery.record(self.old, "c" * 64))

    def test_failed_start_leaves_durable_hold_and_safety_backup(self):
        self.matching_backup()
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate", return_value={"process_ready": False, "problems": ["down"]}):
            with self.assertRaisesRegex(cli.Failed, "recovery_start_failed"):
                self.box.rollback(self.cfg, "old")
        pending = recovery.pending(self.layout.state)
        self.assertEqual(pending["phase"], "READY_TO_START")
        self.assertTrue((self.layout.backups / pending["safety_backup"] / "backup.json").is_file())
        self.assertEqual(recovery.read_identity(self.layout.state)["semantics"]["extractor_profile"],
                         "http-requests-4")

    def test_failed_recovery_can_restore_original_safety_set_with_same_guard(self):
        self.matching_backup()
        config.write_json(self.layout.bindings("new") / "policy.json", {"original": True})
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate", return_value={"process_ready": False, "problems": ["down"]}):
            with self.assertRaises(cli.Failed):
                self.box.rollback(self.cfg, "old")
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.new, "b" * 64)), \
                mock.patch.object(self.box, "activate", return_value={"process_ready": True, "problems": []}):
            result = self.box.abort_recovery(self.cfg)
        self.assertEqual(result["mode"], "restored_backup")
        self.assertEqual(recovery.read_identity(self.layout.state)["semantics"]["extractor_profile"],
                         "http-requests-6")
        self.assertIsNone(recovery.pending(self.layout.state))

    def test_retry_of_failed_abort_resumes_same_safety_target(self):
        self.matching_backup()
        config.write_json(self.layout.bindings("new") / "policy.json", {"original": True})
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.old, "c" * 64)), \
                mock.patch.object(self.box, "activate", return_value={"process_ready": False, "problems": ["down"]}):
            with self.assertRaises(cli.Failed):
                self.box.rollback(self.cfg, "old")
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.new, "b" * 64)), \
                mock.patch.object(self.box, "activate", return_value={"process_ready": False, "problems": ["down"]}):
            with self.assertRaises(cli.Failed):
                self.box.abort_recovery(self.cfg)
        with mock.patch.object(cli.rel, "verify_tree", return_value=(self.new, "b" * 64)), \
                mock.patch.object(self.box, "activate", return_value={"process_ready": True, "problems": []}):
            result = self.box.abort_recovery(self.cfg)
        self.assertEqual(result["to"], "new")


class SemanticContract(unittest.TestCase):
    def test_unchanged_install_does_not_clear_recovery_gate_or_checkpoint_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            m = manifest("x", "p")
            recovery.identify(state, m, "d" * 64, reconcile=True, token="matching-backup")
            recovery.identify(state, m, "d" * 64)
            value = recovery.read_identity(state)
            self.assertTrue(value["reconcile_required"])
            self.assertEqual(value["recovery_token"], "matching-backup")

    def test_equality_is_not_profile_number_order(self):
        m = manifest("x", "arbitrary-profile-without-number")
        self.assertEqual(recovery.semantics(m, "d" * 64)["extractor_profile"],
                         "arbitrary-profile-without-number")

    def test_unknown_protocol_is_closed(self):
        m = manifest("x", "p")
        m["contracts"]["recovery"]["protocol"] = 2
        with self.assertRaises(release.ReleaseError):
            recovery.semantics(m, "d" * 64)

    def test_incomplete_transition_blocks_start_even_with_matching_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            m = manifest("x", "p")
            recovery.identify(state, m, "d" * 64)
            (state / recovery.TRANSITION).write_text(json.dumps({"phase": "RESTORING"}))
            with self.assertRaisesRegex(release.ReleaseError, "recovery_unfinished"):
                recovery.check_start(state, m, "d" * 64)

    def test_same_semantics_wrong_process_identity_is_not_ready(self):
        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp)
            recovery.identify(state, manifest("x", "p"), "d" * 64)
            with self.assertRaisesRegex(release.ReleaseError, "state_semantics_mismatch"):
                recovery.check_start(state, manifest("y", "p"), "e" * 64)


class LegacyGenerationAdapter(unittest.TestCase):
    def test_new_version_already_queued_is_not_revoked_by_recovery_reopen(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = ServiceStore(Path(tmp) / "queue.sqlite")
            rid = "github:acme/orders#7"
            store.apply_snapshot(resource_id=rid, provider="github", kind="pull_request", version="new-head",
                                 snapshot={}, event_id="recovered-new-head")
            legacy_reopen(store, {"github"}, "box_recovery")
            self.assertEqual(store.resource(rid)["generation"], 1)
            self.assertEqual(len(store.jobs(rid)), 1)


@unittest.skipIf(os.name == "nt", "POSIX SIGTERM of a process-supervisor guard")
class GuardProcessLifetime(unittest.TestCase):
    def test_stopping_guard_stops_its_sqlite_preflight_writer_before_return(self):
        self.check_stop(signal.SIGTERM)

    def test_killed_guard_cannot_leave_an_orphan_sqlite_writer(self):
        self.check_stop(signal.SIGKILL)

    def check_stop(self, stop_signal):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            writer = root / "writer.py"
            writer.write_text("import os,sqlite3,time,sys\nfrom pathlib import Path\n"
                              "Path(sys.argv[2]).write_text(str(os.getpid()))\n"
                              "db=sqlite3.connect(sys.argv[1]); db.execute('CREATE TABLE ticks(x)'); db.commit()\n"
                              "while True:\n db.execute('INSERT INTO ticks VALUES(1)'); db.commit(); time.sleep(.02)\n")
            command = [sys.executable, str(writer), str(root / "state.sqlite"), str(root / "pid")]
            parent = subprocess.Popen([sys.executable, "-c",
                                       "from tools.agent_service.box.guard import run_preflight; "
                                       f"run_preflight({command!r})"], stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 5
                while not (root / "pid").exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                time.sleep(.1)
                parent.send_signal(stop_signal)
                parent.wait(timeout=5)
                db = sqlite3.connect(root / "state.sqlite")
                try:
                    before = db.execute("SELECT count(*) FROM ticks").fetchone()[0]
                    time.sleep(.15)
                    after = db.execute("SELECT count(*) FROM ticks").fetchone()[0]
                    self.assertEqual(after, before, "orphan preflight still writes after supervisor stop")
                finally:
                    db.close()
            finally:
                if parent.poll() is None:
                    parent.kill()
                    parent.wait()
                if (root / "pid").exists():
                    try:
                        os.kill(int((root / "pid").read_text()), signal.SIGKILL)
                    except ProcessLookupError:
                        pass
