"""Initial/recovery discovery must not lose issues older than seven days."""

import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from agent_service.http import Response
from agent_service.smoke import SmokeBench
from tests.service.helpers import ServiceCase


class JiraDiscoveryTest(ServiceCase):
    def test_bootstrap_enqueues_old_issue_without_a_pr_or_webhook(self):
        self.github.prs.clear()
        self.jira.issues["10001"]["fields"]["_epoch"] = time.time() - 30 * 86400
        self.assertEqual(self.service.reconcile()["enqueued"], 1)
        self.drain()
        self.assertEqual(len(self.jira_comments()), 1)
        self.assertEqual(self.pr_requests(), 0)
        self.assertEqual(self.service.reconcile()["enqueued"], 0)

    def test_recovery_full_listing_finds_old_issue_absent_from_restored_state(self):
        self.service.store.checkpoint("reconcile:jira", str(self.clock()))
        self.jira.issues["10001"]["fields"]["_epoch"] = time.time() - 30 * 86400
        connector = self.service.connectors["jira"]
        self.assertEqual([rid for rid, _ in connector.reconcile_candidates(None)], ["jira:10001"])

    def test_full_listing_paginates_and_keeps_the_project_scope(self):
        connector = self.service.connectors["jira"]
        issue = self.jira._public(self.jira.issues["10001"])
        pages = [Response(200, {}, json.dumps(page).encode()) for page in (
            {"issues": [], "nextPageToken": "page-two", "isLast": False},
            {"issues": [issue], "isLast": True},
        )]
        with patch.object(connector, "_call", side_effect=pages) as call:
            self.assertEqual([rid for rid, _ in connector.reconcile_candidates(None)], ["jira:10001"])
        queries = [c.kwargs["query"] for c in call.call_args_list]
        self.assertEqual(queries[0]["jql"], "project in (ORD) ORDER BY updated ASC")
        self.assertEqual(queries[1]["nextPageToken"], "page-two")
        self.assertNotIn("nextPageToken", queries[0])

    def test_incomplete_bootstrap_does_not_advance_checkpoint(self):
        connector = self.service.connectors["jira"]
        response = Response(200, {}, b'{"issues":[],"nextPageToken":"more","isLast":false}')
        with patch.object(connector, "_call", return_value=response):
            self.service.reconcile()
        self.assertIsNone(self.service.store.checkpoint("reconcile:jira"))
        self.assertIn("reconcile_failed", {n["kind"] for n in self.service.store.notices()})

    def test_recovery_preflight_applies_old_unknown_issue_without_publishing(self):
        from tools.agent_service.box import preflight
        from agent_service import __main__ as entry
        import sys

        self.github.prs.clear()
        self.service.store.checkpoint("reconcile:jira", str(self.clock()))
        self.jira.issues["10001"]["fields"]["_epoch"] = time.time() - 30 * 86400
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            policy = root / "policy.json"
            policy.write_text('{"repositories": []}')
            config = root / "service.json"
            config.write_text(json.dumps({"core": {"policy_path": str(policy)}}))
            query = SimpleNamespace(source_freshness=lambda: [{"status": "OK"}])
            with patch.object(entry, "_service", return_value=(self.service, None)), \
                    patch.object(self.analyzer, "query", return_value=query, create=True), \
                    patch.object(sys, "path", list(sys.path)), \
                    patch.object(sys, "argv", ["preflight", str(root), str(config), "digest", "backup"]):
                self.assertEqual(preflight.main(), 0)
        resource = self.service.store.resource("jira:10001")
        self.assertIsNotNone(resource)
        self.assertEqual(self.service.store.jobs("jira:10001")[-1]["state"], "QUEUED")
        self.assertEqual(self.analyzer.requests, [])
        self.assertEqual(self.jira_comments(), [])


class JiraCoreWithoutPRTest(unittest.TestCase):
    def test_existing_issue_is_analyzed_by_real_core_without_a_pr(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = SmokeBench(Path(tmp))
            try:
                bench.github.prs.clear()
                bench.jira.issues["10012"]["fields"]["_epoch"] = time.time() - 30 * 86400
                self.assertEqual(bench.service.reconcile()["enqueued"], 1)
                bench.drain()
                jobs = bench.service.store.jobs("jira:10012")
                self.assertEqual(len(jobs), 1)
                result = jobs[0]["result"]
                self.assertEqual(result["trigger_kind"], "jira")
                self.assertEqual(result["reason_code"], "preliminary_impact_found")
                self.assertIn("reporting", [a["service"]["service"] for a in result["affected"]])
                self.assertIn("jira_without_diff", [u["code"] for u in result["unknowns"]])
                self.assertEqual(bench.service.store.resources("github"), [])
            finally:
                bench.close()


if __name__ == "__main__":
    unittest.main()
