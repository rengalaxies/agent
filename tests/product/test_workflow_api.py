import copy
from datetime import timedelta
import json
import time
import unittest

from fastapi.testclient import TestClient

from change_completion.delivery import DeliveryConfig
from change_completion.models import Action, TransitionSpec
from change_completion.runtime import encode
from change_completion.verification import TrustPolicy, context_digest, digest_bytes
from change_completion.web_api import create_product_app
from change_completion.workflow_service import Principal, WorkflowService
from change_completion.workflow_store import WorkflowStore
from tests.product import test_runtime as fixture_module


class FakeGateway:
    config = DeliveryConfig(endpoint="https://fixture.invalid/send", allow_send=True)
    def __init__(self):
        self.calls = []
        self.unknown = False
    def send(self, kind, payload, key):
        self.calls.append((kind, payload, key))
        return ({"status": "unknown", "receipt": None, "reason_codes": ["test_unknown"]} if self.unknown else
                {"status": "delivered", "receipt": {"url": "https://fixture.invalid/pr/1", "external_id": "1"}, "reason_codes": []})


class WorkflowAPITest(unittest.TestCase):
    def setUp(self):
        self.lab = fixture_module.RuntimeTest()
        self.lab.setUp()
        self.addCleanup(self.lab.doCleanups)
        # Deployment-authorized send actions, prepared before candidate execution.
        data = self.lab.spec.model_dump(mode="json")
        data["allowed_actions"] += ["publish_pr", "notify"]
        self.lab.spec = TransitionSpec.model_validate(data)
        suite = json.loads(self.lab.suite)
        suite["context_sha256"] = context_digest(self.lab.spec)
        self.lab.suite = encode(suite)
        policy = self.lab.policy
        send_grant = policy.grants[0].model_copy(update={"grant_id": "publisher-grant", "actor": "publisher",
                                                        "actions": (Action.PUBLISH_PR, Action.NOTIFY)})
        self.lab.policy = TrustPolicy(frozenset({digest_bytes(self.lab.suite)}), policy.approved_owners, (*policy.grants, send_grant))
        run = self.lab.run_case()
        self.assertEqual(run["status"], "READY_FOR_REVIEW", run)
        self.run_id = run["run_id"]
        self.clock = fixture_module.NOW
        self.workflows = WorkflowStore(self.lab.base / "workflow/state.sqlite3")
        self.gateway = FakeGateway()
        self.service = WorkflowService(self.lab.store, self.workflows, self.lab.repo,
                                       lambda: self.lab.spec, lambda: self.lab.suite,
                                       lambda uri: (self.lab.fixtures / uri).read_bytes(), lambda: self.lab.policy,
                                       worker_actor="demo-worker", gateway=self.gateway, clock=lambda: self.clock,
                                       destinations={"analytics": {"repository": "fixture/analytics", "base_branch": "main"}},
                                       notification_routes={"analytics-owner": "channel-analytics", "audit-owner": "channel-audit"})
        scope = frozenset({self.lab.spec.transition_id})
        all_permissions = frozenset({"read", "review", "prepare_delivery", "send_delivery", "tick", "revalidate"})
        self.principals = {actor: Principal(actor, scope, all_permissions) for actor in
                           ("analytics-owner", "audit-owner", "business-acceptor", "publisher")}
        self.tokens = {("test-token-"+actor): p for actor, p in self.principals.items()}
        self.app = create_product_app(self.service, self.tokens, tick_seconds=.1)
        self.client = TestClient(self.app)
        self.path = "/api/runs/"+self.run_id

    def test_c3_proposal_does_not_require_production_approval(self):
        # An approved high-risk scope can request review without granting a deploy.
        data = self.lab.spec.model_dump(mode="json")
        data["criticality"] = 3
        data["critical_risks"] = ["financial calculation"]
        self.lab.spec = TransitionSpec.model_validate(data)
        suite = json.loads(self.lab.suite)
        suite["context_sha256"] = context_digest(self.lab.spec)
        self.lab.suite = encode(suite)
        old = self.lab.policy
        self.lab.policy = TrustPolicy(frozenset({digest_bytes(self.lab.suite)}), old.approved_owners,
                                      old.grants, old.revoked_grant_ids, old.minimum_cases)
        run = self.lab.run_case()
        self.assertEqual(run["status"], "READY_FOR_REVIEW", run)
        outcome = self.service.deliver(run["run_id"], self.principals["publisher"], "pr", send=True)
        self.assertEqual(outcome["status"], "delivered")
        self.assertEqual(len(self.gateway.calls), 1)
        self.assertEqual(self.workflows.get(run["run_id"])["status"], "PENDING")

    def headers(self, actor="publisher"):
        return {"Authorization": "Bearer test-token-"+actor}

    def detail(self):
        response = self.client.get(self.path, headers=self.headers())
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_shell_public_data_auth_and_actor_spoof(self):
        shell = self.client.get("/")
        self.assertEqual(shell.status_code, 200)
        self.assertIn("sha256-", shell.headers["content-security-policy"])
        self.assertEqual(self.client.get(self.path).status_code, 401)
        digest = self.detail()["workflow"]["package_digest"]
        spoof = self.client.post(self.path+"/review", headers=self.headers("analytics-owner"),
                                 json={"decision": "approve", "package_digest": digest, "actor": "business-acceptor"})
        self.assertEqual(spoof.status_code, 422)

    def test_owners_then_acceptor_and_digest_binding(self):
        digest = self.detail()["workflow"]["package_digest"]
        body = {"decision": "approve", "package_digest": digest}
        self.assertEqual(self.client.post(self.path+"/review", headers=self.headers("business-acceptor"), json=body).status_code, 409)
        self.assertEqual(self.client.post(self.path+"/review", headers=self.headers("publisher"), json=body).status_code, 403)
        for actor in ("analytics-owner", "audit-owner", "business-acceptor"):
            response = self.client.post(self.path+"/review", headers=self.headers(actor), json=body)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["workflow"]["status"], "ACCEPTED_FOR_REVIEW")
        body["package_digest"] = "0"*64
        self.assertEqual(self.client.post(self.path+"/review", headers=self.headers("analytics-owner"), json=body).status_code, 409)

    def test_prepare_never_sends_even_enabled_gateway(self):
        response = self.client.post(self.path+"/deliver", headers=self.headers(), json={"kind": "pr"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "draft")
        self.assertIn("analytics", response.json()["draft"]["patches"])
        self.assertFalse(self.gateway.calls)

    def test_explicit_send_links_package_and_is_idempotent(self):
        body = {"kind": "pr", "send": True}
        for _ in range(2):
            response = self.client.post(self.path+"/deliver", headers=self.headers(), json=body)
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["status"], "delivered")
        self.assertEqual(len(self.gateway.calls), 1)
        payload = self.gateway.calls[0][1]
        self.assertEqual(payload["recipients"], ["analytics-owner", "audit-owner"])
        self.assertEqual(set(payload["patches"]), {"analytics"})

    def test_unknown_outcome_is_not_retried(self):
        self.gateway.unknown = True
        for _ in range(2):
            response = self.client.post(self.path+"/deliver", headers=self.headers(), json={"kind": "notification", "send": True})
            self.assertEqual(response.json()["status"], "unknown")
        self.assertEqual(len(self.gateway.calls), 1)

    def test_stale_read_and_timer_redact_cancel_and_clear_review(self):
        self.detail()
        self.client.post(self.path+"/deliver", headers=self.headers(), json={"kind": "pr"})
        self.clock = self.clock.replace(year=2028)
        result = self.service.tick()
        self.assertGreaterEqual(result["invalidated"], 1)
        detail = self.detail()
        self.assertEqual(detail["run"]["freshness"], "stale")
        self.assertNotIn("patches", detail["result"])
        self.assertNotIn("payload", detail["workflow"]["outbox"][0])
        self.assertEqual(detail["workflow"]["outbox"][0]["status"], "CANCELLED")
        self.assertEqual(detail["workflow"]["reviews"], {})

    def test_background_tick_without_api_event(self):
        with TestClient(self.app) as client:
            client.get(self.path, headers=self.headers())
            self.clock = self.clock.replace(year=2028)
            until = time.monotonic()+3
            while time.monotonic() < until:
                if self.workflows.get(self.run_id)["status"] == "STALE":
                    break
                time.sleep(.05)
            self.assertEqual(self.workflows.get(self.run_id)["status"], "STALE")

    def test_source_tamper_reject_and_explicit_reopen(self):
        digest = self.detail()["workflow"]["package_digest"]
        path = self.lab.repo / "analytics.sql"
        original = path.read_bytes()
        path.write_text("SELECT 999;")
        self.assertEqual(self.detail()["run"]["freshness"], "stale")
        path.write_bytes(original)
        self.assertEqual(self.detail()["workflow"]["status"], "STALE")
        response = self.client.post(self.path+"/revalidate", headers=self.headers(), json={"package_digest": digest})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["workflow"]["status"], "PENDING")

    def test_cross_project_and_cross_origin_and_body_limit(self):
        stranger = Principal("stranger", frozenset({"other-project"}), frozenset({"read"}))
        app = create_product_app(self.service, {"test-token-stranger": stranger})
        client = TestClient(app)
        self.assertEqual(client.get(self.path, headers={"Authorization": "Bearer test-token-stranger"}).status_code, 403)
        headers = {**self.headers(), "Origin": "https://foreign.invalid"}
        self.assertEqual(self.client.post("/api/tick", headers=headers).status_code, 403)
        self.assertEqual(self.client.post("/api/tick", headers=self.headers(), content=b"x"*20_000).status_code, 413)

    def test_no_publish_grant_or_destination_no_send(self):
        self.lab.policy = TrustPolicy(self.lab.policy.approved_suite_digests, self.lab.policy.approved_owners,
                                      tuple(g for g in self.lab.policy.grants if g.actor != "publisher"))
        response = self.client.post(self.path+"/deliver", headers=self.headers(), json={"kind": "pr", "send": True})
        self.assertEqual(response.status_code, 403)
        self.assertFalse(self.gateway.calls)

    def test_declined_owner_blocks_send(self):
        digest = self.detail()["workflow"]["package_digest"]
        self.client.post(self.path+"/review", headers=self.headers("audit-owner"), json={"decision": "reject", "package_digest": digest})
        response = self.client.post(self.path+"/deliver", headers=self.headers(), json={"kind": "pr", "send": True})
        self.assertEqual(response.status_code, 409)
        self.assertFalse(self.gateway.calls)
