from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
import time
import uuid

from agent_graph_demo.contracts import DemoError
from agent_graph_demo.worker import Worker
from .helpers import CORE, DemoCase


class JobTests(DemoCase):
    def test_idempotency_precedes_stale_revision_and_conflicts(self):
        body = self.body(key="repeat")
        j = self.store.enqueue(self.sid, "operator", body)
        self.worker.run_once()
        self.assertEqual(self.store.enqueue(self.sid, "operator", body)["id"], j["id"])
        with self.assertRaisesRegex(DemoError, "idempotency_conflict"):
            self.store.enqueue(
                self.sid, "operator", {**body, "payload": {"task": "changed"}}
            )

    def test_concurrent_version_selection_one_reservation_and_proposed_running_separate(
        self,
    ):
        base = self.prepare()

        def submit(v):
            try:
                return self.store.enqueue(
                    self.sid,
                    "operator",
                    self.body(
                        "analyze_change",
                        revision=1,
                        target_version=v,
                        base_context_id=base,
                    ),
                )
            except DemoError as e:
                return e.code

        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(submit, ["B", "D"]))
        accepted = [r for r in outcomes if isinstance(r, dict)]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(self.store.session(self.sid)["scenario_version"], "A")
        self.assertFalse(self.store.session(self.sid)["needs_refresh"])
        self.assertEqual(self.store.session(self.sid)["revision"], 1)
        self.worker.run_once()
        s = self.store.session(self.sid)
        self.assertEqual(s["scenario_version"], accepted[0]["target_version"])
        self.assertEqual(s["revision"], 2)
        self.assertIsNone(s["pending_job_id"])
        self.assertNotIn("running_manifest_sha256", s)

    def test_cancellation_after_materialization_restores_published_bytes(self):
        base = self.prepare()
        body = self.body("analyze_change", target_version="B", base_context_id=base)
        j = self.store.enqueue(self.sid, "operator", body)

        def cancel(stage, job):
            if stage == "materialized":
                text = (
                    self.snap.session_root(self.sid) / "work/orders/app.py"
                ).read_text()
                self.assertIn("None = 100", text)
                self.store.cancel(job["id"])

        Worker(self.store, self.snap, self.cli, hook=cancel).run_once()
        self.assertEqual(self.store.job(j["id"])["status"], "CANCELLED")
        self.assertEqual(self.store.session(self.sid)["revision"], 1)
        self.assertIn(
            "None = None",
            (self.snap.session_root(self.sid) / "work/orders/app.py").read_text(),
        )
        self.assertIsNone(self.store.session(self.sid)["pending_job_id"])

    def test_failure_before_publication_restores_and_does_not_publish_late_result(self):
        base = self.prepare()
        j = self.store.enqueue(
            self.sid,
            "operator",
            self.body("analyze_change", target_version="B", base_context_id=base),
        )

        def fail(stage, job):
            if stage == "before_publish":
                raise DemoError("injected_failure")

        Worker(self.store, self.snap, self.cli, hook=fail).run_once()
        self.assertEqual(self.store.job(j["id"])["status"], "FAILED")
        self.assertEqual(self.store.session(self.sid)["current_context_id"], base)
        self.assertTrue(self.store.session(self.sid)["needs_refresh"])
        self.assertEqual(self.store.session(self.sid)["scenario_version"], "A")

    def test_real_process_crash_recovery_unknown_no_retry(self):
        base = self.prepare()
        j = self.store.enqueue(
            self.sid,
            "operator",
            self.body("analyze_change", target_version="B", base_context_id=base),
        )
        marker = self.root / "materialized"
        code = """
import os,time
from pathlib import Path
from agent_graph_demo.store import Store
from agent_graph_demo.snapshots import Snapshots
from agent_graph_demo.graph_cli import GraphCLI
from agent_graph_demo.worker import Worker
root=Path(os.environ['TEST_STATE']);marker=Path(os.environ['TEST_MARKER'])
def hook(stage,j):
 if stage=='materialized':
  marker.touch()
  while True: time.sleep(.05)
Worker(Store(root),Snapshots(root,'TEST_PRODUCT'),GraphCLI(os.environ['TEST_CORE']),hook=hook).run_once()
"""
        proc = subprocess.Popen(
            [sys.executable, "-c", code],
            env={
                **os.environ,
                "TEST_STATE": str(self.store.root),
                "TEST_MARKER": str(marker),
                "TEST_CORE": str(CORE),
            },
        )
        try:
            deadline = time.monotonic() + 10
            while not marker.exists() and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(marker.exists())
            proc.kill()
            proc.wait()
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait()
        self.assertIn(
            "None = 100",
            (self.snap.session_root(self.sid) / "work/orders/app.py").read_text(),
        )
        self.worker.recover()
        recovered = self.store.job(j["id"])
        self.assertEqual(recovered["status"], "UNKNOWN_AFTER_RESTART")
        self.assertEqual(self.store.session(self.sid)["revision"], 1)
        self.assertIn(
            "None = None",
            (self.snap.session_root(self.sid) / "work/orders/app.py").read_text(),
        )
        self.assertFalse(self.worker.run_once())
        self.assertTrue(self.store.jobs(self.sid)[0]["result_ref"])

    def test_one_running_and_four_waiting_then_queue_full(self):
        self.store.enqueue(self.sid, "operator", self.body())
        self.assertIsNotNone(self.store.claim())
        self.assertIsNone(self.store.claim())
        for _ in range(4):
            sid = str(uuid.uuid4())
            self.store.create(sid, "operator", self.snap.create(sid))
            self.store.enqueue(sid, "operator", self.body())
        sid = str(uuid.uuid4())
        self.store.create(sid, "operator", self.snap.create(sid))
        with self.assertRaisesRegex(DemoError, "queue_full"):
            self.store.enqueue(sid, "operator", self.body())
        with self.store.connect() as c:
            self.assertEqual(
                c.execute(
                    "SELECT count(*) FROM jobs WHERE status='RUNNING'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                c.execute("SELECT count(*) FROM jobs WHERE status='QUEUED'").fetchone()[
                    0
                ],
                4,
            )

    def test_cross_session_context_cannot_authorize_selection(self):
        base = self.prepare()
        sid = str(uuid.uuid4())
        self.store.create(sid, "operator", self.snap.create(sid))
        with self.assertRaisesRegex(DemoError, "context_not_published_here"):
            self.store.enqueue(
                sid,
                "operator",
                self.body("analyze_change", target_version="B", base_context_id=base),
            )
