"""M2 defects: reproduce against the pre-M2 implementation, using local HTTP only."""
import json
import unittest
from unittest.mock import patch

from agent_service.http import ClientError, Response
from agent_service.stands import Fault
from tests.service.helpers import BASE, HEAD1, HEAD2, REPO, ServiceCase

RID = "github:acme/orders#7"


def response(value):
    return Response(200, {}, json.dumps(value).encode())


class M2RegressionTest(ServiceCase):
    def test_wrong_app_installation_is_rejected_before_enqueue(self):
        connector = self.service.connectors["github"]
        connector.installation_id = 99
        for installation in ({"id": 100}, None):
            payload = self.pr_payload(HEAD1)
            if installation:
                payload["installation"] = installation
            status, _ = self.deliver_github(payload)
            self.assertEqual(status, 403)
        self.assertEqual(self.service.store.status()["events"], {})
        self.assertEqual(self.github.log, [])

    def test_correct_installation_and_setup_ping_are_accepted(self):
        self.service.connectors["github"].installation_id = 99
        payload = self.pr_payload(HEAD1, extra={"installation": {"id": 99}})
        self.assertEqual(self.deliver_github(payload)[0], 202)
        self.assertEqual(self.deliver_github({"zen": "test"}, event="ping")[1]["state"], "IGNORED")
        self.drain()
        self.assertEqual(len(self.pr_comments()), 1)

    def test_malformed_signed_payload_returns_400(self):
        for provider, deliver, field in (("github", self.deliver_github, "repository"),
                                         ("jira", self.deliver_jira, "issue")):
            for payload in ([], {field: ["malformed"]}):
                with self.subTest(provider=provider, payload=payload):
                    self.assertEqual(deliver(payload)[0], 400)

    def test_new_base_without_new_head_replaces_result(self):
        self.deliver_github(self.pr_payload(HEAD1))
        self.drain()
        self.github.prs[(REPO, 7)]["base"]["sha"] = "d" * 40
        self.service.reconcile()
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn("base " + "d" * 12, comment["body"])
        self.assertEqual(self.pr_requests(), 2)
        self.assertEqual(self.github.count("POST", r".*/issues/7/comments"), 1)

    def test_base_moves_between_analysis_and_publication(self):
        def move(request):
            self.github.prs[(REPO, 7)]["base"]["sha"] = "d" * 40
        self.analyzer.during = move
        self.deliver_github(self.pr_payload(HEAD1))
        self.drain()
        self.assertFalse(any("base " + BASE[:12] in text for text in self.github.written))
        self.assertIn("base " + "d" * 12, self.pr_comments()[0]["body"])

    def test_failed_postsend_read_is_visible_and_durably_rechecked(self):
        def race(phase, intent):
            if phase == "after_send" and intent["generation"] == 1:
                self.github.set_head(REPO, 7, HEAD2)
                self.github.faults.append(Fault("GET", r".*/pulls/7", status=503))
        self.service = self.make_service(race)
        self.deliver_github(self.pr_payload(HEAD1))
        self.assertEqual(self.service.step(), "ingest:new_generation")
        self.assertEqual(self.service.step(), "analyze:done")
        self.service.step()
        self.assertIn("postsend_check_failed", {n["kind"] for n in self.service.store.notices()})
        self.assertEqual(self.service.store.status()["events"].get("RECEIVED"), 1)
        self.restart()
        self.drain()
        self.assertIn(HEAD2[:12], self.pr_comments()[0]["body"])
        self.assertEqual(self.github.count("POST", r".*/issues/7/comments"), 1)
        self.assertNotIn("postsend_check_failed", {n["kind"] for n in self.service.store.notices()})

    def test_noop_adoption_still_checks_for_a_racing_head(self):
        # A lost response is reconciled by finding the already-written digest.
        self.github.faults.append(Fault("POST", r".*/issues/7/comments", drop="after"))
        self.deliver_github(self.pr_payload(HEAD1))
        self.service.run_until_idle()
        def move(phase, intent):
            if phase == "before_send" and intent["generation"] == 1:
                self.github.set_head(REPO, 7, HEAD2)
        self.service.hook = self.service.publisher.hook = move
        self.drain()
        self.assertIn(HEAD2[:12], self.pr_comments()[0]["body"])
        self.assertEqual(self.github.count("POST", r".*/issues/7/comments"), 1)

    def test_truncated_github_scan_does_not_close_unseen_pr_or_advance_cursor(self):
        self.deliver_github(self.pr_payload(HEAD1))
        self.drain()
        connector = self.service.connectors["github"]
        other = dict(self.github.prs[(REPO, 7)], number=8)
        with patch.object(connector, "_call", return_value=response([other] * 50)):
            self.service.reconcile()
        self.assertIsNone(self.service.store.checkpoint("reconcile:github"))
        self.drain()
        self.assertFalse(self.service.store.resource(RID)["closed"])
        self.assertIn("reconcile_failed", {n["kind"] for n in self.service.store.notices()})

    def test_comment_scan_limit_does_not_allow_a_duplicate_create(self):
        connector = self.service.connectors["github"]
        with patch.object(connector, "_call", return_value=response([
                {"id": i, "body": "human", "user": {"login": "human"}} for i in range(100)])):
            with self.assertRaises(ClientError):
                connector.list_comments(RID)

    def test_jira_scan_limit_does_not_advance_checkpoint(self):
        connector = self.service.connectors["jira"]
        with patch.object(connector, "_call", return_value=response(
                {"issues": [], "nextPageToken": "more", "isLast": False})):
            self.service.reconcile()
        self.assertIsNone(self.service.store.checkpoint("reconcile:jira"))

    def test_jira_comment_scan_limit_fails_closed(self):
        connector = self.service.connectors["jira"]
        with patch.object(connector, "_call", return_value=response({"comments": [
                {"id": i, "body": "human", "author": {"accountId": "human"}} for i in range(100)],
                "total": 1001})):
            with self.assertRaises(ClientError):
                connector.list_comments("jira:10001")

    def test_jira_downtime_over_seven_days_is_not_clamped(self):
        connector = self.service.connectors["jira"]
        with patch.object(connector, "_call", return_value=response({"issues": [], "isLast": True})) as call:
            connector.reconcile_candidates(self.clock() - 14 * 86400)
        self.assertIn("updated >= -20170m", call.call_args.kwargs["query"]["jql"])

    def test_known_jira_issue_deleted_without_delivery_is_reconciled(self):
        self.service.reconcile()
        self.drain()
        del self.jira.issues["10001"]
        self.service.reconcile()
        self.drain()
        self.assertTrue(self.service.store.resource("jira:10001")["closed"])

    def test_reconciliation_recovers_force_push_back_to_a_previous_head(self):
        self.service.reconcile(); self.drain()
        self.github.set_head(REPO, 7, HEAD2)
        self.service.reconcile(); self.drain()
        self.github.set_head(REPO, 7, HEAD1)
        self.service.reconcile(); self.drain()
        self.assertIn(HEAD1[:12], self.pr_comments()[0]["body"])
        self.assertEqual(self.pr_requests(), 3)

    def test_jira_change_beyond_the_display_limit_invalidates_the_result(self):
        fields = self.jira.issues["10001"]["fields"]
        fields["description"] = "x" * 20001 + "before"
        self.deliver_jira(self.jira_payload("jira:issue_created")); self.drain()
        fields["description"] = "x" * 20001 + "after"
        self.deliver_jira(self.jira_payload()); self.drain()
        self.assertEqual(len(self.service.store.jobs("jira:10001")), 2)

    def test_revoked_auth_during_prepare_pauses_instead_of_spinning(self):
        self.github.faults.append(Fault("GET", r".*/compare/.*", status=401, times=100))
        self.deliver_github(self.pr_payload(HEAD1))
        self.service.step()
        self.assertEqual(self.service.step(), "analyze:blocked")
        [job] = self.service.store.jobs(RID)
        self.assertGreaterEqual(job["not_before"] - self.clock(), 900)
        self.assertIsNone(self.service.step())
        self.github.faults.clear()
        self.clock.advance(901)
        self.drain()
        self.assertIn(HEAD1[:12], self.pr_comments()[0]["body"])

    def test_permanent_prepare_error_is_not_retried(self):
        self.github.faults.append(Fault("GET", r".*/compare/.*", status=422, times=100))
        self.deliver_github(self.pr_payload(HEAD1))
        self.drain()
        self.assertEqual(self.github.count("GET", r".*/compare/.*"), 1)
        self.assertIn("provider_rejected", self.pr_comments()[0]["body"])

    def test_permanent_ingest_error_is_not_retried(self):
        self.github.faults.append(Fault("GET", r".*/pulls/7", status=422, times=100))
        self.deliver_github(self.pr_payload(HEAD1))
        self.drain()
        self.assertEqual(self.github.count("GET", r".*/pulls/7"), 1)
        self.assertEqual(self.service.store.status()["events"], {"FAILED": 1})
        self.assertIn("provider_rejected", {n["kind"] for n in self.service.store.notices()})


class JiraLinkParsingTest(unittest.TestCase):
    def test_only_complete_allowlisted_keys_are_links_and_multiple_keys_stay_explicit(self):
        from agent_service.connectors.github import jira_keys

        self.assertEqual(jira_keys(["ORD-12suffix prefix_ORD-13 ORD-14_foo OTHER-1"], ["ORD"]), [])
        self.assertEqual(jira_keys(["ORD-12 / ORD-13", "feature/ORD-12-fix"], ["ORD"]),
                         ["ORD-12", "ORD-13"])


if __name__ == "__main__":
    unittest.main()
