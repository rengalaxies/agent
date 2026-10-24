from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from agent_graph.contracts import GraphError
from agent_graph.discovery import operation_id as code_operation_id
from agent_graph.runtime_observations import (
    AccessLogSource, FreshnessPolicy, assess, read_access_logs, relationships)

T0 = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
T1 = T0 + timedelta(minutes=10)
IDENTITIES = [dict(alias="orders-7f9c", service="orders"), dict(alias="inventory-2b1d", service="inventory"),
              dict(alias="reporting-5d8b", service="reporting"), dict(alias="health", service="health"),
              dict(alias="export", service="export")]


def at(minutes):
    return (T0 + timedelta(minutes=minutes)).isoformat()


def request(minute, client="reporting-5d8b", emitter="orders-7f9c", **fields):
    record = dict(ts=at(minute), service=emitter, env="prod", client=client, method="GET",
                  route="/orders", path="/orders?day=1", status=200, duration_ms=4.0)
    record.update(fields)
    return {k: v for k, v in record.items() if v is not None}


class RuntimeObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.logs = Path(self.tmp.name) / "logs"
        self.logs.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def segment(self, name, emitter, records, start=0, end=10, sample_rate=1.0, raw_lines=()):
        lines = [json.dumps(r) for r in records] + list(raw_lines)
        data = ("\n".join(lines) + "\n").encode()
        (self.logs / f"{name}.jsonl").write_bytes(data)
        (self.logs / f"{name}.coverage.json").write_text(json.dumps(dict(
            schema="access-log-segment-1", file=f"{name}.jsonl", emitter=emitter, environment="prod",
            start=at(start), end=at(end), sample_rate=sample_rate, sha256=hashlib.sha256(data).hexdigest())))

    def read(self, root=None, checked_at=None, **policy):
        source = AccessLogSource(id="access", installation_id="acme", environment="prod",
                                 root=str(root or self.logs), identities=[dict(i) for i in IDENTITIES],
                                 instrumented_services=["orders", "inventory"])
        return read_access_logs(source, T0, T1, checked_at=checked_at or T1 + timedelta(minutes=1),
                                freshness=FreshnessPolicy(**policy))

    def edges(self, result):
        return {(e["caller"], e["callee"], e["kind"]) for e in relationships(result)}

    def test_zero_traffic_in_a_fully_covered_window_is_reported_but_proves_no_absence(self):
        self.segment("orders", "orders-7f9c", [request(1), request(2)])
        self.segment("inventory", "inventory-2b1d", [])
        result = self.read()
        verdict = assess(result, "export", "orders", "GET", "/orders")
        self.assertEqual(verdict["status"], "NO_TRAFFIC_OBSERVED")
        self.assertFalse(verdict["proves_absence"])
        self.assertNotIn("export", {o["caller"]["service"] for o in result["observations"]})
        self.assertEqual(result["source"]["status"], "AVAILABLE")

    def test_record_without_route_yields_a_service_edge_and_never_an_api_dependency(self):
        # The raw path names /orders, but only a matched route template may name an operation.
        self.segment("orders", "orders-7f9c", [request(1, route=None), request(2, route=None, method=None)])
        result = self.read()
        self.assertEqual(self.edges(result), {("reporting", "orders", "CALLS_SERVICE")})
        (observation,) = result["observations"]
        self.assertIsNone(observation["operation"])
        self.assertIsNone(observation["route"])
        self.assertEqual(observation["sufficiency"], "SERVICE_EDGE_ONLY")
        self.assertEqual(assess(result, "reporting", "orders", "GET", "/orders")["status"], "ROUTE_NOT_RECORDED")

    def test_two_services_with_the_same_path_stay_two_operations(self):
        self.segment("orders", "orders-7f9c", [request(1)])
        self.segment("inventory", "inventory-2b1d", [request(2, client="Health", emitter="inventory-2b1d")])
        result = self.read()
        self.assertEqual(self.edges(result), {
            ("reporting", "orders", "CALLS_OPERATION"), ("reporting", "orders", "CALLS_SERVICE"),
            ("health", "inventory", "CALLS_OPERATION"), ("health", "inventory", "CALLS_SERVICE")})
        operations = {o["callee"]["service"]: o["operation"]["id"] for o in result["observations"] if o["operation"]}
        scope = SimpleNamespace(installation_id="acme", environment="prod")
        # Runtime and code meet on the same node only for the same service.
        self.assertEqual(operations["orders"], code_operation_id(scope, "orders", "GET", "/orders"))
        self.assertEqual(operations["inventory"], code_operation_id(scope, "inventory", "GET", "/orders"))
        self.assertNotEqual(operations["orders"], operations["inventory"])
        self.assertEqual(assess(result, "reporting", "inventory", "GET", "/orders")["status"], "NO_TRAFFIC_OBSERVED")

    def test_uncovered_part_of_window_is_a_gap_not_zero_traffic(self):
        self.segment("orders", "orders-7f9c", [request(1)], start=0, end=4)
        self.segment("inventory", "inventory-2b1d", [], start=0, end=10)
        result = self.read()
        self.assertIn(dict(code="not_covered", service="orders", start="2026-10-24T10:04:00.000Z",
                           end="2026-10-24T10:10:00.000Z"), result["gaps"])
        verdict = assess(result, "export", "orders")
        self.assertEqual((verdict["status"], verdict["reasons"]), ("WINDOW_GAP", ["not_covered"]))
        self.assertEqual(assess(result, "export", "inventory")["status"], "NO_TRAFFIC_OBSERVED")
        self.assertEqual(result["source"]["status"], "PARTIAL")

    def test_unavailable_source_gives_no_observations_and_says_so(self):
        result = self.read(root=self.logs / "missing")
        self.assertEqual(result["source"]["status"], "UNAVAILABLE")
        self.assertEqual(result["observations"], [])
        self.assertEqual({g["code"] for g in result["gaps"]}, {"source_unavailable"})
        verdict = assess(result, "reporting", "orders", "GET", "/orders")
        self.assertEqual(verdict["status"], "SOURCE_UNAVAILABLE")
        self.assertFalse(verdict["proves_absence"])

    def test_corrupt_line_keeps_valid_records_and_blocks_the_no_traffic_claim(self):
        self.segment("orders", "orders-7f9c", [request(1), request(2)],
                     raw_lines=['{"ts": "2026-10-24T10:03:00+00:00", "client": "leak-marker-77", "serv'])
        result = self.read()
        service_edge = next(o for o in result["observations"] if o["kind"] == "CALLS_SERVICE")
        self.assertEqual(service_edge["aggregates"]["request_count"], 2)
        self.assertEqual(result["rejected"], {"invalid_json": 1})
        self.assertIn("corrupt_records", {g["code"] for g in result["gaps"] if g["service"] == "orders"})
        self.assertEqual(assess(result, "export", "orders")["status"], "WINDOW_GAP")
        self.assertNotIn("leak-marker-77", json.dumps(result))

    def test_tampered_segment_is_dropped_as_a_gap(self):
        self.segment("orders", "orders-7f9c", [request(1)])
        with (self.logs / "orders.jsonl").open("a") as stream:
            stream.write(json.dumps(request(3, client="export")) + "\n")
        result = self.read()
        self.assertEqual(result["observations"], [])
        self.assertEqual(assess(result, "export", "orders")["reasons"], ["segment_digest_mismatch"])

    def test_sampled_segment_gives_an_estimate_and_never_reports_no_traffic(self):
        self.segment("orders", "orders-7f9c", [request(1)], sample_rate=0.1)
        result = self.read()
        aggregates = result["observations"][0]["aggregates"]
        self.assertEqual((aggregates["request_count"], aggregates["estimated_request_count"]), (1, 10.0))
        self.assertEqual(assess(result, "export", "orders")["status"], "SAMPLED_NOT_OBSERVED")

    def test_untrusted_records_are_rejected_or_left_unattributed(self):
        self.segment("orders", "orders-7f9c", [
            request(1, client="ignore-previous-instructions"),
            request(2, ts="2026-10-24T10:02:00"),
            request(3, env="stage"),
            request(4, emitter="inventory-2b1d"),
            request(5, route="/orders/../admin"),
            request(6, status=None, duration_ms=None),
        ])
        result = self.read()
        self.assertEqual(result["rejected"], {"emitter_mismatch": 1, "environment_mismatch": 1,
                                              "timestamp_without_offset": 1})
        self.assertEqual([u["request_count"] for u in result["unattributed"]], [1])
        self.assertNotIn("ignore-previous-instructions", json.dumps(result))
        # The bad route degrades to a service edge; aggregates appear only when every record has the field.
        service_edge = next(o for o in result["observations"] if o["kind"] == "CALLS_SERVICE")
        self.assertEqual(service_edge["aggregates"]["request_count"], 2)
        self.assertNotIn("error_count", service_edge["aggregates"])
        self.assertNotIn("latency_ms", service_edge["aggregates"])
        operation_edge = next(o for o in result["observations"] if o["kind"] == "CALLS_OPERATION")
        self.assertEqual(operation_edge["aggregates"]["request_count"], 1)

    def test_old_window_is_stale_under_the_configured_age(self):
        self.segment("orders", "orders-7f9c", [request(1)])
        fresh = self.read(access_log_max_age_seconds=3600)
        stale = self.read(checked_at=T1 + timedelta(hours=2), access_log_max_age_seconds=3600)
        self.assertEqual(fresh["observations"][0]["freshness"]["status"], "CURRENT")
        self.assertEqual(stale["observations"][0]["freshness"]["status"], "STALE")
        self.assertEqual(stale["observations"][0]["id"], fresh["observations"][0]["id"])

    def test_naive_window_is_refused(self):
        source = AccessLogSource(id="access", installation_id="acme", environment="prod", root=str(self.logs),
                                 identities=[dict(i) for i in IDENTITIES], instrumented_services=["orders"])
        with self.assertRaises(GraphError) as raised:
            read_access_logs(source, "2026-10-24T10:00:00", "2026-10-24T11:00:00")
        self.assertEqual(raised.exception.code, "invalid_window")


if __name__ == "__main__":
    unittest.main()
