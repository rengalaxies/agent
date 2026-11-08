import unittest

from agent_service.analysis import ResultView
from agent_service.confluence import with_documentation
from agent_service.connectors.jira import adf_text, to_adf
from agent_service.publisher import result_doc


class JiraPresentationTest(unittest.TestCase):
    def doc(self, status="ABSTAINED", reason="no_supported_delta", raw=None, **kwargs):
        from agent_service.jira_presentation import summary_doc

        view = ResultView(
            status, reason, "No supported behavior change was found.", **kwargs
        )
        doc = result_doc(
            view,
            snapshot={"repository": "pilot/orders", "pr_id": 4, "head_sha": "a" * 40},
            kind="pr",
            generation=5,
            gaps=[],
        )
        doc["jira_summary"] = summary_doc(
            view, raw or {}, kind="pr", gaps=[], earlier=[]
        )
        return doc

    def test_abstention_is_russian_and_has_no_empty_sections_or_versions(self):
        doc = self.doc(
            versions={"correlation_id": "private-trace", "code_version": "release-123"}
        )
        text = adf_text(to_adf(doc, "marker"))
        for forbidden in [
            "No supported",
            "no_supported_delta",
            "private-trace",
            "release-123",
            "нет данных",
            "Путь влияния не построен",
            "Версии",
            "Поколение",
        ]:
            self.assertNotIn(forbidden, text)
        self.assertIn("не гарантирует", text)
        self.assertLess(len(text), 1300)
        self.assertIn("Версии", str(doc["sections"]))

    def test_removed_operation_keeps_consumer_callsite_and_test_limit(self):
        raw = {
            "deltas": [
                {
                    "code": "OPERATION_REMOVED",
                    "operation": {
                        "service": "orders",
                        "method": "GET",
                        "route": "/orders/summary",
                    },
                }
            ],
            "findings": [
                {
                    "code": "OPERATION_REMOVED",
                    "consumer": {"service": "reporting"},
                    "callsite": {
                        "repository": "bb.reporting",
                        "path": "client.py",
                        "line": 14,
                    },
                    "test_executed": False,
                }
            ],
        }
        text = adf_text(
            to_adf(
                self.doc(
                    "USEFUL",
                    "impact_found_within_profile",
                    raw=raw,
                    affected=[
                        {
                            "service": "reporting",
                            "owner_status": "UNKNOWN",
                            "teams": [],
                            "owner_source": None,
                        }
                    ],
                ),
                "marker",
            )
        )
        for expected in [
            "reporting",
            "client.py:14",
            "/orders/summary",
            "не запускались",
        ]:
            self.assertIn(expected, text)
        self.assertNotIn("OPERATION_REMOVED", text)

    def test_context_is_a_reference_not_a_full_dump(self):
        doc = self.doc()
        page = {
            "page_id": "123",
            "title": "Требования",
            "version": 4,
            "url": "https://pilot.atlassian.net/wiki/spaces/X/pages/123",
            "text": "FULL_PAGE_TEXT " * 200,
            "truncated": True,
            "unsupported_blocks": 1,
        }
        doc = with_documentation(doc, [page])
        text = adf_text(to_adf(doc, "marker"))
        self.assertIn("версия 4", text)
        self.assertIn(page["url"], text)
        self.assertNotIn("FULL_PAGE_TEXT", text)
        self.assertIn("отдельно не провер", text)
        self.assertIn("не полностью", text)
        self.assertIn("FULL_PAGE_TEXT", str(doc["sections"]))

    def test_missing_page_stays_visible_and_removing_link_clears_summary(self):
        doc = with_documentation(
            self.doc(),
            [
                {
                    "page_id": "123",
                    "url": "https://pilot.atlassian.net/wiki/spaces/X/pages/123",
                    "status": "UNAVAILABLE",
                    "reason": "not_found",
                }
            ],
        )
        self.assertIn("недоступ", adf_text(to_adf(doc, "marker")))
        doc = with_documentation(doc, [])
        self.assertNotIn("https://pilot", adf_text(to_adf(doc, "marker")))

    def test_incompatible_result_does_not_become_safe(self):
        doc = self.doc("FAILED", "result_request_mismatch", compatible=False)
        text = adf_text(to_adf(doc, "marker"))
        self.assertIn("не показан", text)
        self.assertNotIn("предупреждений нет", text)

    def test_stale_source_and_partial_coverage_are_not_hidden(self):
        doc = self.doc(
            "PARTIAL",
            "source_stale",
            freshness=[
                {"source": "git:orders", "status": "STALE", "checked_at": "old"}
            ],
            unknowns=["requirement_unknown (reporting)"],
        )
        text = adf_text(to_adf(doc, "marker"))
        self.assertIn("устар", text)
        self.assertIn("непол", text)
        self.assertNotIn("source_stale", text)

    def test_jira_intent_keeps_a_structured_dependency_path(self):
        raw = {
            "relationships": [
                {
                    "id": "r",
                    "kind": "calls",
                    "source": {"service": "reporting"},
                    "target": {
                        "service": "orders",
                        "method": "GET",
                        "route": "/orders",
                    },
                }
            ],
            "impact_paths": [{"relationship_refs": ["r"]}],
            "evidence": [],
        }
        text = adf_text(
            to_adf(self.doc("USEFUL", "preliminary_impact_found", raw=raw), "marker")
        )
        self.assertIn("reporting → orders GET /orders", text)

    def test_stale_and_failure_notifications_omit_machine_versions(self):
        from agent_service.publisher import failure_doc, stale_doc

        snapshot = {"repository": "pilot/orders", "pr_id": 4, "head_sha": "a" * 40}
        for doc in [
            stale_doc(snapshot=snapshot, kind="pr", generation=5),
            failure_doc(
                reason_code="source_unavailable",
                snapshot=snapshot,
                kind="pr",
                generation=5,
            ),
        ]:
            text = adf_text(to_adf(doc, "marker"))
            self.assertNotIn("Поколение", text)
            self.assertNotIn("source_unavailable", text)


