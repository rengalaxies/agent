"""Reconciliation recovers missed deliveries without a person."""

import unittest

from tests.service.helpers import HEAD1, HEAD2, REPO, ServiceCase


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

    def test_failed_reconciliation_is_a_notice_and_does_not_move_the_checkpoint(self):
        self.github.revoked = True
        self.service.reconcile()
        notices = {n["kind"]: n for n in self.service.store.notices()}
        self.assertIn("reconcile_failed", notices)
        self.assertIsNone(self.service.store.checkpoint("reconcile:github"))
        self.assertIsNotNone(self.service.store.checkpoint("reconcile:jira"))


if __name__ == "__main__":
    unittest.main()
