"""The service on the batch 3 persistent graph: owners, runtime sources and main-line memory."""

from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from agent_service.smoke import SmokeBench, _section

IDENTITIES = [dict(alias=name, service=name) for name in ("orders", "reporting", "archive", "billing", "audit")]


class GraphCase(unittest.TestCase):
    runtime = False

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.logs = self.root / "logs"
        sources = []
        if self.runtime:
            self.write_segment([dict(client="reporting", route="/orders")])
            sources = [dict(id="access", installation_id="acme", environment="prod", root=str(self.logs),
                            identities=IDENTITIES, instrumented_services=["orders"])]
        self.bench = SmokeBench(self.root / "bench", runtime_sources=sources)
        self.addCleanup(self.bench.close)

    def write_segment(self, records):
        """One closed access-log window of the last 10 minutes (access-log-segment-1)."""
        self.logs.mkdir(exist_ok=True)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        lines = [json.dumps(dict(ts=(now - timedelta(minutes=10) + timedelta(seconds=i + 1)).isoformat(),
                                 service="orders", env="prod", method="GET", status=200, **r))
                 for i, r in enumerate(records)]
        data = ("\n".join(lines) + "\n").encode()
        (self.logs / "w1.jsonl").write_bytes(data)
        (self.logs / "w1.coverage.json").write_text(json.dumps(dict(
            schema="access-log-segment-1", file="w1.jsonl", emitter="orders", environment="prod",
            start=(now - timedelta(minutes=10)).isoformat(), end=now.isoformat(), sample_rate=1.0,
            sha256=hashlib.sha256(data).hexdigest())))

    def jira_comment(self, summary=None):
        """Analyze ORD-12 again; a changed summary is a semantic change that opens a new generation."""
        if summary:
            self.bench.jira.set_summary(10012, summary)
            self.bench.deliver_jira("jira:issue_updated", "issue_generic")
        else:
            self.bench.deliver_jira()
        self.bench.drain()
        [text] = self.bench.jira_texts()
        return text

    def jira_result(self):
        job = [j for j in self.bench.service.store.jobs("jira:10012") if j["state"] == "DONE"][-1]
        return job["result"]


class OwnershipTest(GraphCase):
    def test_owner_change_is_addressed_on_the_next_analysis_and_conflicts_are_shown_as_is(self):
        before = _section(self.jira_comment(), "Что может затронуть", "Почему")
        self.assertIn("reporting: команда team-reporting", before)
        mapping = json.loads(self.bench.ownership_path.read_text())
        mapping.update(version="ownership-2")
        mapping["services"].update(reporting=["team-insights", "team-finance"])
        mapping["services"].pop("archive")
        self.bench.ownership_path.write_text(json.dumps(mapping))
        self.bench.service.reconcile_graph()
        after = _section(self.jira_comment("Orders: уменьшить размер страницы до 20"), "Что может затронуть",
                         "Почему")
        self.assertIn("reporting: владелец спорный: team-finance, team-insights (источник: "
                      "installation_mapping@ownership-2)", after)
        self.assertIn("archive: команда не определена", after)
        unknowns = {(u["code"], u["subject"]) for u in self.jira_result()["unknowns"]}
        self.assertTrue({("owner_conflict", "reporting"), ("owner_unknown", "archive")} <= unknowns)
        history = self.bench.analyzer.query().owner_history("reporting")
        self.assertIn(("team-reporting", "ownership_changed"), {(h["team"], h["closed_reason"]) for h in history})

    def test_unreadable_ownership_keeps_the_last_owners_and_is_visible(self):
        self.jira_comment()
        self.bench.ownership_path.write_text("{not json")
        self.bench.service.reconcile_graph()
        self.assertIn("graph_source_unavailable", {n["kind"] for n in self.bench.service.store.notices()})
        after = self.jira_comment("Orders: уменьшить размер страницы до 20")
        self.assertIn("reporting: команда team-reporting", after)


class RuntimeSourceTest(GraphCase):
    runtime = True

    def test_unavailable_runtime_source_keeps_the_code_relationship_and_marks_freshness(self):
        before = self.jira_comment()
        self.assertIn("наблюдаемые вызовы access: reporting -> orders GET /orders", before)
        self.assertIn("runtime:access: CURRENT", before)
        shutil.rmtree(self.logs)
        self.bench.service.reconcile_graph()
        after = self.jira_comment("Orders: уменьшить размер страницы до 20")
        self.assertIn("reporting: команда team-reporting", _section(after, "Что может затронуть", "Почему"))
        self.assertIn("код reporting@", after)  # the code basis stays
        freshness = {(s["source_kind"], s["source_id"]): s["freshness"]["status"]
                     for s in self.jira_result()["source_freshness"]}
        self.assertNotEqual(freshness[("runtime", "access")], "CURRENT")
        self.assertIn("graph_source_unavailable", {n["kind"] for n in self.bench.service.store.notices()})


class MainLineMemoryTest(GraphCase):
    def test_readme_change_on_the_default_branch_keeps_the_relationships_and_their_bases(self):
        self.jira_comment()
        first = self.jira_result()
        query = self.bench.analyzer.query()
        rel_ids = sorted(first["impact_paths"][0]["relationship_refs"] + first["impact_paths"][1]["relationship_refs"])
        opened = {rid: [b["opened_version"] for b in query.relationship(rid)["bases"]] for rid in rel_ids}
        readme = self.bench.stand.head("orders", "readme-only")
        self.bench.github.branches[("acme/orders", "main")] = readme
        self.bench.service.reconcile_graph()
        self.jira_comment("Orders: уменьшить размер страницы до 20")
        second = self.jira_result()
        query = self.bench.analyzer.query()
        self.assertGreater(query.version, int(first["graph_version"].split("-")[1]))
        for rid in rel_ids:
            view = query.relationship(rid)
            self.assertEqual(view["status"], "ACTIVE")
            self.assertEqual([b["opened_version"] for b in view["bases"]], opened[rid])
        self.assertEqual({a["service"]["service"] for a in second["affected"]}, {"reporting", "archive"})
        self.assertEqual(sorted(e["id"] for e in second["evidence"]), sorted(e["id"] for e in first["evidence"]))

    def test_default_branch_push_moves_the_graph_without_reanalysing_open_resources(self):
        # The analysis basis must exclude graph_version: otherwise every push to main
        # would re-analyse and re-edit every open comment on the next reconciliation.
        self.bench.push("pr-7")
        self.bench.drain()
        self.bench.service.reconcile()  # records the basis (one re-analysis after install)
        self.bench.drain()
        version = self.bench.analyzer.query().version
        self.bench.github.branches[("acme/orders", "main")] = self.bench.stand.head("orders", "readme-only")
        result = self.bench.service.reconcile()
        self.assertGreater(self.bench.analyzer.query().version, version)
        self.assertEqual(result["reanalysed"], 0)

    def test_pr_head_never_becomes_graph_memory(self):
        self.bench.push("pr-7")
        self.bench.drain()
        query = self.bench.analyzer.query()
        commits = {b["commit"] for r in query.summary()["services"] for h in query.find(r, kind="operation")
                   for v in query.neighbors(h["id"], direction="in") for b in v["bases"] if b["origin"] == "code"}
        self.assertNotIn(self.bench.stand.head("orders", "pr-7"), commits)


if __name__ == "__main__":
    unittest.main()
