"""End-to-end: signed delivery over HTTP → queue → analysis → one comment on the stand."""

import re
import unittest

from tests.service.helpers import BASE, CONSUMER_SHA, HEAD1, ServiceCase


class JiraThenPullRequestTest(ServiceCase):
    def test_jira_event_gives_preliminary_comment_and_pr_refines_it_with_its_shas(self):
        status, _ = self.deliver_jira(self.jira_payload("jira:issue_created", "issue_created"))
        self.assertEqual(status, 202)
        self.drain()

        [jira_comment] = self.jira_comments()
        text = _adf_text(jira_comment["body"])
        self.assertIn("предварительный вывод", text)
        self.assertIn("reporting: команда team-reporting", text)
        self.assertIn("requirement_unknown (reporting)", text)
        request, _ = self.analyzer.requests[0]
        self.assertEqual(request["trigger_kind"], "jira")
        self.assertEqual(request["jira"]["key"], "ORD-1")
        self.assertEqual(request["jira"]["updated_at"], "2026-10-24T10:00:00.000+00:00")
        self.assertIsNone(request["pr"])
        # Before any diff the analysis reads the pinned default branches of every repository.
        self.assertEqual(request["repository_revisions"], {"orders": BASE, "reporting": CONSUMER_SHA})

        status, _ = self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.assertEqual(status, 202)
        self.drain()

        [pr_comment] = self.pr_comments()
        body = pr_comment["body"]
        self.assertIn(f"base {BASE[:12]}, head {HEAD1[:12]}", body)
        self.assertIn("ORD-1", body)
        request, attachments = self.analyzer.requests[1]
        self.assertEqual((request["pr"]["base_sha"], request["pr"]["head_sha"]), (BASE, HEAD1))
        self.assertEqual(request["repository_revisions"], {"orders": HEAD1, "reporting": CONSUMER_SHA})
        self.assertEqual(attachments["linked_jira_keys"], ["ORD-1"])
        self.assertEqual(attachments["changed_paths"], ["orders/api.py"])
        self.assertIn(b"+PAGE_SIZE = 20", attachments["diff"])
        self.assertIn("Факт в пределах профиля: Reporting вызывает GET /orders без page_size.", body)
        self.assertIn(f"код reporting@{CONSUMER_SHA[:12]}:reporting/export.py#L12-14", body)
        self.assertIn("наблюдаемые вызовы access-log: reporting -> orders", body)
        # Sections in the contract order.
        titles = re.findall(r"^\*\*(.+)\*\*$", body, flags=re.M)
        self.assertEqual(titles, ["Что может затронуть", "Почему и через какой путь", "Что проверить",
                                  "Неизвестные и свежесть", "Версии"])

    def test_sources_stay_read_only_except_the_service_comment(self):
        self.deliver_jira(self.jira_payload("jira:issue_created", "issue_created"))
        self.deliver_github(self.pr_payload(HEAD1, action="opened"))
        self.drain()
        writes = [(m, p) for stand in (self.github, self.jira) for m, p in stand.log if m != "GET"]
        self.assertTrue(writes)
        for method, path in writes:
            self.assertRegex(path, r"^/repos/acme/orders/issues/7/comments$|^/rest/api/3/issue/10001/comment$",
                             f"unexpected write {method} {path}")


def _adf_text(node):
    from agent_service.connectors.jira import adf_text

    return adf_text(node)


if __name__ == "__main__":
    unittest.main()
