"""Fault-injection boundary tests; real HTTP/container acceptance is a separate suite."""

import json
from pathlib import Path
from unittest.mock import patch
import uuid

from agent_graph_demo.contracts import DemoError, now
from agent_graph_demo.runtime import observe
from agent_graph_demo.snapshots import atomic_json
from tools.agent_graph_demo.runtime_guard import RuntimeGuard
from tools.agent_graph_demo.ingest_receipt import ingest
from .helpers import DemoCase


class RunnerTests(DemoCase):
    def guard(self):
        return RuntimeGuard(
            self.store.root, self.root / "runtime", "sha256:" + "1" * 64, "TEST_PRODUCT"
        )

    def running(self, state="RUNNING"):
        m = self.snap.manifest(self.sid, "A")
        r = dict(
            state=state,
            generation=3,
            session_id=self.sid,
            project_name="agent-graph-demo-sbx-" + self.sid,
            manifest_sha256=m["manifest_sha256"],
            observed_at=now(),
        )
        atomic_json(self.registry, r)
        return r

    def test_generation_cas_fails_before_any_docker_mutation(self):
        g = self.guard()
        self.running()
        with patch.object(g, "docker") as docker:
            with self.assertRaisesRegex(DemoError, "runtime_generation_conflict"):
                g.stop(self.sid, 2)
            docker.assert_not_called()

    def test_failed_down_marks_unknown_and_blocks_activation_until_reconcile(self):
        g = self.guard()
        self.running()
        with (
            patch.object(g, "compare", return_value=[]),
            patch.object(g, "down", side_effect=DemoError("injected_down_failure")),
        ):
            with self.assertRaisesRegex(DemoError, "injected_down_failure"):
                g.stop(self.sid, 3)
        self.assertEqual(g.read()["state"], "UNKNOWN")
        with g.exclusive():
            with self.assertRaisesRegex(DemoError, "runtime_reconciliation_required"):
                g.activate_locked(
                    self.sid,
                    self.snap.manifest(self.sid, "A"),
                    Path("/unused"),
                    Path("/unused"),
                    4,
                )
        with (
            patch.object(g, "compare", return_value=[]),
            patch.object(g, "down") as down,
        ):
            reconciled = g.reconcile(4)
            self.assertEqual(reconciled["state"], "STOPPED")
            down.assert_called_once()

    def test_interrupted_start_is_not_resumed_by_stop_or_observe(self):
        g = self.guard()
        self.running("STARTING")
        for operation in (lambda: g.stop(self.sid, 3), lambda: g.refresh(3)):
            with self.assertRaisesRegex(DemoError, "runtime_reconciliation_required"):
                operation()

    def test_foreign_project_is_not_in_owned_inventory(self):
        g = self.guard()
        sid = str(uuid.uuid4())

        def container(project):
            return {
                "Config": {"Labels": {"com.docker.compose.project": project}},
                "State": {"Running": True},
            }

        containers = [
            container("agent-graph-demo"),
            container("unrelated-control"),
            container("agent-graph-demo-sbx-" + sid),
            container("agent-graph-demo-sbx-invalid"),
        ]
        with patch.object(g, "docker", side_effect=["a b c d", json.dumps(containers)]):
            owned = g.inventory()
            self.assertEqual(len(owned), 1)
            self.assertEqual(
                owned[0]["Config"]["Labels"]["com.docker.compose.project"],
                "agent-graph-demo-sbx-" + sid,
            )

    def test_unknown_or_stale_observation_never_running(self):
        self.assertEqual(observe(self.root / "missing")["state"], "UNKNOWN")
        self.running()
        self.assertEqual(observe(self.registry)["state"], "RUNNING")
        r = json.loads(self.registry.read_text())
        r["observed_at"] = "2000-01-01T00:00:00+00:00"
        atomic_json(self.registry, r)
        self.assertEqual(observe(self.registry)["state"], "UNKNOWN")

    def test_imported_pass_is_external_report_not_local_receipt(self):
        s = self.store.session(self.sid)
        receipt = dict(
            id="explicit-external-fixture",
            session_id=self.sid,
            session_revision=1,
            version="A",
            proposed_manifest_sha256=s["proposed_manifest_sha256"],
            running_manifest_sha256=s["proposed_manifest_sha256"],
            dataset_sha256="0" * 64,
            status="PASS",
            consumers={},
        )
        path = self.root / "external.json"
        path.write_text(json.dumps(receipt))
        ingest(self.store.root, path)
        self.assertFalse(self.store.artifacts(self.sid, "receipt"))
        external = self.store.artifacts(self.sid, "external_report")[0]
        self.assertEqual(external["origin"], "external_import")
        self.assertEqual(external["graph_status"], "EXTERNAL_REPORTED")
        self.assertFalse(external["independently_verified"])
