"""Runtime bases next to code in the persistent graph, conflicts, and the bounded query tool."""
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json

from pydantic import ValidationError

from agent_graph.contracts import GraphError
from agent_graph.engine import Graph
from agent_graph.graph_query import GraphQuery, dispatch
from agent_graph.output_contracts import SCHEMA_VERSION, ContractError, parse_document
from agent_graph.runtime_observations import AccessLogSource, read_access_logs
from tests.graph.test_graph_store import ROOT, StandCase

IDENTITIES = [dict(alias=name, service=name) for name in ("orders", "reporting", "archive", "billing", "audit")]


class RuntimeGraphCase(StandCase):
    def setUp(self):
        super().setUp()
        self.store, self.gs = self.open()
        self.graph = Graph(self.policy(), self.store)
        self.gs.sync_code(self.context(self.graph))
        self.logs = self.root / "logs"
        self.logs.mkdir()
        # Per test: windows are relative to the moment the code was synced.
        self.now = datetime.now(timezone.utc).replace(microsecond=0)

    def segment(self, name, records, start=-10, end=0):
        lines = [json.dumps(dict(ts=(self.now + timedelta(minutes=start, seconds=i + 1)).isoformat(), service="orders",
                                 env="prod", method="GET", status=200, **r)) for i, r in enumerate(records)]
        data = ("\n".join(lines) + "\n").encode()
        (self.logs / f"{name}.jsonl").write_bytes(data)
        (self.logs / f"{name}.coverage.json").write_text(json.dumps(dict(
            schema="access-log-segment-1", file=f"{name}.jsonl", emitter="orders", environment="prod",
            start=(self.now + timedelta(minutes=start)).isoformat(), end=(self.now + timedelta(minutes=end)).isoformat(),
            sample_rate=1.0, sha256=hashlib.sha256(data).hexdigest())))

    def sync_runtime(self, root=None, start=-10, end=0):
        source = AccessLogSource(id="access", installation_id="acme", environment="prod", root=str(root or self.logs),
                                 identities=IDENTITIES, instrumented_services=["orders"])
        return self.gs.sync_runtime(read_access_logs(source, self.now + timedelta(minutes=start),
                                                     self.now + timedelta(minutes=end)))

    def query(self, **kwargs):
        return GraphQuery.for_policy(self.gs, self.policy(), runtime_sources=["access"], **kwargs)


