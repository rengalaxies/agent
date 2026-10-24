"""Process death in every phase: no lost job and no blind second create."""

import unittest

from tests.service.helpers import HEAD1, Crash, ServiceCase
from tests.service.stands import Fault

POST_COMMENT = r"/repos/acme/orders/issues/7/comments"


class RestartTest(ServiceCase):
    def crash_at(self, phase):
        def hook(name, item):
            if name == phase:
                raise Crash(phase)
        return hook

    def finish_after_restart(self):
        self.restart()
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn(HEAD1[:12], comment["body"])
        jobs = self.service.store.jobs("github:acme/orders#7")
        self.assertEqual([j["state"] for j in jobs], ["DONE"])
        return comment

    def test_restart_after_receive(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.finish_after_restart()
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)

    def test_restart_after_claim_returns_the_job(self):
        self.service = self.make_service(self.crash_at("claimed"))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        with self.assertRaises(Crash):
            self.drain()
        self.assertEqual(self.service.store.status()["jobs"], {"RUNNING": 1})
        self.finish_after_restart()
        self.assertEqual(len(self.analyzer.requests), 1)

    def test_restart_after_analysis_before_result_is_stored_reanalyzes_once(self):
        self.service = self.make_service(self.crash_at("analyzed"))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        with self.assertRaises(Crash):
            self.drain()
        self.finish_after_restart()
        self.assertEqual(len(self.analyzer.requests), 2)
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)

    def test_restart_with_claimed_intent_before_send(self):
        self.service = self.make_service(self.crash_at("before_send"))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        with self.assertRaises(Crash):
            self.drain()
        self.assertEqual(self.github.written, [])
        self.finish_after_restart()
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)

    def test_restart_after_sending_was_recorded_but_before_the_write(self):
        self.service = self.make_service(self.crash_at("sending"))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        with self.assertRaises(Crash):
            self.drain()
        self.assertEqual(self.service.store.status()["intents"], {"SENDING": 1})
        self.finish_after_restart()
        # Outcome was unknown, so the comments were listed before the single create.
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)
        self.assertGreaterEqual(self.github.count("GET", POST_COMMENT), 2)

    def test_restart_after_the_external_write_does_not_create_again(self):
        self.service = self.make_service(self.crash_at("after_send"))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        with self.assertRaises(Crash):
            self.drain()
        self.assertEqual(len(self.pr_comments()), 1)
        self.finish_after_restart()
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)
        self.assertEqual(self.github.count("PATCH", r"/repos/acme/orders/issues/comments/\d+"), 0)

    def test_lost_response_after_write_is_reconciled_by_marker(self):
        self.github.faults.append(Fault("POST", POST_COMMENT, drop="after"))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.assertEqual(len(self.pr_comments()), 1)
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)
        [intent] = self.service.store.intents("github:acme/orders#7")
        self.assertEqual((intent["state"], intent["receipt"]["wrote"]), ("DELIVERED", False))

    def test_jira_lost_response_after_write_is_reconciled_by_marker(self):
        self.jira.faults.append(Fault("POST", r"/rest/api/3/issue/10001/comment", drop="after"))
        self.deliver_jira(self.jira_payload("jira:issue_created", "issue_created"))
        self.drain()
        self.restart()
        self.drain()
        self.assertEqual(len(self.jira_comments()), 1)
        self.assertEqual(self.jira.count("POST", r"/rest/api/3/issue/10001/comment"), 1)


if __name__ == "__main__":
    unittest.main()
