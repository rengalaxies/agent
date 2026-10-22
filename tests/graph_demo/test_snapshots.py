import json
from pathlib import Path

from agent_graph_demo.contracts import DemoError
from agent_graph_demo.runtime import applicable
from examples.agent_graph_demo.oracle import DATASET_SHA256
from .helpers import DemoCase


class SnapshotTests(DemoCase):
    def test_manifest_binds_all_bytes(self):
        m = self.snap.manifest(self.sid, "A")
        self.assertNotEqual(
            m["manifest_sha256"], self.snap.manifest(self.sid, "B")["manifest_sha256"]
        )
        f = self.snap.session_root(self.sid) / "snapshots/A/corpus/reporting/client.py"
        f.chmod(0o600)
        f.write_text(f.read_text() + "# changed\n")
        with self.assertRaisesRegex(DemoError, "snapshot_bytes_changed"):
            self.snap.materialize(self.sid, "A")

    def test_roots_grants_requirements_stable_between_versions(self):
        policies = []
        for v in "ABDE":
            self.snap.materialize(self.sid, v)
            p = json.loads(
                (self.snap.session_root(self.sid) / "policy.json").read_text()
            )
            policies.append(
                [
                    {k: x for k, x in r.items() if k != "revision"}
                    for r in p["repositories"]
                ]
            )
            self.assertIsNone(p["model"])
        self.assertTrue(all(p == policies[0] for p in policies))
        self.assertIn("export", [r["id"] for r in policies[0]])

    def test_receipt_applicability_binds_revision_manifest_and_dataset(self):
        s = self.store.session(self.sid)
        r = dict(
            session_id=self.sid,
            session_revision=s["revision"],
            proposed_manifest_sha256=s["proposed_manifest_sha256"],
            running_manifest_sha256=s["proposed_manifest_sha256"],
            dataset_sha256=DATASET_SHA256,
        )
        self.assertTrue(applicable(r, s))
        for key, value in [
            ("session_id", "another"),
            ("session_revision", 0),
            ("running_manifest_sha256", "wrong"),
            ("dataset_sha256", "wrong"),
        ]:
            self.assertFalse(applicable({**r, key: value}, s))

    def test_working_paths_and_policy_cannot_contain_oracle(self):
        work = self.snap.session_root(self.sid) / "work"
        self.assertFalse(any("oracle" in f.name for f in work.rglob("*")))
        self.assertFalse(any("dataset" in f.name for f in work.rglob("*")))
        self.assertTrue(
            all(
                Path(r["root"]).parent == work
                for r in json.loads((work.parent / "policy.json").read_text())[
                    "repositories"
                ]
            )
        )
