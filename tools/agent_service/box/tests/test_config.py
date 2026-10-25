"""The owner's single box.yaml: validation without echoing values, and what the service gets from it."""

import json
from pathlib import Path
import tempfile
import unittest

from tools.agent_service.box import config as box_config
from tools.agent_service.box.messages import explain

SECRET_LOOKING = "ghp_0123456789abcdefghijklmnopqrstuvwxyzAB"


def minimal(**overrides) -> dict:
    value = {
        "installation_id": "acme", "environment": "prod",
        "github": {"bot_login": "acme-agent[bot]", "auth": {"kind": "app", "app_id": "1", "installation_id": 2},
                   "repositories": [{"name": "acme/orders", "service": "orders", "watch_prs": True},
                                    {"name": "acme/reporting", "service": "reporting"}]},
        "jira": {"base_url": "https://acme.atlassian.net", "project_keys": ["ORD"], "bot_account_id": "bot"},
    }
    value.update(overrides)
    return value


class Load(unittest.TestCase):
    def load(self, data) -> box_config.BoxConfig:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "box.yaml"
            path.write_text(json.dumps(data), encoding="utf-8")
            return box_config.load(path)

    def test_problem_names_the_field_but_never_echoes_its_value(self):
        data = minimal(listen={"host": "127.0.0.1", "port": SECRET_LOOKING})
        with self.assertRaises(box_config.ConfigProblem) as ctx:
            self.load(data)
        text = "; ".join(ctx.exception.problems)
        self.assertIn("listen.port", text)
        self.assertNotIn(SECRET_LOOKING, text)

    def test_secret_value_in_an_unknown_field_is_not_echoed(self):
        data = minimal(github_token=SECRET_LOOKING)
        with self.assertRaises(box_config.ConfigProblem) as ctx:
            self.load(data)
        self.assertNotIn(SECRET_LOOKING, "; ".join(ctx.exception.problems))

    def test_plain_http_provider_is_refused_outside_test_stands(self):
        data = minimal()
        data["jira"]["base_url"] = "http://127.0.0.1:9000"
        with self.assertRaises(box_config.ConfigProblem):
            self.load(data)
        data["testing"] = {"allow_loopback_http": True}
        self.assertEqual(self.load(data).jira.base_url, "http://127.0.0.1:9000")

    def test_local_clone_path_is_refused_outside_test_stands(self):
        data = minimal()
        data["github"]["repositories"][0]["clone_url"] = "/srv/git/orders"
        with self.assertRaises(box_config.ConfigProblem):
            self.load(data)

    def test_some_repository_must_be_watched_for_pull_requests(self):
        data = minimal()
        data["github"]["repositories"][0]["watch_prs"] = False
        with self.assertRaises(box_config.ConfigProblem):
            self.load(data)

    def test_address_of_a_service_without_repository_is_refused(self):
        with self.assertRaises(box_config.ConfigProblem):
            self.load(minimal(service_addresses={"billing": "https://billing.internal"}))


class Example(unittest.TestCase):
    def test_shipped_example_is_a_valid_configuration(self):
        root = Path(__file__).resolve().parents[4]
        cfg = box_config.load(root / "infra" / "agent_service" / "box.example.yaml")
        self.assertEqual(cfg.publication, "dry_run")
        self.assertIsNone(cfg.model)


class Derived(unittest.TestCase):
    def setUp(self):
        self.cfg = box_config.BoxConfig.model_validate(minimal(model={
            "endpoint": "https://models.example/v1", "model": "qwen", "configuration_id": "qwen-1"}))

    def test_secret_names_follow_the_auth_kind(self):
        names = self.cfg.secret_names()
        self.assertIn("GITHUB_APP_PRIVATE_KEY_PATH", names)
        self.assertNotIn("GITHUB_TOKEN", names)
        self.assertIn("JIRA_EMAIL", names)
        self.assertIn("MODEL_API_KEY", names)

    def test_service_config_watches_only_marked_repositories_and_reads_all(self):
        svc = self.cfg.service(state=Path("/var/lib/agent-service"), policy_path=Path("/etc/p.json"),
                               constitution=Path("/c.yaml"), release_id="0.1.0+gabc")
        self.assertEqual(svc["github"]["repositories"], ["acme/orders"])
        self.assertEqual(svc["github"]["read_repositories"], {"acme/orders": "main", "acme/reporting": "main"})
        self.assertEqual(svc["analysis"]["code_version"], "0.1.0+gabc")
        self.assertNotIn("token", json.dumps(svc).replace("token_env", ""))

    def test_policy_reads_every_repository_from_its_mirror_at_a_pinned_commit(self):
        policy = self.cfg.policy(mirrors=Path("/m"), tips={"orders": "1" * 40, "reporting": "2" * 40},
                                 constitution=Path("/c.yaml"))
        roots = {r["id"]: (Path(r["root"]).name, r["snapshot"], r["revision"]) for r in policy["repositories"]}
        self.assertEqual(roots["orders"], ("orders.git", "git", "1" * 40))
        self.assertEqual(policy["model"]["allowed_endpoints"], ["https://models.example/v1"])


class Secrets(unittest.TestCase):
    def test_malformed_line_is_reported_by_number_without_its_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.env"
            path.write_text(f"GITHUB_TOKEN=x\n{SECRET_LOOKING}\n", encoding="utf-8")
            with self.assertRaises(box_config.ConfigProblem) as ctx:
                box_config.read_secrets(path)
            self.assertIn("line 2", ctx.exception.problems[0])
            self.assertNotIn(SECRET_LOOKING, ctx.exception.problems[0])

    def test_quoted_values_are_unquoted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "secrets.env"
            path.write_text('JIRA_EMAIL="bot@acme.example"\n# comment\n', encoding="utf-8")
            self.assertEqual(box_config.read_secrets(path), {"JIRA_EMAIL": "bot@acme.example"})


class Messages(unittest.TestCase):
    def test_probe_reason_names_the_source_and_the_action(self):
        text = explain("probe:github:acme/orders:connection_unauthorized")
        self.assertIn("github:acme/orders", text)
        self.assertIn("учётные данные", text)

    def test_unknown_code_is_shown_as_is_not_hidden(self):
        self.assertEqual(explain("something_new"), "something_new")


if __name__ == "__main__":
    unittest.main()
