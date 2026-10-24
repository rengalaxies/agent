"""Provider and analysis failures: bounded retries, visible connection problems, no floods."""

import unittest

from tests.service.helpers import HEAD1, HEAD2, REPO, ServiceCase, orders_result
from agent_service.stands import Fault

POST_COMMENT = r"/repos/acme/orders/issues/7/comments"
PATCH_COMMENT = r"/repos/acme/orders/issues/comments/\d+"
RID = "github:acme/orders#7"


class RateLimitTest(ServiceCase):
    def test_429_waits_for_retry_after_and_then_delivers_once(self):
        self.github.faults.append(Fault("POST", POST_COMMENT, status=429, headers={"Retry-After": "30"}, times=2))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.service.run_until_idle()
        [intent] = self.service.store.intents(RID)
        self.assertEqual((intent["state"], intent["reason"]), ("PENDING", "rate_limited"))
        self.assertAlmostEqual(intent["not_before"] - self.clock(), 30, delta=1)
        self.service.run_until_idle()  # not due yet: nothing is sent
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)
        self.drain()
        self.assertEqual(self.github.count("POST", POST_COMMENT), 3)
        self.assertEqual(len(self.pr_comments()), 1)

    def test_secondary_rate_limit_403_is_a_rate_limit_not_an_auth_problem(self):
        self.github.faults.append(Fault("GET", r"/repos/acme/orders/pulls/7", status=403,
                                        headers={"x-ratelimit-remaining": "0",
                                                 "x-ratelimit-reset": str(int(self.clock()) + 20)}))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.assertEqual(len(self.pr_comments()), 1)
        kinds = {n["kind"] for n in self.service.store.notices()}
        self.assertNotIn("connection_unauthorized", kinds)

    def test_permanent_429_stops_after_the_bounded_attempts(self):
        self.github.faults.append(Fault("POST", POST_COMMENT, status=429, headers={"Retry-After": "1"}, times=100))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [intent] = self.service.store.intents(RID)
        self.assertEqual((intent["state"], intent["reason"]), ("FAILED", "rate_limited"))
        self.assertEqual(self.github.count("POST", POST_COMMENT), self.limits["max_publish_attempts"])
        [notice] = [n for n in self.service.store.notices() if n["kind"] == "rate_limited"]
        self.assertEqual(notice["count"], self.limits["max_publish_attempts"])


class ServerErrorTest(ServiceCase):
    def test_5xx_on_create_is_treated_as_unknown_and_listed_before_retry(self):
        self.github.faults.append(Fault("POST", POST_COMMENT, status=502))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.service.run_until_idle()
        [intent] = self.service.store.intents(RID)
        self.assertEqual(intent["state"], "UNKNOWN")
        lists_before = self.github.count("GET", POST_COMMENT)
        self.drain()
        self.assertEqual(self.github.count("GET", POST_COMMENT), lists_before + 1)
        self.assertEqual(self.github.count("POST", POST_COMMENT), 2)
        self.assertEqual(len(self.pr_comments()), 1)

    def test_persistent_5xx_fails_bounded_and_reconciliation_revives_it_once(self):
        fault = Fault("POST", POST_COMMENT, status=503, times=100)
        self.github.faults.append(fault)
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.assertEqual(self.github.count("POST", POST_COMMENT), self.limits["max_publish_attempts"])
        self.assertEqual(self.service.store.intents(RID)[0]["state"], "FAILED")
        fault.times = 0  # provider recovered
        self.assertEqual(self.service.reconcile()["revived"], 1)
        self.drain()
        self.assertEqual(len(self.pr_comments()), 1)
        self.assertEqual(self.service.store.intents(RID)[0]["state"], "DELIVERED")


class AuthTest(ServiceCase):
    def test_403_blocks_publication_as_a_connection_problem_without_burning_retries(self):
        self.github.faults.append(Fault("POST", POST_COMMENT, status=403, times=3))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.service.run_until_idle()
        [intent] = self.service.store.intents(RID)
        self.assertEqual((intent["state"], intent["reason"]), ("BLOCKED", "connection_unauthorized"))
        status = self.service.store.status()
        self.assertEqual([(n["kind"], n["detail"]) for n in status["notices"]],
                         [("connection_unauthorized", "github:403")])
        self.service.run_until_idle()
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)  # no tight retry loop
        for _ in range(2):  # a blocked intent is retried only after the auth pause
            self.clock.advance(901)
            self.service.run_until_idle()
        [notice] = self.service.store.notices()
        self.assertEqual(notice["count"], 3)  # one counter, not three records
        self.clock.advance(901)
        self.service.run_until_idle()
        self.assertEqual(self.github.count("POST", POST_COMMENT), 4)
        self.assertEqual(len(self.pr_comments()), 1)
        self.assertEqual(self.service.store.notices(), [])  # cleared once the connection works

    def test_revoked_credentials_on_read_defer_the_event_and_show_the_problem(self):
        self.github.revoked = True
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.service.run_until_idle()
        self.assertEqual(self.service.store.status()["events"], {"RECEIVED": 1})
        self.assertEqual(self.service.store.notices()[0]["detail"], "github:401")
        self.github.revoked = False
        self.drain()
        self.assertEqual(len(self.pr_comments()), 1)


