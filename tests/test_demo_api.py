"""Development-only test: no evaluation oracle is used."""
import unittest
from fastapi.testclient import TestClient
from services.demo_api import app

class DemoApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client=TestClient(app)

    def test_health_and_catalog(self):
        response=self.client.get("/healthz")
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()["engine_live"])
        self.assertFalse(response.json()["evaluation_oracle_loaded"])
        catalog=self.client.get("/api/v1/demo/scenarios")
        self.assertEqual(catalog.status_code,200)
        self.assertEqual(catalog.json()["dataset"],"development")
        self.assertGreater(len(catalog.json()["scenarios"]),0)
        self.assertNotIn("expected_decision",str(catalog.json()))

    def test_live_v2_development_case(self):
        catalog=self.client.get("/api/v1/demo/scenarios").json()["scenarios"]
        response=self.client.post("/api/v1/demo/runs",json={"scenario_id":catalog[0]["id"]})
        self.assertEqual(response.status_code,200)
        item=response.json()
        self.assertEqual(item["mode"],"V2")
        self.assertEqual(item["dataset"],"development")
        self.assertIn("decision",item)
        self.assertEqual(item["scenario_id"],catalog[0]["id"])

    def test_nonlisted_evaluation_scenario_blocked(self):
        response=self.client.post("/api/v1/demo/runs",json={"scenario_id":"NOT_IN_DEVELOPMENT"})
        self.assertEqual(response.status_code,404)
