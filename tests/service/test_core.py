"""The service on the real 2A core and the Orders/Reporting Git stand (spec section 5)."""

from pathlib import Path
import tempfile
import unittest

from agent_service.intent import match_operations
from agent_service.smoke import SmokeBench, _section, run_smoke

ORDERS = dict(id="op-orders", service="orders", method="GET", path="/orders")
BILLING = dict(id="op-billing", service="billing", method="GET", path="/orders")
INVOICES = dict(id="op-invoices", service="billing", method="POST", path="/invoices")


class IntentTest(unittest.TestCase):
    def test_route_of_two_services_needs_the_service_named(self):
        ops = [ORDERS, BILLING]
        self.assertEqual(match_operations(ops, ["Orders: GET /orders default 100 -> 20"]), (["op-orders"], "route"))
        self.assertEqual(match_operations(ops, ["GET /orders: default 100 -> 20"]), ([], "ambiguous_route"))

    def test_route_path_alone_does_not_name_a_service(self):
        # "/orders" must not count as naming the service orders.
        self.assertEqual(match_operations([ORDERS, BILLING], ["Change GET /orders/ paging"])[1], "ambiguous_route")

    def test_service_name_without_route_selects_its_operations(self):
        self.assertEqual(match_operations([ORDERS, BILLING, INVOICES], ["Billing totals are wrong"]),
                         (["op-billing", "op-invoices"], "service"))

    def test_no_mention_is_unclear_intent(self):
        self.assertEqual(match_operations([ORDERS], ["Speed up the dashboard"]), ([], "no_mention"))


class SmokeTest(unittest.TestCase):
    def test_offline_smoke_passes_every_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = run_smoke(Path(tmp))
        failed = [c for c in report["checks"] if not c["ok"]]
        self.assertEqual(failed, [])
        self.assertGreaterEqual(len(report["checks"]), 15)


class BenchCase(unittest.TestCase):
    policy = None

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.bench = SmokeBench(Path(tmp.name), policy_overrides=self.policy)
        self.addCleanup(self.bench.close)


class JiraWithoutRequirementTest(BenchCase):
    policy = {"requirements": []}

    def test_unknown_completeness_requirement_is_stated_not_assumed(self):
        self.bench.deliver_jira()
        self.bench.drain()
        [text] = self.bench.jira_texts()
        self.assertIn("requirement_unknown (reporting)", text)
        self.assertIn("whether it needs the complete collection is not known", text)
        self.assertNotIn("POSSIBLE_TRUNCATION", text)  # no diff: no claimed break


class AmbiguousJiraTest(BenchCase):
    def test_task_naming_only_the_route_abstains_instead_of_guessing_the_service(self):
        issue = self.bench.jira.issues["10012"]["fields"]
        issue["summary"] = "Уменьшить размер страницы до 20"
        issue["description"]["content"][0]["content"][0]["text"] = "GET /orders: default page_size 100 -> 20."
        self.bench.deliver_jira()
        self.bench.drain()
        [text] = self.bench.jira_texts()
        self.assertIn("intent_unclear", text)
        self.assertEqual(_section(text, "Что может затронуть", "Почему и через какой путь").strip(), "нет данных")


class UnavailableCommitTest(BenchCase):
    def test_head_missing_from_the_mirror_fails_visibly_instead_of_using_another_commit(self):
        self.bench.github.set_head("acme/orders", 7, "e" * 40)
        self.bench.deliver_pr("opened")
        self.bench.drain()
        [comment] = self.bench.pr_comments()
        self.assertIn("commit_unavailable", comment["body"])
        self.assertIn("Технический отказ анализа", comment["body"])
        self.assertNotIn("POSSIBLE_TRUNCATION", comment["body"])


class UnqualifiedModelTest(unittest.TestCase):
    def test_configured_but_unqualified_model_is_never_called(self):
        calls = []

        class Model:
            def complete_raw(self, *args, **kwargs):
                calls.append(1)
                raise AssertionError("model must not be called")

        model = dict(protocol="actions-v3", endpoint="http://127.0.0.1:9/v1/chat/completions",
                     allowed_endpoints=["http://127.0.0.1:9/v1/chat/completions"], model="qwen-test",
                     configuration_id="qwen-test-1", allow_source_transfer=True)
        with tempfile.TemporaryDirectory() as tmp:
            bench = SmokeBench(Path(tmp), policy_overrides={"model": model})
            try:
                bench.analyzer.model = Model()
                self.assertIsNone(bench.analyzer.request_settings()["model_configuration_id"])
                bench.deliver_pr("opened")
                bench.drain()
                [comment] = bench.pr_comments()
            finally:
                bench.close()
        self.assertEqual(calls, [])
        self.assertNotIn("model:", comment["body"])


if __name__ == "__main__":
    unittest.main()
