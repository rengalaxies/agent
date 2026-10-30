"""A comment that is updated says what disappeared since the last published result."""

from types import SimpleNamespace
import unittest

from agent_service.publisher import since_previous
from tests.service.helpers import HEAD1, HEAD2, REPO, ServiceCase, orders_result


def without_change(request):
    # The PR was repaired: the analyzer finds no supported behaviour change at the new head.
    return {**orders_result(request), "status": "ABSTAINED", "reason_code": "no_supported_delta",
            "summary": "No supported behavior change was found.", "affected": [], "impact_paths": [],
            "checks": [], "claims": [], "deltas": [], "relationships": []}


class ResultTransitionTest(ServiceCase):
    def test_incompatible_schema_was_not_a_previously_displayed_risk(self):
        self.analyzer.result = lambda request: orders_result(request, schema_version='99.0')
        self.deliver_github(self.pr_payload(HEAD1, action='opened'))
        self.drain()
        self.assertIn('несовместим', self.pr_comments()[0]['body'])
        self.analyzer.result = without_change
        self.github.set_head(REPO, 7, HEAD2)
        self.deliver_github(self.pr_payload(HEAD2))
        self.drain()
        self.assertNotIn('Что изменилось с прошлого вывода', self.pr_comments()[0]['body'])

    def test_foreign_request_was_not_a_previously_displayed_risk(self):
        self.analyzer.result = lambda request: {**orders_result(request), 'request_id': 'foreign-request'}
        self.deliver_github(self.pr_payload(HEAD1, action='opened'))
        self.drain()
        self.assertIn('result_request_mismatch', self.pr_comments()[0]['body'])
        self.analyzer.result = without_change
        self.github.set_head(REPO, 7, HEAD2)
        self.deliver_github(self.pr_payload(HEAD2))
        self.drain()
        self.assertNotIn('Что изменилось с прошлого вывода', self.pr_comments()[0]['body'])

    def test_fix_in_the_same_pr_names_the_risk_that_is_no_longer_found(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [before] = self.pr_comments()
        self.analyzer.result = without_change
        self.github.set_head(REPO, 7, HEAD2)
        self.deliver_github(self.pr_payload(HEAD2))
        self.drain()
        [after] = self.pr_comments()
        self.assertEqual(after["id"], before["id"])
        section = after["body"].partition("**Что изменилось с прошлого вывода**")[2].partition("**")[0]
        self.assertIn("Поколение 1: изменение orders GET /orders: PAGE_DEFAULT_CHANGED 100 -> 20. "
                      "В текущей версии не обнаружено.", section)
        self.assertIn("тесты не запускались", section)

    def test_risk_that_persists_after_a_push_adds_no_transition(self):
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.github.set_head(REPO, 7, HEAD2)
        self.deliver_github(self.pr_payload(HEAD2))
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn(HEAD2[:12], comment["body"])
        self.assertNotIn("Что изменилось с прошлого вывода", comment["body"])

    def test_failed_analysis_does_not_claim_the_earlier_risk_is_gone(self):
        # Review finding: a FAILED result has no deltas, which is not "not found".
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        self.analyzer.result = lambda request: {**without_change(request), "status": "FAILED",
                                                "reason_code": "source_unavailable"}
        self.github.set_head(REPO, 7, HEAD2)
        self.deliver_github(self.pr_payload(HEAD2))
        self.drain()
        [comment] = self.pr_comments()
        self.assertIn(HEAD2[:12], comment["body"])
        self.assertNotIn("Что изменилось с прошлого вывода", comment["body"])
        self.assertNotIn("не обнаружено", comment["body"])

    def test_abstention_explains_itself_instead_of_empty_sections(self):
        self.analyzer.result = without_change
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [comment] = self.pr_comments()
        self.assertNotIn("нет данных", comment["body"].partition("**Неизвестные")[0])
        self.assertIn("Потребители не названы (no_supported_delta). Это не доказывает отсутствие влияния.",
                      comment["body"])
        self.assertNotIn("Что изменилось с прошлого вывода", comment["body"])


class SincePreviousTest(unittest.TestCase):
    VIEW = SimpleNamespace(compatible=True, status="ABSTAINED", reason_code="no_supported_delta")
    DELTA = {"operation": {"service": "orders", "method": "GET", "route": "/orders"},
             "code": "PAGE_DEFAULT_CHANGED", "before": 100, "after": 20}

    def test_same_resource_version_is_a_new_analyzer_not_a_fix(self):
        # A re-analysis after a profile change keeps the version; a missing finding is not a repair.
        self.assertEqual(since_previous((1, "v1", {"deltas": [self.DELTA]}), {"deltas": []}, self.VIEW, "v1"), [])
        self.assertTrue(since_previous((1, "v1", {"deltas": [self.DELTA]}), {"deltas": []}, self.VIEW, "v2"))

    def test_malformed_stored_result_is_skipped_not_raised(self):
        # Older releases stored their own shapes; a crash here would stop the worker.
        stored = {"deltas": {"operation": "orders"}, "findings": [{"consumer": "reporting", "code": "X"}, "junk"]}
        self.assertEqual(since_previous((1, "v1", stored), {"deltas": "junk"}, self.VIEW, "v2"), [])


if __name__ == "__main__":
    unittest.main()
