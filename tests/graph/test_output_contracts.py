import copy
import json
from pathlib import Path
import unittest

from agent_graph.contracts import digest
from agent_graph.output_contracts import (
    SCHEMA_VERSION, AnalysisResult, ContractError, display_verdict, dump_document, entity_id,
    json_schema, normalize_route, parse_document)

ROOT = Path(__file__).resolve().parents[2]
BASE = "1" * 40
HEAD = "2" * 40
REPORTING = "3" * 40
NOW = "2026-10-24T12:00:00Z"
SECRET = "sk-control-7f3a9c"


def service(name):
    return dict(kind="service", installation_id="acme", environment="prod", service=name)


def operation():
    return dict(kind="operation", installation_id="acme", environment="prod", service="orders",
                method="GET", route="/orders")


def fresh(status="CURRENT", reasons=()):
    return dict(status=status, checked_at=NOW, reasons=list(reasons))


def code_evidence(id, repository, commit, path, line):
    return dict(id=id, origin="code", provenance="AUTHENTIC", sufficiency="SUPPORTED_WITHIN_PROFILE",
                freshness=fresh(), visibility=[repository], snapshot="GIT_COMMIT", repository=repository,
                commit=commit, blob="4" * 40, content_sha256="5" * 64, path=path,
                start_line=line, end_line=line + 2)


def request(**changes):
    value = dict(schema="agent-graph-output", schema_version=SCHEMA_VERSION, kind="analysis_request",
                 installation_id="acme", environment="prod", request_id="req-1", trigger_kind="pr",
                 source_event=dict(event_id="delivery-9", resource_version=HEAD),
                 pr=dict(provider="github", repository="orders", pr_id=7, base_sha=BASE, head_sha=HEAD),
                 repository_revisions=dict(orders=HEAD, reporting=REPORTING),
                 graph_version="graph-12", constitution_version="agent-service-v1",
                 model_configuration_id=None, deadline="2026-10-24T12:05:00Z",
                 access_scope=dict(view_id="6" * 64, repositories=["orders", "reporting"]))
    value.update(changes)
    return value


def result(**changes):
    """Orders/Reporting PR: default page size 100 -> 20, Reporting reads one page."""
    calls = dict(id="rel-calls", kind="calls", source=service("reporting"), target=operation(),
                 status="ACTIVE", origins=["code"], evidence_refs=["ev-call"], freshness=fresh(),
                 change_origin="code_scan", visibility=["reporting", "orders"])
    value = dict(
        schema="agent-graph-output", schema_version=SCHEMA_VERSION, kind="analysis_result",
        profile="http-requests-4", code_version="agent 0.3.1.dev4+" + HEAD[:12],
        constitution_version="agent-service-v1", installation_id="acme", environment="prod",
        request_id="req-1", event_id="delivery-9", resource_version=HEAD, correlation_id="corr-1",
        trigger_kind="pr",
        snapshots=[dict(repository="orders", mode="GIT_COMMIT", commit=BASE, tree="7" * 40, role="base"),
                   dict(repository="orders", mode="GIT_COMMIT", commit=HEAD, tree="8" * 40, role="head"),
                   dict(repository="reporting", mode="GIT_COMMIT", commit=REPORTING, tree="9" * 40,
                        role="consumer")],
        graph_version="graph-12", status="USEFUL", reason_code="impact_found_within_profile",
        summary="Reporting reads one page of GET /orders; the default page size drops from 100 to 20.",
        affected=[dict(service=service("reporting"), relationship_refs=["rel-calls"],
                       owner=dict(status="UNKNOWN", teams=[], source=None))],
        impact_paths=[dict(relationship_refs=["rel-calls"], summary="reporting -> orders GET /orders")],
        checks=[dict(consumer=service("reporting"), claim_refs=["claim-1"],
                     text="Run the export with more than 20 orders and compare with the full set.")],
        claims=[dict(id="claim-1", kind="fact", statement="Reporting calls GET /orders without page_size.",
                     evidence_refs=["ev-call", "ev-decl"], applicability="pinned commits only",
                     uncertainty="LOW", unknowns=["requirement_unknown"])],
        deltas=[dict(operation=operation(), code="PAGE_DEFAULT_CHANGED", before=100, after=20,
                     evidence_refs=["ev-decl"])],
        findings=[dict(code="POSSIBLE_TRUNCATION", consumer=service("reporting"),
                       usage="SINGLE_REQUEST_OBSERVED", dependency_freshness="CURRENT",
                       callsite=dict(kind="callsite", installation_id="acme", environment="prod",
                                     service="reporting", repository="reporting", path="client.py", line=6),
                       evidence_refs=["ev-call"])],
        unknowns=[dict(code="requirement_unknown", subject="reporting")],
        source_freshness=[dict(source_kind="git", source_id="orders", freshness=fresh())],
        evidence=[code_evidence("ev-call", "reporting", REPORTING, "client.py", 5),
                  code_evidence("ev-decl", "orders", HEAD, "api.py", 6)],
        relationships=[calls], model=None,
        costs=dict(model_calls=0, prompt_tokens=None, completion_tokens=None, reserved_micro=None, currency=None),
        timings=dict(started_at=NOW, finished_at=NOW, seconds=dict(analysis=0.4)))
    value.update(changes)
    return value


