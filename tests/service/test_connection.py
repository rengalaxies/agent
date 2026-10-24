"""One-time connection: App token exchange, secrets by reference, dry-run publication, status access."""

import json
import os
from pathlib import Path
import tempfile
import unittest
import urllib.error
import urllib.request

from agent_service.config import ServiceConfig, build
from agent_service.connectors.github import GitHubAppAuth, GitHubConnector
from agent_service.http import AuthError, HttpClient
from agent_service.service import Service

from tests.service.helpers import (BASE, CONSUMER, CONSUMER_SHA, GH_SECRET, HEAD1, REPO, Clock, ScriptedAnalyzer,
                                   ServiceCase)
from agent_service.stands import GitHubStand, sign


def _rsa_pem():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption())
    return key, pem


class GitHubAppAuthTest(unittest.TestCase):
    def setUp(self):
        self.stand = GitHubStand()
        self.addCleanup(self.stand.close)
        self.stand.add_pr(REPO, 7, head=HEAD1, base=BASE)
        self.key, self.pem = _rsa_pem()
        self.stand.app_id, self.stand.app_public_key = "12345", self.key.public_key()
        self.clock = Clock()

    def connector(self, pem):
        client = HttpClient(self.stand.url, allow_loopback_http=True, clock=self.clock)
        auth = GitHubAppAuth(client, "12345", 99, pem, self.clock)
        return GitHubConnector(client, auth, repositories=[REPO], bot_login="agent-service[bot]",
                               webhook_secret=GH_SECRET, clock=self.clock)

    def test_installation_token_is_exchanged_once_and_reused(self):
        connector = self.connector(self.pem)
        self.assertEqual(connector.fetch("github:acme/orders#7").data["head_sha"], HEAD1)
        connector.fetch("github:acme/orders#7")
        self.assertEqual(self.stand.token_exchanges, 1)

    def test_wrong_app_key_is_a_connection_problem(self):
        _, other = _rsa_pem()
        with self.assertRaises(AuthError):
            self.connector(other).fetch("github:acme/orders#7")


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.stand = GitHubStand()
        self.addCleanup(self.stand.close)
        self.stand.add_pr(REPO, 7, head=HEAD1, base=BASE)
        self.stand.branches.update({(REPO, "main"): BASE, (CONSUMER, "main"): CONSUMER_SHA})
        self.config = ServiceConfig.model_validate({
            "installation_id": "inst-1", "environment": "test",
            "state_path": str(Path(self.tmp.name) / "state.sqlite"), "publication": "dry_run",
            "allow_loopback_http": True,
            "github": {"api_base": self.stand.url, "repositories": [REPO], "bot_login": "agent-service[bot]",
                       "read_repositories": {REPO: "main", CONSUMER: "main"},
                       "repository_ids": {REPO: "orders", CONSUMER: "reporting"},
                       "webhook_secret_env": "T_GH_WEBHOOK", "auth": {"kind": "token", "token_env": "T_GH_TOKEN"}},
        })

    def test_missing_secret_names_the_variable_not_a_value(self):
        os.environ.pop("T_GH_WEBHOOK", None)
        os.environ["T_GH_TOKEN"] = "do-not-print-me"
        self.addCleanup(os.environ.pop, "T_GH_TOKEN", None)
        with self.assertRaises(ValueError) as error:
            build(self.config)
        self.assertEqual(str(error.exception), "missing_secret_env:T_GH_WEBHOOK")

    def test_dry_run_publishes_to_the_sink_and_never_writes_to_the_provider(self):
        secrets = {"T_GH_WEBHOOK": GH_SECRET.decode(), "T_GH_TOKEN": self.stand.token}
        store, connectors, backends = build(self.config, env_secret=secrets.__getitem__)
        service = Service(store=store, connectors=connectors, backends=backends, analyzer=ScriptedAnalyzer(),
                          installation_id="inst-1", environment="test")
        body = json.dumps({"action": "opened", "number": 7, "repository": {"full_name": REPO},
                           "pull_request": {"head": {"sha": HEAD1, "ref": "f"}, "base": {"ref": "main"}}}).encode()
        status, _ = service.receive("github", {"X-GitHub-Event": "pull_request", "X-GitHub-Delivery": "d1",
                                               "X-Hub-Signature-256": sign(GH_SECRET, body)}, body)
        self.assertEqual(status, 202)
        service.run_until_idle()
        self.assertEqual([m for m, _ in self.stand.log if m != "GET"], [])
        [written] = list((Path(self.tmp.name) / "dry-run-comments" / "github").glob("*.json"))
        self.assertIn("Возможное влияние", written.read_text(encoding="utf-8"))


class StatusEndpointTest(ServiceCase):
    def get(self, headers):
        req = urllib.request.Request(self.receiver.url + "/status", headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            with exc:
                return exc.code, {}

    def test_status_requires_the_token_and_contains_no_secrets(self):
        self.assertEqual(self.get({})[0], 401)
        self.github.revoked = True
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.service.run_until_idle()
        status, body = self.get({"Authorization": "Bearer status-token"})
        self.assertEqual(status, 200)
        self.assertEqual(body["notices"][0]["kind"], "connection_unauthorized")
        text = json.dumps(body)
        for secret in (self.github.token, GH_SECRET.decode(), "jira-test-token"):
            self.assertNotIn(secret, text)


if __name__ == "__main__":
    unittest.main()
