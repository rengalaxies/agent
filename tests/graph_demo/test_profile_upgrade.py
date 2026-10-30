"""A saved demo result must not retain CURRENT across an extractor upgrade."""
from unittest.mock import patch

from fastapi.testclient import TestClient

from agent_graph_demo.api import create_app
from .helpers import DemoCase


class ProfileUpgradeTests(DemoCase):
    def test_saved_graph_and_knowledge_are_stale_and_cannot_accept_a_correction(self):
        cid = self.prepare()
        client = TestClient(create_app(self.settings))
        client.auth = ("operator", "test-password")
        client.headers["Origin"] = "http://testserver"
        base = f"/api/demo/sessions/{self.sid}"
        original = client.get(base + "/graph").json()
        body = dict(expected_revision=1, idempotency_key="before-upgrade", context_id=cid,
                    evidence_id=original["dependencies"][0]["evidence"][0]["evidence_id"],
                    key="owner", statement="Owner reviewed this source", supersedes=None)
        self.assertEqual(client.post(base + "/proposals", json=body).status_code, 202)
        self.worker.run_once()
        prior = client.get(base + "/graph").json()
        ref = self.store.session(self.sid)["graph_ref"]
        self.assertEqual(prior["freshness"]["status"], "CURRENT")
        self.assertEqual(prior["proposals"][0]["status"], "CURRENT")
        with patch("agent_graph_demo.api.PROFILE", "author-next-extractor", create=True), \
                patch("agent_graph_demo.contracts.PROFILE", "author-next-extractor"):
            stale = client.get(base + "/graph").json()
            self.assertEqual(stale["freshness"]["status"], "STALE")
            self.assertEqual(stale["freshness"]["reason"], "extractor_profile_changed")
            self.assertEqual(stale["proposals"][0]["status"], "STALE")
            self.assertEqual(stale["proposals"][0]["freshness"]["status"], "STALE")
            self.assertEqual(stale["proposals"][0]["id"], prior["proposals"][0]["id"])
            body.update(idempotency_key="after-upgrade")
            response = client.post(base + "/proposals", json=body)
            self.assertEqual(response.status_code, 409)
            self.assertEqual(response.json()["error"], "stale_context")
            self.assertEqual(client.post(base + "/proposals", json={**body, "idempotency_key": "before-upgrade"}).status_code, 202)
        self.assertEqual(self.store.session(self.sid)["graph_ref"], ref)
        self.assertEqual(self.store.get_artifact(self.sid, ref)["freshness"]["status"], "CURRENT")
        self.assertEqual(client.get(base + "/graph").json()["freshness"]["status"], "CURRENT")
