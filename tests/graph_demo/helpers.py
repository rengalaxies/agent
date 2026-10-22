import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid

from agent_graph_demo.contracts import DemoSettings, JobRequest, now
from agent_graph_demo.graph_cli import GraphCLI
from agent_graph_demo.snapshots import Snapshots, atomic_json
from agent_graph_demo.store import Store
from agent_graph_demo.worker import Worker

CORE = Path(os.environ.get("DEMO_CORE_ROOT", str(Path(__file__).resolve().parents[2])))


class DemoCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.sid = str(uuid.uuid4())
        self.store = Store(self.root / "state")
        self.snap = Snapshots(self.root / "state", "TEST_PRODUCT")
        self.store.create(self.sid, "operator", self.snap.create(self.sid))
        self.cli = GraphCLI(CORE)
        self.worker = Worker(self.store, self.snap, self.cli)
        self.auth = self.root / "auth.json"
        self.auth.write_text(
            json.dumps(
                {
                    "users": [
                        dict(
                            subject="operator",
                            role="operator",
                            password_sha256=hashlib.sha256(
                                b"test-password"
                            ).hexdigest(),
                        ),
                        dict(
                            subject="viewer",
                            role="viewer",
                            allowed_session_ids=[self.sid],
                            password_sha256=hashlib.sha256(
                                b"view-password"
                            ).hexdigest(),
                        ),
                        dict(
                            subject="stranger",
                            role="operator",
                            password_sha256=hashlib.sha256(
                                b"other-password"
                            ).hexdigest(),
                        ),
                    ]
                }
            )
        )
        self.registry = self.root / "runtime/active.json"
        atomic_json(
            self.registry,
            dict(
                generation=1,
                state="STOPPED",
                session_id=None,
                project_name=None,
                manifest_sha256=None,
                observed_at=now(),
            ),
        )
        self.settings = DemoSettings(
            state_root=self.store.root,
            core_root=CORE,
            auth_config_path=self.auth,
            runtime_registry_path=self.registry,
            allowed_origins=["http://testserver"],
            start_worker=False,
            product_sha="TEST_PRODUCT",
        )

    def body(self, action="prepare_context", revision=None, key=None, **payload):
        return JobRequest(
            action=action,
            expected_revision=revision or self.store.session(self.sid)["revision"],
            idempotency_key=key or str(uuid.uuid4()),
            payload=payload,
        ).model_dump(exclude_none=True, exclude_unset=True)

    def run_job(self, action="prepare_context", **payload):
        j = self.store.enqueue(self.sid, "operator", self.body(action, **payload))
        self.worker.run_once()
        j = self.store.job(j["id"])
        self.assertIn(j["status"], ("SUCCEEDED", "PARTIAL"), j)
        return j

    def prepare(self):
        self.run_job()
        return self.store.session(self.sid)["current_context_id"]
