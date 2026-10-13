"""Development-only test: no evaluation oracle is used."""
import unittest
from fastapi.testclient import TestClient
from services.demo_api import app, E4_RUN_SLOT

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

    def test_live_three_process_e4(self):
        for expected in ("ACCEPT", "REJECT", "NEEDS_REVIEW"):
            with self.subTest(expected=expected):
                response=self.client.post(
                    "/api/v1/demo/distributed-runs",
                    json={"outcome":expected},
                )
                self.assertEqual(response.status_code,200,response.text[:400])
                item=response.json()
                self.assertEqual(item["architecture"],"three_independent_domain_processes")
                self.assertEqual(item["dataset"],"synthetic_E4")
                self.assertFalse(item["evaluation_oracle_loaded"])
                self.assertIn("release",item)
                self.assertEqual(item["requested_outcome"],expected)

    def test_live_verified_knowledge_graph(self):
        response=self.client.get("/api/v1/knowledge/map")
        self.assertEqual(response.status_code,200,response.text[:400])
        graph=response.json()
        self.assertEqual(graph["schema_version"],"knowledge-1")
        self.assertEqual(graph["snapshot_completeness"],"complete")
        self.assertEqual(graph["dataset"],"synthetic_E4")
        self.assertFalse(graph["evaluation_oracle_loaded"])
        self.assertEqual({n["id"] for n in graph["nodes"]},{"sales","risk","analytics"})
        self.assertGreaterEqual(len(graph["edges"]),2)
        self.assertTrue(all(e["source"]=="sales" for e in graph["edges"]))
        self.assertTrue(all(e["kind"]=="confirmed_usage" for e in graph["edges"]))
        self.assertEqual({e["target"] for e in graph["edges"]},{"risk","analytics"})
        self.assertNotIn("expected_decision",str(graph))

    def test_distributed_run_refuses_parallel_process_fanout(self):
        self.assertTrue(E4_RUN_SLOT.acquire(blocking=False))
        try:
            response=self.client.post(
                "/api/v1/demo/distributed-runs",json={"outcome":"ACCEPT"}
            )
            self.assertEqual(response.status_code,429)
        finally:
            E4_RUN_SLOT.release()
