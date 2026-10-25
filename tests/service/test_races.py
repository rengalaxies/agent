"""A new head while the analysis runs or while the comment is being sent."""

import unittest

from tests.service.helpers import HEAD1, HEAD2, REPO, ServiceCase


class NewHeadTest(ServiceCase):
    def test_new_head_during_analysis_never_publishes_the_old_head(self):
        def push_during_analysis(request):
            if request["pr"]["head_sha"] == HEAD1:
                self.github.set_head(REPO, 7, HEAD2)
                self.assertEqual(self.deliver_github(self.pr_payload(HEAD2))[0], 202)

        self.analyzer.during = push_during_analysis
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()

        self.assertTrue(self.github.written)
        self.assertTrue(all(HEAD1[:12] not in body for body in self.github.written))
        [comment] = self.pr_comments()
        self.assertIn(HEAD2[:12], comment["body"])
        jobs = self.service.store.jobs("github:acme/orders#7")
        self.assertEqual([(j["generation"], j["state"]) for j in jobs], [(1, "SUPERSEDED"), (2, "DONE")])

    def test_new_head_without_webhook_during_analysis_is_caught_by_the_check_before_send(self):
        # The delivery for the new head is lost; only the pre-send fetch can notice.
        self.analyzer.during = lambda request: self.github.set_head(REPO, 7, HEAD2) \
            if request["pr"]["head_sha"] == HEAD1 else None
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.assertTrue(all(HEAD1[:12] not in body for body in self.github.written))
        [comment] = self.pr_comments()
        self.assertIn(HEAD2[:12], comment["body"])
        intents = self.service.store.intents("github:acme/orders#7")
        self.assertEqual((intents[0]["generation"], intents[0]["state"]), (1, "SUPERSEDED"))
        opened = [h["detail"]["event_id"] for h in self.service.store.history("github:acme/orders#7")
                  if h["entry"] == "generation_opened"]
        self.assertEqual(len(opened), 2)
        self.assertTrue(opened[1].startswith("freshness:"))

    def test_new_head_during_send_is_replaced_by_a_stale_notice_and_then_the_new_result(self):
        def push_while_sending(phase, item):
            if phase == "sending" and item["generation"] == 1:
                self.github.set_head(REPO, 7, HEAD2)  # webhook lost as well

        self.service = self.make_service(push_while_sending)
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()

        titles = [body.splitlines()[0] for body in self.github.written]
        self.assertEqual(titles, ["### Возможное влияние изменения", "### Предыдущий вывод устарел",
                                  "### Возможное влияние изменения"])
        self.assertIn(HEAD1[:12], self.github.written[0])
        [comment] = self.pr_comments()
        self.assertIn(HEAD2[:12], comment["body"])
        self.assertEqual(self.github.count("POST", r".*/issues/7/comments"), 1)

    def test_closed_pull_request_revokes_pending_publication(self):
        def close_during_analysis(request):
            self.github.prs[(REPO, 7)]["state"] = "closed"

        self.analyzer.during = close_during_analysis
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.assertEqual(self.github.written, [])
        self.assertTrue(self.service.store.resource("github:acme/orders#7")["closed"])


if __name__ == "__main__":
    unittest.main()