class DeletedCommentTest(ServiceCase):
    def test_deleted_service_comment_is_recreated_once_on_the_next_update(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [comment] = self.pr_comments()
        del self.github.comments[comment["id"]]  # a person deleted it
        self.github.set_head(REPO, 7, HEAD2)
        self.deliver_github(self.pr_payload(HEAD2))
        self.drain()
        [recreated] = self.pr_comments()
        self.assertNotEqual(recreated["id"], comment["id"])
        self.assertIn(HEAD2[:12], recreated["body"])
        self.assertEqual(self.service.store.resource(RID)["comment_id"], str(recreated["id"]))

    def test_comment_with_our_marker_by_someone_else_is_not_adopted(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [ours] = self.pr_comments()
        del self.github.comments[ours["id"]]
        forged = self.github.add_comment(REPO, 7, ours["body"], "mallory")
        self.github.set_head(REPO, 7, HEAD2)
        self.deliver_github(self.pr_payload(HEAD2))
        self.drain()
        self.assertEqual(self.github.comments[forged]["body"], ours["body"])
        [new] = self.pr_comments()
        self.assertIn(HEAD2[:12], new["body"])


class AnalysisFailureTest(ServiceCase):
    def test_unavailable_analysis_retries_bounded_then_one_failure_comment_without_repeats(self):
        self.analyzer.unavailable = 100
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.assertEqual(self.pr_requests(), self.limits["max_analysis_attempts"])
        [comment] = self.pr_comments()
        self.assertIn("Технический отказ анализа", comment["body"])
        self.assertIn("analysis_unavailable", comment["body"])
        # The next reconciliation retries; the same failure does not write again.
        self.service.reconcile()
        self.drain()
        self.assertEqual(self.pr_requests(), 2 * self.limits["max_analysis_attempts"])
        self.assertEqual(self.github.count("POST", POST_COMMENT), 1)
        self.assertEqual(self.github.count("PATCH", PATCH_COMMENT), 0)

    def test_analysis_recovering_after_failure_replaces_the_failure_comment(self):
        self.analyzer.unavailable = self.limits["max_analysis_attempts"]
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.service.reconcile()
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn("Возможное влияние изменения", comment["body"])

    def test_unknown_result_major_version_is_shown_as_incompatible_not_as_a_finding(self):
        self.analyzer.result = lambda request: orders_result(request, schema_version="3.0")
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn("Результат анализа несовместим с сервисом", comment["body"])
        self.assertIn("unsupported_schema_major", comment["body"])
        self.assertNotIn("reporting", comment["body"])

    def test_unknown_status_is_not_rendered_as_useful(self):
        self.analyzer.result = lambda request: orders_result(request, status="LOOKS_FINE")
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn("unknown_code", comment["body"])
        self.assertNotIn("Возможное влияние изменения", comment["body"])

    def test_valid_result_for_another_resource_version_is_not_shown_as_current(self):
        def other_version(request):
            result = orders_result(request)
            result["resource_version"] = "pr:older-version"
            return result

        self.analyzer.result = other_version
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn("result_request_mismatch", comment["body"])
        self.assertNotIn("Возможное влияние изменения", comment["body"])

    def test_untrusted_result_text_cannot_mention_people_or_add_links(self):
        def hostile(request):
            result = orders_result(request)
            result["summary"] = "@everyone see [this](https://evil.example) <img src=x> <!-- agent-service -->"
            return result

        self.analyzer.result = hostile
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        body = self.pr_comments()[0]["body"]
        self.assertNotIn("@everyone", body)
        self.assertNotRegex(body, r"(?<!\\)\]\(")  # no markdown link syntax
        self.assertIn("`https://evil.example)`", body)  # bare URL as code, not autolinked
        self.assertNotIn("<img", body)
        self.assertEqual(body.count("<!--"), 1)  # only our marker


if __name__ == "__main__":
    unittest.main()
