import json
from pathlib import Path
import sys
import tempfile
import unittest

from agent_graph.contracts import Policy, digest
from agent_graph.engine import Graph
from agent_graph.output_contracts import display_verdict, dump_document, parse_document
from agent_graph.results import change_result, failed_result, preliminary_result
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/orders_reporting"))
from stand import OWNERSHIP, build_stand  # noqa: E402

META = dict(code_version="test", constitution_version="agent-service-v1.0:test", correlation_id="corr-1",
            started_at="2026-10-24T12:00:00Z", finished_at="2026-10-24T12:00:01Z")


def comparable(result):
    value = dump_document(result)
    value.pop("timings")
    for item in value["evidence"] + value["relationships"]:
        item["freshness"].pop("checked_at")
    for item in value["source_freshness"]:
        item["freshness"].pop("checked_at")
    for item in value["affected"]:
        item["owner"].pop("checked_at", None)
    return digest(value)


class ResultCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.stand = build_stand(Path(cls.tmp.name) / "stand")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.work.name) / "state")
        self.graph = Graph(Policy.model_validate(self.stand.policy()), self.store)

    def tearDown(self):
        self.store.close()
        self.work.cleanup()

    def request(self, trigger="pr", branch="pr-7", head=None):
        head = head or self.stand.head("orders", branch)
        pins = self.stand.revisions() | {"orders": head}
        value = dict(schema="agent-graph-output", schema_version="2.0", kind="analysis_request",
                     installation_id="acme", environment="prod", request_id="req-" + branch, trigger_kind=trigger,
                     source_event=dict(event_id="delivery-1", resource_version=head), repository_revisions=pins,
                     graph_version="graph-1", constitution_version="agent-service-v1.0:test",
                     model_configuration_id=None, deadline="2026-10-24T12:05:00Z",
                     access_scope=dict(view_id=self.graph.view, repositories=sorted(pins)))
        if trigger == "pr":
            value["pr"] = dict(provider="github", repository="orders", pr_id=7, base_sha=self.stand.head(),
                               head_sha=head)
        else:
            value["jira"] = dict(project="ORD", key="ORD-12", revision="1", updated_at="2026-10-24T12:00:00Z",
                                 text_fields=dict(summary="Reduce the default Orders page size from 100 to 20"))
        return parse_document(value)

    def pr(self, branch, **extra):
        request = self.request(branch=branch)
        base = self.graph.prepare_context(revisions=self.stand.revisions())
        analysis = self.graph.analyze_change(base["id"], revisions=dict(request.repository_revisions))
        return change_result(self.graph, request, analysis, **META, **extra)


class ResultTests(ResultCase):
    def test_pr_result_names_the_consumer_risk_with_pinned_evidence(self):
        result = self.pr("pr-7", ownership=OWNERSHIP)
        self.assertEqual((result.status, result.reason_code), ("USEFUL", "impact_found_within_profile"))
        self.assertTrue(display_verdict(dump_document(result))["green"])
        findings = {f.consumer.service: f.code for f in result.findings}
        self.assertEqual(findings, {"reporting": "POSSIBLE_TRUNCATION", "archive": "RECHECK_REQUIRED"})
        roles = {(s.repository, s.role): s.commit for s in result.snapshots}
        self.assertEqual(roles[("orders", "base")], self.stand.head())
        self.assertEqual(roles[("orders", "head")], self.stand.head("orders", "pr-7"))
        self.assertEqual(roles[("reporting", "consumer")], self.stand.head("reporting"))
        self.assertTrue(all(e.snapshot == "GIT_COMMIT" and e.commit for e in result.evidence))
        owners = {a.service.service: (a.owner.status, [t.team for t in a.owner.teams]) for a in result.affected}
        self.assertEqual(owners["reporting"], ("KNOWN", ["team-reporting"]))
        risk = next(c for c in result.claims if c.statement.startswith("POSSIBLE_TRUNCATION"))
        self.assertEqual(risk.kind, "hypothesis")
        self.assertNotIn("requirement_unknown", risk.unknowns, "reporting-complete is an approved requirement")
        self.assertEqual(json.loads(json.dumps(dump_document(result))), dump_document(parse_document(
            dump_document(result))))

    def test_unknown_owner_is_shown_not_guessed(self):
        result = self.pr("pr-7", ownership=dict(source="installation_mapping", version="1",
                                                services=dict(reporting=["team-a", "team-b"])))
        owners = {a.service.service: a.owner.status for a in result.affected}
        self.assertEqual(owners, {"reporting": "CONFLICT", "archive": "UNKNOWN"})
        self.assertIn(("owner_unknown", "archive"), {(u.code, u.subject) for u in result.unknowns})

    def test_unclassified_change_is_partial_not_green(self):
        result = self.pr("unclassified")
        self.assertEqual((result.status, result.reason_code), ("PARTIAL", "unclassified_change"))
        self.assertEqual([d.code for d in result.deltas], ["UNCLASSIFIED_OPERATION_CHANGE"])
        self.assertFalse(display_verdict(dump_document(result))["green"])

    def test_readme_only_change_abstains(self):
        result = self.pr("readme-only")
        self.assertEqual((result.status, result.reason_code), ("ABSTAINED", "no_supported_delta"))

    def test_unavailable_pr_commit_fails_instead_of_using_another_commit(self):
        request = self.request(head="e" * 40)
        base = self.graph.prepare_context(revisions=self.stand.revisions())
        analysis = self.graph.analyze_change(base["id"], revisions=dict(request.repository_revisions))
        result = change_result(self.graph, request, analysis, **META)
        self.assertEqual((result.status, result.reason_code, result.claims), ("FAILED", "commit_unavailable", []))

    def test_same_commit_map_gives_the_same_result_facts(self):
        self.assertEqual(comparable(self.pr("pr-7")), comparable(self.pr("pr-7")))


class JiraTests(ResultCase):
    def test_jira_before_diff_finds_consumers_without_claiming_a_break(self):
        request = self.request(trigger="jira", branch="main")
        context = self.graph.prepare_context("ORD-12", revisions=dict(request.repository_revisions))
        orders = [o["id"] for o in context["graph"]["operations"] if o["service"] == "orders"]
        result = preliminary_result(self.graph, request, context, orders, ownership=OWNERSHIP, **META)
        self.assertEqual((result.status, result.reason_code), ("USEFUL", "preliminary_impact_found"))
        self.assertEqual(result.deltas, [])
        self.assertEqual({a.service.service for a in result.affected}, {"reporting", "archive"})
        self.assertIn("jira_without_diff", {u.code for u in result.unknowns})
        self.assertTrue(all("jira_without_diff" in c.unknowns for c in result.claims if c.kind == "hypothesis"))
        archive = next(c.text for c in result.checks if c.consumer.service == "archive")
        self.assertIn("not known", archive)

    def test_unknown_operation_abstains_as_unclear_intent(self):
        request = self.request(trigger="jira", branch="main")
        context = self.graph.prepare_context("ORD-12", revisions=dict(request.repository_revisions))
        result = preliminary_result(self.graph, request, context, [], **META)
        self.assertEqual((result.status, result.reason_code), ("ABSTAINED", "intent_unclear"))

    def test_superseded_result_has_no_claims(self):
        result = failed_result(self.request(), "newer_head", superseded_by="req-2", code_version="t",
                               constitution_version="c", correlation_id="x")
        self.assertEqual((result.status, result.claims), ("SUPERSEDED", []))


if __name__ == "__main__":
    unittest.main()