class VersionTests(unittest.TestCase):
    def test_valid_request_and_result_round_trip(self):
        for document in (request(), result()):
            parsed = parse_document(document)
            self.assertEqual(dump_document(parsed), parse_document(dump_document(parsed)).model_dump(
                mode="json", by_alias=True))
        self.assertEqual(display_verdict(result()), dict(
            display="USEFUL", green=True, reason_code="impact_found_within_profile", errors=[]))

    def test_unknown_major_is_incompatible_and_not_green(self):
        for version, code in (("3.0", "unsupported_schema_major"), ("1.4", "unsupported_schema_major"),
                              ("2.9", "newer_schema_minor"), ("2", "invalid_schema_version"),
                              (2.0, "invalid_schema_version")):
            with self.subTest(version=version):
                with self.assertRaises(ContractError) as caught:
                    parse_document(result(schema_version=version))
                self.assertEqual(caught.exception.code, code)
                verdict = display_verdict(result(schema_version=version))
                self.assertEqual((verdict["display"], verdict["green"]), ("INCOMPATIBLE", False))

    def test_foreign_schema_is_rejected(self):
        with self.assertRaises(ContractError) as caught:
            parse_document({**result(), "schema": "agent-graph-1"})
        self.assertEqual(caught.exception.code, "unknown_schema")


class CodeTests(unittest.TestCase):
    def assert_unknown(self, document, path):
        with self.assertRaises(ContractError) as caught:
            parse_document(document)
        self.assertEqual(caught.exception.code, "unknown_code")
        self.assertIn(path, [e["path"] for e in caught.exception.errors])
        self.assertFalse(display_verdict(document)["green"])

    def test_unknown_delta_finding_usage_gap_and_status_codes_are_rejected(self):
        doc = result()
        doc["deltas"][0]["code"] = "PAGE_DEFAULT_GREW"
        self.assert_unknown(doc, "deltas.0.code")
        doc = result()
        doc["findings"][0]["code"] = "SAFE"
        self.assert_unknown(doc, "findings.0.code")
        doc = result()
        doc["findings"][0]["usage"] = "STREAMING"
        self.assert_unknown(doc, "findings.0.usage")
        self.assert_unknown(result(status="PARTIAL", gaps=[dict(code="new_gap")]), "gaps.0.code")
        self.assert_unknown(result(status="GREEN"), "status")

    def test_reason_must_belong_to_status(self):
        with self.assertRaises(ContractError) as caught:
            parse_document(result(reason_code="invalid_model_action"))
        self.assertEqual(caught.exception.errors[0]["rule"], "reason_not_allowed_for_status")

    def test_partial_must_show_what_is_missing(self):
        doc = result(status="PARTIAL", reason_code="coverage_gaps", unknowns=[])
        with self.assertRaises(ContractError):
            parse_document(doc)
        doc["gaps"] = [dict(code="dynamic_parameters", repository="reporting", path="client.py")]
        self.assertEqual(display_verdict(doc)["display"], "PARTIAL")
        self.assertFalse(display_verdict(doc)["green"])

    def test_failed_and_superseded_carry_no_claims(self):
        for status, reason, extra in (("FAILED", "commit_unavailable", {}),
                                      ("SUPERSEDED", "newer_head", {"superseded_by": "req-2"})):
            with self.assertRaises(ContractError):
                parse_document(result(status=status, reason_code=reason, **extra))
            parse_document(result(status=status, reason_code=reason, claims=[], checks=[], **extra))
        with self.assertRaises(ContractError):
            parse_document(result(status="SUPERSEDED", reason_code="newer_head", claims=[], checks=[]))


