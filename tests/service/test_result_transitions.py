"""A comment that is updated says what disappeared since the last published result."""

import unittest

from tests.service.helpers import HEAD1, HEAD2, REPO, ServiceCase, orders_result


def without_change(request):
    # The PR was repaired: the analyzer finds no supported behaviour change at the new head.
    return {**orders_result(request), "status": "ABSTAINED", "reason_code": "no_supported_delta",
            "summary": "No supported behavior change was found.", "affected": [], "impact_paths": [],
            "checks": [], "claims": [], "deltas": [], "relationships": []}


class ResultTransitionTest(ServiceCase):
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

    def test_abstention_explains_itself_instead_of_empty_sections(self):
        self.analyzer.result = without_change
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        [comment] = self.pr_comments()
        self.assertNotIn("нет данных", comment["body"].partition("**Неизвестные")[0])
        self.assertIn("Потребители не названы (no_supported_delta). Это не доказывает отсутствие влияния.",
                      comment["body"])
        self.assertNotIn("Что изменилось с прошлого вывода", comment["body"])


if __name__ == "__main__":
    unittest.main()
