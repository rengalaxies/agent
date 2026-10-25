"""Delivery: authenticity, duplicates, reordering, untrusted URLs and the own-comment loop."""

import threading
import unittest

from agent_service.connectors.base import WebhookRejected, verify_hmac_sha256

from tests.service.helpers import HEAD1, HEAD2, REPO, ServiceCase
from agent_service.stands import GitHubStand


class SignatureTest(unittest.TestCase):
    def test_verifier_matches_the_documented_test_vector(self):
        # Test vector from the Jira Cloud webhook documentation (checked 2026-10-24).
        verify_hmac_sha256(b"It's a Secret to Everybody", b"Hello World!",
                           "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9")
        with self.assertRaises(WebhookRejected) as rejected:
            verify_hmac_sha256(b"It's a Secret to Everybody", b"Hello World!!",
                               "sha256=a4771c39fbe90f317c7824e83ddef3caae9cb3d976c214ace1f2937e133263c9")
        self.assertEqual((rejected.exception.status, rejected.exception.code), (401, "signature_invalid"))

    def test_sha1_signature_is_not_accepted(self):
        with self.assertRaises(WebhookRejected) as rejected:
            verify_hmac_sha256(b"s", b"{}", "sha1=0000")
        self.assertEqual(rejected.exception.code, "signature_method_unsupported")


class DeliveryTest(ServiceCase):
    def test_wrong_secret_is_rejected_and_nothing_is_queued(self):
        status, body = self.deliver_github(self.pr_payload(HEAD1), secret=b"other")
        self.assertEqual((status, body["error"]), (401, "signature_invalid"))
        status, body = self.deliver_jira(self.jira_payload(), secret=b"other")
        self.assertEqual(status, 401)
        self.assertEqual(self.service.store.status()["events"], {})

    def test_repeated_and_reordered_deliveries_produce_one_current_result(self):
        self.github.set_head(REPO, 7, HEAD2)
        newer = self.pr_payload(HEAD2)
        self.assertEqual(self.deliver_github(newer, delivery="d2")[0], 202)
        # Redelivery of the same delivery id and a late, older delivery.
        self.assertEqual(self.deliver_github(newer, delivery="d2")[1]["duplicate"], True)
        self.assertEqual(self.deliver_github(self.pr_payload(HEAD1, action="opened"), delivery="d1")[0], 202)
        self.drain()

        jobs = self.service.store.jobs("github:acme/orders#7")
        self.assertEqual([(j["generation"], j["state"]) for j in jobs], [(1, "DONE")])
        self.assertEqual([r["pr"]["head_sha"] for r, _ in self.analyzer.requests], [HEAD2])
        [comment] = self.pr_comments()
        self.assertIn(HEAD2[:12], comment["body"])
        self.assertEqual(self.service.store.status()["events"], {"INGESTED": 1, "COALESCED": 1})

    def test_payload_urls_are_never_fetched(self):
        evil = GitHubStand()
        self.addCleanup(evil.close)
        payload = self.pr_payload(HEAD1, action="opened")
        payload["pull_request"].update(url=evil.url + "/repos/acme/orders/pulls/7", diff_url=evil.url + "/x.diff",
                                       comments_url=evil.url + "/c")
        payload["repository"]["url"] = evil.url
        self.deliver_github(payload)
        jira = self.jira_payload("jira:issue_created", "issue_created")
        jira["issue"]["self"] = evil.url + "/rest/api/3/issue/10001"
        self.deliver_jira(jira)
        self.drain()
        self.assertEqual(evil.log, [])
        self.assertEqual(len(self.pr_comments()), 1)
        self.assertEqual(len(self.jira_comments()), 1)

    def test_unconfigured_repository_is_ignored_without_any_fetch(self):
        payload = self.pr_payload(HEAD1, action="opened")
        payload["repository"]["full_name"] = "acme/secret"
        status, body = self.deliver_github(payload)
        self.assertEqual((status, body["state"]), (202, "IGNORED"))
        self.drain()
        self.assertEqual(self.github.log, [])


class OwnCommentLoopTest(ServiceCase):
    def test_jira_events_caused_by_our_comment_do_not_start_analysis_again(self):
        sent = []

        def echo(issue_id, comment):
            # What Jira Cloud sends after a comment: comment_created and an issue update.
            sent.append(self.deliver_jira({"webhookEvent": "comment_created", "comment": comment,
                                           "issue": {"id": issue_id, "key": "ORD-1",
                                                     "fields": {"project": {"key": "ORD"}}}}))
            sent.append(self.deliver_jira(self.jira_payload(type_name="issue_commented")))
            # An update without a changelog passes the receiver filter; the fetched version must stop it.
            sent.append(self.deliver_jira(self.jira_payload(type_name="issue_generic")))

        self.jira.on_comment = echo
        self.deliver_jira(self.jira_payload("jira:issue_created", "issue_created"))
        self.drain()
        _wait(lambda: len(sent) == 3)
        self.drain()
        self.drain()

        self.assertEqual(len(self.analyzer.requests), 1)
        self.assertEqual(len(self.jira_comments()), 1)
        self.assertEqual(self.jira.count("PUT", r".*/comment/\d+"), 0)
        self.assertEqual(self.service.store.status()["events"], {"INGESTED": 1, "IGNORED": 2, "COALESCED": 1})

    def test_semantic_jira_change_does_open_a_new_generation(self):
        self.deliver_jira(self.jira_payload("jira:issue_created", "issue_created"))
        self.drain()
        self.jira.set_summary(10001, "Уменьшить размер страницы Orders до 10")
        self.deliver_jira(self.jira_payload(changelog=[{"field": "summary", "fieldId": "summary"}]))
        self.drain()
        self.assertEqual(len(self.analyzer.requests), 2)
        self.assertEqual(len(self.jira_comments()), 1)  # updated, not a second comment
        self.assertEqual(self.jira.count("PUT", r".*/comment/\d+"), 2)  # stale notice, then the new result

    def test_github_comment_events_are_ignored(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [comment] = self.pr_comments()
        status, body = self.deliver_github({"action": "created", "issue": {"number": 7},
                                            "comment": {"id": comment["id"], "body": comment["body"]},
                                            "repository": {"full_name": REPO}}, event="issue_comment")
        self.assertEqual(body["state"], "IGNORED")
        self.drain()
        self.assertEqual(len(self.analyzer.requests), 1)


def _wait(predicate, seconds=10.0):
    done = threading.Event()
    for _ in range(int(seconds / 0.05)):
        if predicate():
            return
        done.wait(0.05)
    raise AssertionError("condition not reached")


if __name__ == "__main__":
    unittest.main()