class EvidenceTests(unittest.TestCase):
    def rule(self, document):
        with self.assertRaises(ContractError) as caught:
            parse_document(document)
        return [e.get("rule") for e in caught.exception.errors]

    def test_fact_needs_authentic_sufficient_non_model_evidence(self):
        doc = result()
        hypothesis = dict(id="ev-model", origin="model_hypothesis", provenance="AUTHENTIC",
                          sufficiency="INSUFFICIENT", freshness=fresh(), visibility=["reporting"],
                          model_configuration_id="qwen-x", supporting_refs=["ev-call"],
                          unknowns=["model_hypothesis_unverified"])
        doc["evidence"].append(hypothesis)
        doc["claims"][0]["evidence_refs"] = ["ev-model"]
        self.assertIn("fact_without_sufficient_evidence", self.rule(doc))
        doc["claims"][0]["kind"] = "hypothesis"
        doc["claims"][0]["uncertainty"] = "HIGH"
        self.assertEqual(display_verdict(doc)["display"], "USEFUL")

    def test_model_hypothesis_cannot_declare_itself_sufficient(self):
        doc = result()
        doc["evidence"].append(dict(id="ev-model", origin="model_hypothesis", provenance="AUTHENTIC",
                                    sufficiency="SUPPORTED_WITHIN_PROFILE", freshness=fresh(),
                                    visibility=["reporting"], model_configuration_id="qwen-x",
                                    supporting_refs=[], unknowns=["model_hypothesis_unverified"]))
        self.assertIn("hypothesis_cannot_be_sufficient", self.rule(doc))

    def test_references_must_exist_and_rejected_evidence_cannot_back_claims(self):
        doc = result()
        doc["claims"][0]["evidence_refs"] = ["ev-invented"]
        self.assertIn("unknown_evidence_ref", self.rule(doc))
        doc = result()
        doc["evidence"][0]["provenance"] = "REJECTED"
        self.assertIn("claim_cites_rejected_evidence", self.rule(doc))
        doc = result()
        doc["affected"][0]["relationship_refs"] = ["rel-other"]
        self.assertIn("unknown_relationship_ref", self.rule(doc))

    def test_snapshot_identity_and_worktree_marking(self):
        doc = result()
        doc["evidence"][0]["commit"] = None
        self.assertIn("snapshot_identity_mismatch", self.rule(doc))
        doc = result()
        doc["evidence"][0].update(snapshot="WORKTREE", commit=None, blob=None)
        self.assertIn("worktree_must_be_marked", self.rule(doc))
        doc["evidence"][0]["freshness"]["reasons"] = ["worktree_not_reproducible"]
        parse_document(doc)

    def test_owner_status_matches_teams(self):
        team = dict(kind="team", installation_id="acme", team="reporting-team")
        for owner in (dict(status="UNKNOWN", teams=[team], source="codeowners"),
                      dict(status="KNOWN", teams=[team, {**team, "team": "data"}], source="codeowners"),
                      dict(status="KNOWN", teams=[team], source=None)):
            doc = result()
            doc["affected"][0]["owner"] = owner
            self.assertIn("owner_status_mismatch", self.rule(doc))

    def test_jira_result_has_no_diff(self):
        doc = result(trigger_kind="jira", status="USEFUL", reason_code="preliminary_impact_found")
        self.assertIn("jira_result_has_no_diff", self.rule(doc))
        doc.update(deltas=[], findings=[])
        parse_document(doc)


