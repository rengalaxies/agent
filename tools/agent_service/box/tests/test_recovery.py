"""Author regressions: schema equality never licenses an unknown writer."""

import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from tools.agent_service.box import cli, config, recovery, release
from tools.agent_service.box import state as box_state
from tools.agent_service.box.layout import Layout
from tools.agent_service.box.tests.test_state import make_state, RELEASE_V1


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
            config.write_json(self.layout.bindings(name) / "service.json", {})
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


class SemanticContract(unittest.TestCase):
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
