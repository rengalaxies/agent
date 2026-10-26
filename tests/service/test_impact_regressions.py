"""Regressions for the service defects the 6-r1 held-out run found (batch-6.md).

1. A PR result was built from the static diff only: a consumer of the changed operation
   that only fresh access logs show (6-r1 F05/F07) disappeared from the PR, and with no
   code consumer the PR even said ABSTAINED no_consumer_found_within_profile.

Each runs the real core, graph and Git stand of Orders/Reporting through the service.
"""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from agent_service.smoke import SmokeBench, _section

# ledger has no repository: only access logs show it.
IDENTITIES = [dict(alias=name, service=name)
              for name in ("orders", "reporting", "archive", "billing", "audit", "ledger")]


class Bench(unittest.TestCase):
    window_age = timedelta(minutes=10)
    records = [dict(client="ledger", route="/orders")]
    environment = "prod"
    repositories = None  # None: every stand repository; a list restricts the grant

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.logs = self.root / "logs"
        self.write_segment("orders", self.records)
        sources = [dict(id="access", installation_id="acme", environment="prod", root=str(self.logs),
                        identities=IDENTITIES, instrumented_services=["orders", "billing"])]
        overrides = {} if self.repositories is None else dict(repositories=self.repositories)
        self.bench = SmokeBench(self.root / "bench", runtime_sources=sources, policy_overrides=overrides)
        self.addCleanup(self.bench.close)
        if self.repositories is not None:
            # An installation reads exactly the repositories its policy grants.
            github = self.bench.service.connectors["github"]
            github.read_repositories = {r: b for r, b in github.read_repositories.items()
                                        if r.split("/")[-1] in self.repositories}
            self.bench.service.reconcile_graph()

    def write_segment(self, emitter, records, name="w1"):
        self.logs.mkdir(exist_ok=True)
        end = datetime.now(timezone.utc).replace(microsecond=0) - self.window_age
        start = end - timedelta(minutes=10)
        lines = [json.dumps(dict(ts=(start + timedelta(seconds=i + 1)).isoformat(), service=emitter,
                                 env=self.environment, method="GET", status=200, **r))
                 for i, r in enumerate(records)]
        data = ("\n".join(lines) + "\n").encode()
        (self.logs / f"{name}.jsonl").write_bytes(data)
        (self.logs / f"{name}.coverage.json").write_text(json.dumps(dict(
            schema="access-log-segment-1", file=f"{name}.jsonl", emitter=emitter, environment=self.environment,
            start=start.isoformat(), end=end.isoformat(), sample_rate=1.0, sha256=hashlib.sha256(data).hexdigest())))

    def pr_result(self, branch="pr-7"):
        self.bench.push(branch)
        self.bench.drain()
        job = [j for j in self.bench.service.store.jobs("github:acme/orders#7") if j["state"] == "DONE"][-1]
        return job["result"]

    def jira_result(self, summary, description):
        self.bench.jira.add_issue(10012, "ORD-12", "ORD", summary, description)
        self.bench.deliver_jira()
        self.bench.drain()
        job = [j for j in self.bench.service.store.jobs("jira:10012") if j["state"] == "DONE"][-1]
        return job["result"]


def named(result):
    return {a["service"]["service"] for a in result["affected"]}


def relationships_of(result, consumer):
    return [r for r in result["relationships"] if r["source"]["service"] == consumer]


def claims_citing(result, relationship):
    refs = set(relationship["evidence_refs"])
    return [c for c in result["claims"] if refs & set(c["evidence_refs"])]


