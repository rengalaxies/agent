"""Reconciliation recovers missed deliveries without a person."""

import unittest

from tests.service.helpers import HEAD1, HEAD2, REPO, ServiceCase, orders_result


class ReconcileTest(ServiceCase):
    def test_missed_pr_delivery_is_found_by_reconciliation(self):
        self.assertEqual(self.service.reconcile()["enqueued"], 2)  # open PR and recently updated issue
        self.drain()
        self.assertEqual(len(self.pr_comments()), 1)
        self.assertEqual(len(self.jira_comments()), 1)

    def test_reconciliation_of_unchanged_resources_does_nothing(self):
        self.service.reconcile()
        self.drain()
        before = len(self.analyzer.requests)
        self.assertEqual(self.service.reconcile()["enqueued"], 0)
        self.drain()
        self.assertEqual(len(self.analyzer.requests), before)

    def test_missed_push_is_reanalyzed_and_old_result_marked_stale(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.github.set_head(REPO, 7, HEAD2)  # synchronize delivery lost
        self.service.reconcile()
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn(HEAD2[:12], comment["body"])
        self.assertEqual(self.pr_requests(), 2)

    def test_pull_request_closed_without_delivery_is_closed_by_reconciliation(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.github.prs[(REPO, 7)]["state"] = "closed"
        self.service.reconcile()
        self.drain()
        self.assertTrue(self.service.store.resource("github:acme/orders#7")["closed"])

    def test_new_analysis_basis_updates_the_existing_comment_of_an_unchanged_pr(self):
        # Upgrade to a new extractor profile: neither the PR nor its head changes,
        # the profile-4 result must not stay published indefinitely.
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [before] = self.pr_comments()
        self.analyzer.analysis_basis = lambda: "http-requests-5"
        self.analyzer.result = lambda request: {**orders_result(request), "profile": "http-requests-5"}
        self.service.reconcile()
        self.drain()
        [after] = self.pr_comments()
        self.assertEqual(after["id"], before["id"])
        self.assertIn("http-requests-5", after["body"])
        self.assertNotIn("http-requests-4", after["body"])
        self.assertEqual(self.pr_requests(), 2)
        entries = [(h["entry"], h["detail"].get("reason"))
                   for h in self.service.store.history("github:acme/orders#7")]
        self.assertIn(("generation_opened", "analysis_basis_changed"), entries)

    def test_same_analysis_basis_is_reanalysed_only_once(self):
        self.analyzer.analysis_basis = lambda: "http-requests-5"
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.service.reconcile()  # no recorded basis yet: an upgraded installation re-analyses once
        self.drain()
        before = len(self.analyzer.requests)
        self.service.reconcile()
        self.drain()
        self.assertEqual(len(self.analyzer.requests), before)

    def test_new_basis_keeps_a_queued_new_version_and_its_stale_notice(self):
        # Review finding: revoking here dropped the pending "result is stale" notice.
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        store, rid = self.service.store, "github:acme/orders#7"
        store.apply_snapshot(resource_id=rid, provider="github", kind="pr", version="v-new", snapshot={},
                             event_id="push-not-yet-analysed", stale_notice=lambda g: ("stale", "d" * 64, "m"))
        self.assertEqual(store.reopen_open_resources(reason="analysis_basis_changed", event_id="basis",
                                                     providers={"github", "jira"}), 0)
        self.assertEqual([j["state"] for j in store.jobs(rid)][-1], "QUEUED")
        self.assertIn(("stale", "PENDING"), [(i["kind"], i["state"]) for i in store.intents(rid)])

    def test_resource_of_a_removed_provider_is_not_reopened(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.assertEqual(self.service.store.reopen_open_resources(reason="analysis_basis_changed",
                                                                  event_id="basis", providers={"jira"}), 0)

    def test_closed_pull_request_is_not_reanalysed_on_a_new_basis(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.github.prs[(REPO, 7)]["state"] = "closed"
        self.service.reconcile()
        self.drain()
        before = self.pr_requests()
        self.analyzer.analysis_basis = lambda: "http-requests-5"
        self.service.reconcile()
        self.drain()
        self.assertEqual(self.pr_requests(), before)

    def test_failed_reconciliation_is_a_notice_and_does_not_move_the_checkpoint(self):
        self.github.revoked = True
        self.service.reconcile()
        notices = {n["kind"]: n for n in self.service.store.notices()}
        self.assertIn("reconcile_failed", notices)
        self.assertIsNone(self.service.store.checkpoint("reconcile:github"))
        self.assertIsNotNone(self.service.store.checkpoint("reconcile:jira"))


if __name__ == "__main__":
    unittest.main()