from tests.service.helpers import ServiceCase


class JiraPresentationIntegrationTest(ServiceCase):
    def test_http_publication_is_compact_but_outbox_keeps_full_document(self):
        import json

        self.service.connectors["jira"].comment_format = "summary_ru"
        self.deliver_jira(self.jira_payload())
        self.drain()
        [comment] = self.jira_comments()
        text = adf_text(comment["body"])
        self.assertIn("reporting", text)
        self.assertIn("предварительный", text)
        self.assertNotIn("Версии", text)
        self.assertNotIn("correlation_id", text)
        full = json.loads(self.service.store.intents("jira:10001")[-1]["body"])
        self.assertIn("Версии", str(full["sections"]))
        self.assertIn("correlation_id", str(full["sections"]))
        self.assertIn("jira_summary", full)


class JiraPresentationReviewRegressions(unittest.TestCase):
    def test_service_level_link_does_not_require_method_or_route(self):
        from agent_service.jira_presentation import summary_doc

        raw = {
            "relationships": [
                {
                    "id": "r",
                    "kind": "calls",
                    "source": {"kind": "service", "service": "reporting"},
                    "target": {"kind": "service", "service": "orders"},
                }
            ],
            "impact_paths": [{"relationship_refs": ["r"]}],
        }
        doc = summary_doc(
            ResultView("PARTIAL", "coverage_gaps", ""),
            raw,
            kind="jira",
            gaps=[],
            earlier=[],
        )
        text = str(doc)
        self.assertIn("reporting → orders", text)
        self.assertIn("маршрут", text)

    def test_every_consumer_keeps_specific_requirement_and_callsite(self):
        from agent_service.jira_presentation import summary_doc

        raw = {
            "checks": [
                {
                    "consumer": {"service": name},
                    "text": f"Before the change lands, check how {name} uses GET /orders at client.py:14 against requirement R-{name} (complete_collection).",
                }
                for name in ["reporting", "archive"]
            ]
        }
        text = str(
            summary_doc(
                ResultView("PARTIAL", "coverage_gaps", ""),
                raw,
                kind="jira",
                gaps=[],
                earlier=[],
            )
        )
        for name in ["reporting", "archive"]:
            self.assertIn("R-" + name, text)
        self.assertIn("client.py:14", text)
        self.assertNotIn("Before the change", text)


class JiraPresentationConfigurationTest(unittest.TestCase):
    def test_format_is_explicit_and_reaches_jira_backend(self):
        from agent_service.config import ServiceConfig, build_connectors

        data = {
            "installation_id": "test",
            "environment": "test",
            "state_path": "unused.sqlite",
            "publication": "live",
            "jira": {
                "base_url": "https://pilot.atlassian.net",
                "project_keys": ["KAN"],
                "bot_account_id": "bot",
                "webhook_secret_env": "HOOK",
                "auth": {"kind": "basic", "email_env": "EMAIL", "token_env": "TOKEN"},
            },
        }
        cfg = ServiceConfig.model_validate(data)
        self.assertEqual(cfg.jira.comment_format, "full")
        data["jira"]["comment_format"] = "summary_ru"
        cfg = ServiceConfig.model_validate(data)
        connectors, _ = build_connectors(cfg, env_secret=lambda name: "test-value")
        self.assertEqual(connectors["jira"].comment_format, "summary_ru")

    def test_model_hypothesis_keeps_full_explanation_even_in_summary_mode(self):
        from tests.service.test_model_publication import ModelPublicationTest

        case = ModelPublicationTest(
            "test_jira_publishes_candidate_as_hypothesis_with_source_reference"
        )
        case.setUp()
        try:
            case.bench.service.connectors["jira"].comment_format = "summary_ru"
            case.test_jira_publishes_candidate_as_hypothesis_with_source_reference()
        finally:
            case.doCleanups()


class JiraCheckTranslationTest(unittest.TestCase):
    def test_pagination_guidance_keeps_numeric_bound_in_russian(self):
        from agent_service.jira_presentation import russian_check

        text = russian_check(
            "reporting",
            "Run consumer with more than 20 records; compare full expected set, page traversal and explicit limits",
        )
        self.assertIn("20", text)
        self.assertIn("обход страниц", text)
        self.assertNotIn("Run consumer", text)