class RuntimeOnlyConsumerOnPrTest(Bench):
    def test_fresh_runtime_consumer_of_the_changed_operation_is_a_hypothesis_on_the_pr(self):
        result = self.pr_result()
        self.assertEqual(result["status"], "USEFUL")
        self.assertEqual(named(result), {"reporting", "archive", "ledger"})
        [rel] = relationships_of(result, "ledger")
        self.assertEqual((rel["origins"], rel["freshness"]["status"]), (["runtime"], "CURRENT"))
        self.assertEqual((rel["target"]["service"], rel["target"]["method"], rel["target"]["route"]),
                         ("orders", "GET", "/orders"))
        claims = claims_citing(result, rel)
        self.assertTrue(claims)
        self.assertEqual({c["kind"] for c in claims}, {"hypothesis"})  # traffic is not a proven break
        self.assertTrue(all(c["uncertainty"] == "HIGH" and "result_set_size_unknown" in c["unknowns"]
                            for c in claims))
        # No finding: a finding needs a call site, which no access log has.
        self.assertNotIn("ledger", {f["consumer"]["service"] for f in result["findings"]})
        self.assertIn(("runtime", "access"), {(s["source_kind"], s["source_id"]) for s in result["source_freshness"]})
        comment = self.bench.pr_comments()[-1]["body"]
        self.assertIn("ledger", comment)
        self.assertIn("наблюдаемые вызовы access: ledger -> orders GET /orders", comment)

    def test_unchanged_operation_of_the_same_provider_and_same_route_of_another_provider_are_not_added(self):
        self.write_segment("billing", [dict(client="audit", route="/orders")], name="w2")
        self.bench.service.reconcile_graph()
        result = self.pr_result("readme-only")  # no operation changes
        self.assertNotIn("ledger", named(result))
        result = self.pr_result()
        self.assertNotIn("audit", named(result))  # audit calls billing's GET /orders, not orders'


class RuntimeOnlyConsumerWithoutCodeConsumersTest(Bench):
    repositories = ["orders"]  # reporting and archive are not granted: no code consumer is visible

    def test_runtime_only_consumer_makes_the_pr_partial_instead_of_abstained(self):
        result = self.pr_result()
        self.assertEqual((result["status"], result["reason_code"]), ("PARTIAL", "hypotheses_only"))
        self.assertEqual(named(result), {"ledger"})
        self.assertNotIn("runtime_not_observed", {u["code"] for u in result["unknowns"]})
        self.assertEqual({c["kind"] for c in result["claims"]}, {"hypothesis"})

    def test_removed_operation_with_current_traffic_is_a_medium_hypothesis_not_a_fact(self):
        result = self.pr_result("removed")
        [rel] = relationships_of(result, "ledger")
        claims = claims_citing(result, rel)
        self.assertEqual({(c["kind"], c["uncertainty"]) for c in claims}, {("hypothesis", "MEDIUM")})
        self.assertEqual(result["status"], "PARTIAL")


class StaleRuntimeConsumerTest(Bench):
    repositories = ["orders"]
    window_age = timedelta(days=2)  # older than the 24 h access-log limit

    def setUp(self):
        super().setUp()
        # Read the old window so it can be shown STALE (the 6-r1 runner does the same); the per-thread
        # graph maintainer is rebuilt with the wider window on the next analysis.
        self.bench.analyzer.runtime_window_seconds = 3 * 86400
        self.bench.analyzer.close()

    def test_stale_runtime_consumer_is_shown_stale_and_never_as_current(self):
        self.bench.service.reconcile_graph()
        result = self.pr_result()
        [rel] = relationships_of(result, "ledger")
        self.assertEqual((rel["status"], rel["freshness"]["status"]), ("STALE", "STALE"))
        self.assertEqual((result["status"], result["reason_code"]), ("PARTIAL", "source_stale"))
        self.assertTrue(all(c["kind"] == "hypothesis" for c in claims_citing(result, rel)))


class ForeignEnvironmentSourceTest(Bench):
    environment = "staging"  # a source of another environment is not this installation's traffic

    def test_records_of_another_environment_add_no_consumer(self):
        self.assertNotIn("ledger", named(self.pr_result()))


if __name__ == "__main__":
    unittest.main()