class RuntimeNextToCodeTests(RuntimeGraphCase):
    def test_zero_traffic_keeps_the_code_dependency_and_a_routeless_edge_stays_service_level(self):
        self.segment("w1", [dict(client="reporting", route="/orders"), dict(client="audit")])
        self.sync_runtime()
        query = self.query()
        archive = query.relationship(self.rel(query, "archive", "orders"))
        self.assertEqual((archive["status"], archive["origins"]), ("ACTIVE", ["code"]))
        reporting = query.relationship(self.rel(query, "reporting", "orders"))
        self.assertEqual(reporting["origins"], ["code", "runtime"])
        audit = next(r for r in query._rels.values() if query._entities[r["source"]]["service"] == "audit"
                     and query._entities[r["target"]] == dict(kind="service", installation_id="acme",
                                                              environment="prod", service="orders"))
        self.assertIsNone(query.relationship(audit["id"])["bases"][0]["route"])
        orders_op = next(h["id"] for h in query.find("orders GET /orders", "operation"))
        impact = query.impact(orders_op)
        service_level = [p for p in impact["paths"] if p["service_level"]]
        self.assertEqual([p["consumer"] for p in service_level], ["audit"])
        self.assertIn(dict(code="runtime_route_not_recorded", subject=audit["id"]), impact["unknowns"])

    def test_same_path_of_another_service_is_a_separate_operation(self):
        query = self.query()
        operations = {h["entity"]["service"]: h["id"] for h in query.find("GET /orders", "operation")}
        self.assertEqual(set(operations), {"orders", "billing"})
        self.assertEqual({p["consumer"] for p in query.impact(operations["orders"])["paths"]}, {"reporting", "archive"})
        self.assertEqual({p["consumer"] for p in query.impact(operations["billing"])["paths"]}, {"audit"})

    def test_runtime_on_another_route_of_the_pair_is_a_visible_conflict(self):
        self.segment("w1", [dict(client="reporting", route="/orders/v2")])
        self.sync_runtime()
        query = self.query()
        view = query.relationship(self.rel(query, "reporting", "orders"))
        self.assertEqual(view["status"], "CONFLICT")
        self.assertEqual([c["code"] for c in view["conflicts"]], ["route_conflict"])
        self.assertEqual(view["contract"]["status"], "CONFLICT")

    def test_traffic_after_code_removal_is_a_conflict_not_a_silent_choice(self):
        self.gs.sync_code(self.context(self.graph, orders="removed"))
        self.segment("w1", [dict(client="reporting", route="/orders")], start=-1, end=1)
        self.sync_runtime(start=-1, end=1)
        query = self.query(now=self.now + timedelta(minutes=2))
        view = query.relationship(self.rel(query, "reporting", "orders"))
        self.assertEqual([c["code"] for c in view["conflicts"]], ["runtime_after_removal"])
        self.assertEqual(view["status"], "CONFLICT")

    def test_unavailable_or_old_runtime_changes_freshness_only(self):
        self.segment("w1", [dict(client="reporting", route="/orders")])
        self.sync_runtime()
        self.sync_runtime(root=self.root / "gone")
        query = self.query()
        view = query.relationship(self.rel(query, "reporting", "orders"))
        runtime = next(b for b in view["bases"] if b["origin"] == "runtime")
        code = next(b for b in view["bases"] if b["origin"] == "code")
        self.assertEqual(runtime["freshness"]["reasons"], ["source_unavailable"])
        self.assertEqual(code["freshness"]["status"], "CURRENT")
        self.assertEqual(view["status"], "ACTIVE")
        later = self.query(now=self.now + timedelta(days=2))
        old = next(b for b in later.relationship(view["id"])["bases"] if b["origin"] == "runtime")
        self.assertIn("age_exceeded", old["freshness"]["reasons"])
        (source,) = [s for s in query.source_freshness() if s["source_kind"] == "runtime"]
        self.assertEqual(source["freshness"]["status"], "STALE")

    def test_runtime_source_without_grant_is_invisible(self):
        self.segment("w1", [dict(client="reporting", route="/orders")])
        self.sync_runtime()
        query = GraphQuery.for_policy(self.gs, self.policy())
        self.assertEqual(query.relationship(self.rel(query, "reporting", "orders"))["origins"], ["code"])
        self.assertEqual([s for s in query.source_freshness() if s["source_kind"] == "runtime"], [])