class RequestTests(unittest.TestCase):
    def rule(self, document):
        with self.assertRaises(ContractError) as caught:
            parse_document(document)
        return [e.get("rule") for e in caught.exception.errors]

    def test_pr_head_must_be_pinned_and_in_scope(self):
        self.assertIn("pr_head_not_pinned", self.rule(request(repository_revisions=dict(orders=BASE))))
        self.assertIn("repository_outside_scope", self.rule(request(
            repository_revisions=dict(orders=HEAD, billing=REPORTING))))
        self.assertIn("invalid_document", [self._code(request(repository_revisions=dict(orders="main")))])

    def test_trigger_kind_matches_payload(self):
        jira = dict(project="ORD", key="ORD-12", revision="3", updated_at=NOW,
                    text_fields=dict(summary="Reduce the default Orders page size from 100 to 20"))
        parse_document(request(trigger_kind="jira", pr=None, jira=jira, repository_revisions=dict(orders=HEAD)))
        self.assertIn("jira_trigger_mismatch", self.rule(request(trigger_kind="jira")))
        self.assertIn("replay_requires_origin", self.rule(request(trigger_kind="replay")))

    def test_diagnostics_never_echo_input(self):
        jira = dict(project="ORD", key="ORD-12", revision="3", updated_at=NOW,
                    text_fields={SECRET: SECRET, "summary": 5})
        document = request(trigger_kind="jira", pr=None, jira=jira, repository_revisions={SECRET: HEAD},
                           installation_id=SECRET + "!")
        with self.assertRaises(ContractError) as caught:
            parse_document(document)
        report = json.dumps([caught.exception.code, caught.exception.errors, str(caught.exception)])
        self.assertNotIn(SECRET, report)
        self.assertIn("jira.text_fields.*", report)

    def _code(self, document):
        try:
            parse_document(document)
        except ContractError as exc:
            return exc.code
        return None


class IdentityTests(unittest.TestCase):
    def test_operation_identity_matches_core_formula_and_separates_services(self):
        op = operation()
        self.assertEqual(entity_id(op), digest(["acme", "prod", "orders", "GET", "/orders"]))
        self.assertNotEqual(entity_id(op), entity_id({**op, "service": "billing"}))
        self.assertNotEqual(entity_id(op), entity_id({**op, "environment": "stage"}))

    def test_route_normalization(self):
        self.assertEqual(normalize_route("//orders//items/"), "/orders/items")
        self.assertEqual(normalize_route("/"), "/")
        for bad in ("orders", "/orders?x=1", "/orders#a"):
            with self.assertRaises(ValueError):
                normalize_route(bad)
        doc = result()
        doc["deltas"][0]["operation"]["route"] = "/orders/"
        with self.assertRaises(ContractError):
            parse_document(doc)


class SchemaFileTests(unittest.TestCase):
    def test_committed_json_schema_matches_models(self):
        def shape(node):
            # Titles and descriptions differ between pydantic releases; structure must not.
            if isinstance(node, dict):
                return {k: shape(v) for k, v in node.items() if k not in ("title", "description")}
            return [shape(v) for v in node] if isinstance(node, list) else node
        committed = json.loads((ROOT / "schemas/agent-graph-output-2.json").read_text(encoding="utf-8"))
        self.assertEqual(shape(committed), shape(json_schema()),
                         "regenerate: python -m agent_graph.output_contracts > schemas/agent-graph-output-2.json")

    def test_parse_does_not_mutate_input(self):
        doc = result()
        before = copy.deepcopy(doc)
        self.assertIsInstance(parse_document(doc), AnalysisResult)
        self.assertEqual(doc, before)


if __name__ == "__main__":
    unittest.main()


class SharedExampleTests(unittest.TestCase):
    """Orders/Reporting stand documents other batches build against (tests/graph/fixtures/output-2)."""

    def test_shared_examples_parse_and_keep_their_status(self):
        folder = ROOT / "tests/graph/fixtures/output-2"
        expected = {"pr-7-result.json": ("USEFUL", "impact_found_within_profile"),
                    "ord-12-result.json": ("USEFUL", "preliminary_impact_found")}
        for name in ("pr-7-request.json", "ord-12-request.json", *expected):
            with self.subTest(name=name):
                parsed = parse_document(json.loads((folder / name).read_text(encoding="utf-8")))
                if name in expected:
                    self.assertEqual((parsed.status, parsed.reason_code), expected[name])
