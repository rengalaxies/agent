import uuid

from fastapi.testclient import TestClient

from agent_graph_demo.api import create_app
from agent_graph_demo.contracts import now
from agent_graph_demo.snapshots import atomic_json
from .helpers import DemoCase


class APITests(DemoCase):
    def setUp(self):
        super().setUp()
        self.app = create_app(self.settings)
        self.client = TestClient(self.app)
        self.client.auth = ("operator", "test-password")
        self.client.headers["Origin"] = "http://testserver"
        self.base = "/api/demo/sessions/" + self.sid

    def test_auth_origin_roles_and_foreign_session(self):
        anonymous = TestClient(self.app)
        self.assertEqual(anonymous.get(self.base).status_code, 401)
        self.assertEqual(anonymous.get("/").status_code, 401)
        self.client.auth = ("viewer", "view-password")
        self.assertEqual(self.client.get(self.base).status_code, 200)
        self.assertEqual(
            self.client.post(self.base + "/jobs", json=self.body()).status_code, 403
        )
        self.client.auth = ("stranger", "other-password")
        r = self.client.get(self.base)
        self.assertEqual(r.status_code, 403)
        self.assertNotIn("proposed_manifest", r.text)
        self.client.auth = ("operator", "test-password")
        del self.client.headers["Origin"]
        self.assertEqual(
            self.client.post(self.base + "/jobs", json=self.body()).status_code, 403
        )
        self.client.headers["Origin"] = "https://attacker.test"
        self.assertEqual(
            self.client.post(
                self.base + "/reset",
                json=dict(expected_revision=1, idempotency_key="x"),
            ).status_code,
            403,
        )

    def test_strict_schema_and_no_paths_or_model_configuration(self):
        for value in [
            dict(self.body(), executable="/bin/sh"),
            dict(self.body(), action="shell"),
            dict(self.body(), payload={"target_version": "B"}),
            dict(
                self.body("analyze_change", target_version="B", base_context_id="fake"),
                payload={"target_version": "A", "base_context_id": "fake"},
            ),
            dict(self.body(), payload={"root": "/etc"}),
        ]:
            self.assertEqual(
                self.client.post(self.base + "/jobs", json=value).status_code, 422
            )
        self.assertEqual(
            self.client.get(self.base + "/evidence/../../etc/passwd").status_code, 404
        )
        self.assertIn(
            "script-src 'self'", self.client.get("/").headers["content-security-policy"]
        )

    def test_selection_cas_history_and_proposed_runtime_distinction(self):
        base = self.prepare()
        current = self.client.get(self.base).json()
        self.assertEqual(current["scenario_version"], "A")
        self.assertIsNone(current["running_manifest_sha256"])
        body = self.body(
            "analyze_change", target_version="B", base_context_id=base, key="select-B"
        )
        r = self.client.post(self.base + "/jobs", json=body)
        self.assertEqual(r.status_code, 202, r.text)
        job = r.json()
        self.assertEqual((job["session_revision"], job["target_revision"]), (1, 2))
        before = self.client.get(self.base).json()
        self.assertEqual((before["scenario_version"], before["revision"]), ("A", 1))
        self.assertEqual(
            self.client.post(self.base + "/jobs", json=body).json()["id"], job["id"]
        )
        self.worker.run_once()
        after = self.client.get(self.base).json()
        self.assertEqual((after["scenario_version"], after["revision"]), ("B", 2))
        self.assertIsNone(after["running_version"])
        self.assertEqual(
            self.client.post(self.base + "/jobs", json=body).json()["id"], job["id"]
        )
        old = self.store.jobs(self.sid)[0]
        historical = self.client.get(self.base + "/graph?job_id=" + old["id"]).json()
        self.assertTrue(historical["historical"])
        self.assertEqual(historical["freshness"]["status"], "STALE")
        self.assertFalse(
            self.client.get(self.base + "/graph?job_id=" + job["id"]).json()[
                "historical"
            ]
        )
        self.assertEqual(
            self.client.get("/api/demo/jobs/" + job["id"]).json()["result"][
                "context_used_id"
            ],
            after["current_context_id"],
        )

    def test_foreign_evidence_and_base_context_rejected(self):
        base = self.prepare()
        g = self.store.get_artifact(self.sid, self.store.session(self.sid)["graph_ref"])
        eid = g["dependencies"][0]["evidence"][0]["evidence_id"]
        other = str(uuid.uuid4())
        self.store.create(other, "operator", self.snap.create(other))
        self.assertEqual(
            self.client.get(
                "/api/demo/sessions/" + other + "/evidence/" + eid
            ).status_code,
            404,
        )
        body = self.body("analyze_change", target_version="B", base_context_id=base)
        self.assertEqual(
            self.client.post(
                "/api/demo/sessions/" + other + "/jobs", json=body
            ).status_code,
            422,
        )
        e = self.client.get(self.base + "/evidence/" + eid)
        self.assertEqual(e.status_code, 200)
        self.assertEqual(e.json()["context_id"], base)

    def test_historical_refresh_diff_keeps_executed_version_after_later_selection(self):
        base = self.prepare()
        self.run_job("analyze_change", target_version="B", base_context_id=base)
        refreshed = self.run_job("prepare_context")
        context_b = self.store.session(self.sid)["current_context_id"]
        self.run_job("analyze_change", target_version="D", base_context_id=context_b)
        suffix = "?job_id=" + refreshed["id"]
        graph = self.client.get(self.base + "/graph" + suffix).json()
        diff = self.client.get(self.base + "/diff" + suffix).json()
        self.assertEqual(graph["demo_version"], "B")
        self.assertTrue(graph["historical"])
        self.assertEqual(diff["version"], "B")
        self.assertIn("B/orders/app.py", diff["text"])

    def test_reset_requires_stop_and_preserves_history_idempotently(self):
        self.prepare()
        m = self.store.session(self.sid)["proposed_manifest_sha256"]
        atomic_json(
            self.registry,
            dict(
                state="RUNNING",
                generation=2,
                session_id=self.sid,
                manifest_sha256=m,
                observed_at=now(),
            ),
        )
        body = dict(expected_revision=1, idempotency_key="reset")
        self.assertEqual(
            self.client.post(self.base + "/reset", json=body).json()["error"],
            "operator_stop_required",
        )
        atomic_json(
            self.registry,
            dict(state="UNKNOWN", generation=3, session_id=self.sid, observed_at=now()),
        )
        self.assertEqual(
            self.client.post(self.base + "/reset", json=body).json()["error"],
            "runtime_unknown",
        )
        atomic_json(
            self.registry,
            dict(state="STOPPED", generation=4, session_id=self.sid, observed_at=now()),
        )
        r = self.client.post(self.base + "/reset", json=body)
        self.assertEqual(r.status_code, 201, r.text)
        new = r.json()
        self.assertNotEqual(new["id"], self.sid)
        self.assertIsNone(new["running_manifest_sha256"])
        self.assertEqual(
            self.client.post(self.base + "/reset", json=body).json()["id"], new["id"]
        )
        self.assertTrue(self.store.session(self.sid)["closed"])
        self.assertTrue(self.store.jobs(self.sid)[0]["result_ref"])

    def test_model_unavailable_and_external_import_separate(self):
        base = self.prepare()
        r = self.client.post(
            self.base + "/jobs", json=self.body("investigate", context_id=base)
        )
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()["error"], "model_unavailable")
        r = self.client.get(self.base).json()
        self.assertEqual(r["checks"], [])
        self.assertEqual(r["model"]["status"], "UNAVAILABLE")

    def test_correction_uses_server_owned_exact_evidence_current_revision(self):
        cid = self.prepare()
        g = self.store.get_artifact(self.sid, self.store.session(self.sid)["graph_ref"])
        body = dict(
            expected_revision=1,
            idempotency_key="human",
            context_id=cid,
            evidence_id=g["dependencies"][0]["evidence"][0]["evidence_id"],
            key="knowledge-note",
            statement="A human note, not a release approval",
            supersedes=None,
        )
        response = self.client.post(self.base + "/proposals", json=body)
        self.assertEqual(response.status_code, 202, response.text)
        self.worker.run_once()
        g = self.client.get(self.base + "/graph").json()
        self.assertEqual(g["proposals"][0]["trust"], "HUMAN_CORRECTION")
        self.assertEqual(g["proposals"][0]["actor"], "operator")
        self.assertEqual(len(g["dependencies"]), 3)
        malicious = {**body, "idempotency_key": "bad", "quote": "injected"}
        self.assertEqual(
            self.client.post(self.base + "/proposals", json=malicious).status_code, 422
        )