class QueryToolTests(RuntimeGraphCase):
    def test_tool_calls_are_validated_and_bounded(self):
        query = self.query()
        found = dispatch(query, dict(tool="graph_find", text="orders", kind="operation", limit=5))
        self.assertTrue(all(h["entity"]["kind"] == "operation" for h in found))
        for bad in (dict(tool="graph_sql", text="x"), dict(tool="graph_find", text="x", limit=1000),
                    dict(tool="graph_impact", entity_id="not-a-digest"), dict(tool="graph_find", text="x", extra=1)):
            with self.assertRaises(ValidationError):
                dispatch(query, bad)
        with self.assertRaises(GraphError) as raised:
            dispatch(query, dict(tool="graph_neighbors"))
        self.assertEqual(raised.exception.code, "invalid_query")
        with self.assertRaises(GraphError):
            dispatch(query, dict(tool="graph_impact", entity_id="0" * 64))
        owner = dispatch(query, dict(tool="graph_owner", service="audit"))
        self.assertEqual(owner["owner"]["status"], "UNKNOWN")

    def test_impact_feeds_a_valid_analysis_result(self):
        """The pieces mvp-4 copies into AnalysisResult pass the 2A reader as they are."""
        self.segment("w1", [dict(client="reporting", route="/orders"), dict(client="audit")])
        self.sync_runtime()
        query = self.query()
        orders_op = next(h for h in query.find("orders GET /orders", "operation"))
        impact = query.impact(orders_op["id"])
        rels = [v["contract"] for v in impact["relationships"].values()]
        runtime = next(e for e in impact["evidence"] if e["origin"] == "runtime" and e["route"])
        routeless = next(e for e in impact["evidence"] if e["origin"] == "runtime" and not e["route"])
        document = dict(
            schema="agent-graph-output", schema_version=SCHEMA_VERSION, kind="analysis_result",
            profile="http-requests-4", code_version="test", constitution_version="agent-service-v1",
            installation_id="acme", environment="prod", request_id="req-1", event_id="ORD-12", resource_version="1",
            correlation_id="corr-1", trigger_kind="jira", snapshots=[], graph_version=impact["graph_version"],
            status="PARTIAL", reason_code="owner_unknown", summary="Reporting and Archive read GET /orders.",
            affected=[dict(service=a["service"], owner=a["owner"], relationship_refs=a["relationship_refs"])
                      for a in impact["affected"]],
            impact_paths=[dict(relationship_refs=p["relationship_refs"], summary=p["summary"]) for p in impact["paths"]],
            claims=[dict(id="c1", kind="fact", statement="Reporting calls GET /orders on Orders.",
                         evidence_refs=[runtime["id"]], applicability="observed window", uncertainty="LOW",
                         subject=orders_op["entity"])],
            unknowns=[dict(code="owner_unknown", subject="audit")],
            source_freshness=[{k: s[k] for k in ("source_kind", "source_id", "freshness")} for s in impact["sources"]],
            evidence=impact["evidence"], relationships=rels, model=None,
            costs=dict(model_calls=0, prompt_tokens=None, completion_tokens=None, reserved_micro=None, currency=None),
            timings=dict(started_at=impact["sources"][0]["freshness"]["checked_at"],
                         finished_at=impact["sources"][0]["freshness"]["checked_at"]))
        parsed = parse_document(document)
        self.assertEqual({e.origin for e in parsed.evidence}, {"code", "runtime"})
        # A service edge without a route cannot back a fact about the operation (contract 2.1).
        document["claims"][0]["evidence_refs"] = [routeless["id"]]
        with self.assertRaises(ContractError) as raised:
            parse_document(document)
        self.assertEqual(raised.exception.errors[0]["rule"], "fact_without_operation_evidence")


class HttpStandTests(StandCase):
    def test_real_http_calls_become_a_directed_runtime_edge_next_to_code(self):
        spec = importlib.util.spec_from_file_location("runtime_stand", ROOT / "tools/agent_service/runtime_stand/stand.py")
        runtime_stand = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime_stand)
        store, gs = self.open()
        gs.sync_code(self.context(Graph(self.policy(), store)))
        run = runtime_stand.run_stand(self.root / "http", installation="acme", environment="prod")
        source = AccessLogSource.model_validate(run["source"])
        gs.sync_runtime(read_access_logs(source, run["window"]["start"], run["window"]["end"]))
        query = GraphQuery.for_policy(gs, self.policy(), runtime_sources=[source.id])
        reporting = query.relationship(self.rel(query, "reporting", "orders"))
        self.assertEqual((reporting["status"], reporting["origins"]), ("ACTIVE", ["code", "runtime"]))
        runtime = next(b for b in reporting["bases"] if b["origin"] == "runtime")
        self.assertEqual(runtime["aggregates"]["request_count"], 3)
        # Inventory exists only at runtime; its same-path operation stays its own node.
        health = query.relationship(self.rel(query, "health", "inventory"))
        self.assertEqual(health["origins"], ["runtime"])
        self.assertNotEqual(health["target_id"], reporting["target_id"])


if __name__ == "__main__":
    import unittest
    unittest.main()
