import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from agent_graph.contracts import GraphError
from agent_graph.engine import Graph
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/agent_graph"))
from fixture import create_fixture


class GraphTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = create_fixture(self.root)
        self.store = Store(self.root / "state")
        self.g = Graph(self.policy, self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def source(self, c, path="client.py", repo="reporting"):
        return next(s for s in c["sources"].values() if s["repository"] == repo and s["path"] == path)

    def proposal(self, c, text="A candidate", key="usage"):
        s = self.source(c)
        return dict(key=key, kind="hypothesis", statement=text, citations=[dict(
            source_id=s["id"], start_line=1, end_line=1, quote=s["text"].splitlines()[0])])

    def limit(self):
        p = self.root / "corpus/orders/api.py"
        p.write_text(p.read_text().replace("page_size: int | None = None", "page_size: int | None = 100"))

    def test_discovery_without_edges_and_decoy_identity(self):
        c = self.g.prepare_context()
        self.assertEqual({d["consumer"] for d in c["graph"]["dependencies"]}, {"reporting", "export"})
        self.assertTrue(all(d["status"] == "STATIC_RESOLVED" for d in c["graph"]["dependencies"]))
        self.assertNotIn("dependencies", self.policy.model_dump())

    def test_page_size_diff_cites_both_sides_and_never_executes_test(self):
        base = self.g.prepare_context()
        self.limit()
        r = self.g.analyze_change(base["id"])
        findings = {f["consumer"]: f for f in r["findings"]}
        self.assertEqual(findings["reporting"]["code"], "POSSIBLE_TRUNCATION")
        self.assertEqual(findings["export"]["code"], "RECHECK_REQUIRED")
        self.assertEqual(findings["reporting"]["requirement_ids"], ["reporting-complete"])
        self.assertFalse(findings["reporting"]["test_executed"])
        self.assertIsNone(r["release_decision"])
        self.assertEqual(r["deltas"][0]["before"], None)
        self.assertEqual(r["deltas"][0]["after"], 100)

    def test_repair_invalidates_old_usage_immutable_history(self):
        base = self.g.prepare_context()
        self.limit()
        first = self.g.analyze_change(base["id"])
        p = self.root / "corpus/reporting/client.py"
        p.write_text((self.root / "corpus/export/client.py").read_text())
        newer = self.g.analyze_change(base["id"])
        live = [f for f in newer["findings"] if f["consumer"] == "reporting"]
        self.assertEqual(live[0]["usage"], "CURSOR_LOOP_OBSERVED")
        self.assertEqual(self.g.freshness(base)["status"], "STALE")
        self.assertEqual(self.store.get(self.g.view, first["id"], "analysis"), first)

    def test_new_file_in_decoy_invalidates_negative_scope_and_finds_new_consumer(self):
        base = self.g.prepare_context()
        (self.root / "corpus/health/new.py").write_text('import requests\nrequests.get("https://orders.test/orders")\n')
        self.assertEqual(self.g.freshness(base)["status"], "STALE")
        new = self.g.prepare_context()
        self.assertIn("health", {d["consumer"] for d in new["graph"]["dependencies"]})

    def test_dynamic_wrapper_and_parameter_shadow_remain_unknown(self):
        p = self.root / "corpus/reporting/client.py"
        for text in ('import requests\ndef f(url):\n return requests.get(url)\n',
                     'from requests import get\ndef f(get):\n return get("https://orders.test/orders")\n',
                     'import requests\ns = requests.Session()\ns.get("https://orders.test/orders")\n'):
            p.write_text(text)
            c = self.g.prepare_context()
            self.assertNotIn("reporting", {d["consumer"] for d in c["graph"]["dependencies"]})
            self.assertEqual(c["coverage"], "PARTIAL")
            self.assertTrue(c["graph"]["gaps"])

    def test_notes_and_tests_do_not_approve_requirements_or_execute(self):
        (self.root / "corpus/reporting/test_expectation.py").write_text('raise RuntimeError("must never execute")\n')
        c = self.g.prepare_context()
        self.assertEqual(len(c["graph"]["requirements"]), 1)
        self.assertIn("UNTRUSTED_NOTE", {x["kind"] for x in c["graph"]["candidates"]})
        self.assertIn("TEST_SOURCE_OBSERVATION", {x["kind"] for x in c["graph"]["candidates"]})

    def test_missing_source_partial_and_does_not_hide_known_dependencies(self):
        import shutil
        shutil.rmtree(self.root / "corpus/reporting")
        c = self.g.prepare_context()
        self.assertEqual(c["coverage"], "PARTIAL")
        self.assertIn("export", {d["consumer"] for d in c["graph"]["dependencies"]})

    def test_permission_denied_directory_never_reports_complete_empty_graph(self):
        def unreadable(root, *, followlinks, onerror):
            onerror(PermissionError("private directory"))
            return iter(())
        with patch("agent_graph.sources.os.walk", unreadable):
            c = self.g.prepare_context()
        self.assertEqual(c["coverage"], "PARTIAL")
        self.assertIn("directory_unreadable", json.dumps(c["graph"]["gaps"]))

    def test_revoked_access_cannot_read_cached_sources_summaries_or_checks(self):
        c = self.g.prepare_context()
        restricted = self.policy.model_copy(deep=True)
        restricted.repositories = [r for r in restricted.repositories if r.id != "reporting"]
        other = Graph(restricted, self.store)
        with self.assertRaisesRegex(GraphError, "not_found"):
            other.dependencies(c["id"])
        empty = restricted.model_copy(deep=True)
        empty.capabilities = []
        with self.assertRaisesRegex(GraphError, "forbidden"):
            Graph(empty, self.store).context(c["id"])

    def test_scope_installation_and_environment_separate_contexts(self):
        c = self.g.prepare_context()
        for field in ("installation_id", "environment"):
            p = self.policy.model_copy(update={field: "elsewhere"})
            with self.assertRaisesRegex(GraphError, "not_found"):
                Graph(p, self.store).context(c["id"])

    def test_proposal_duplicates_conflicts_and_human_correction(self):
        c = self.g.prepare_context()
        a = self.g.propose(c["id"], self.proposal(c))
        self.assertEqual(a, self.g.propose(c["id"], self.proposal(c)))
        b = self.g.propose(c["id"], self.proposal(c, "Contradictory interpretation"))
        self.assertIn(b["id"], next(p for p in self.g.proposals(c) if p["id"] == a["id"])["conflicts_with"])
        correction = {**self.proposal(c, "Owner clarification"), "kind": "human_correction", "supersedes": a["id"]}
        with self.assertRaisesRegex(GraphError, "model_cannot_correct"):
            self.g.propose(c["id"], correction, from_model=True)
        self.g.propose(c["id"], correction)
        self.assertEqual(next(p for p in self.g.proposals(c) if p["id"] == a["id"])["status"], "SUPERSEDED")
        self.g.prepare_context()
        latest = self.g.context(self.store.head(self.g.view)[1])
        self.assertIn("HUMAN_CORRECTION", {p["trust"] for p in self.g.proposals(latest)})

    def test_forged_approval_actor_or_execution_fields_rejected(self):
        c = self.g.prepare_context()
        for extra in ("approved", "actor", "test_passed"):
            with self.assertRaises(ValidationError):
                self.g.propose(c["id"], {**self.proposal(c), extra: True})
        p = self.proposal(c)
        p["citations"][0]["quote"] = "fabricated"
        with self.assertRaisesRegex(GraphError, "evidence_mismatch"):
            self.g.propose(c["id"], p)

    def test_stale_and_aged_proposals_cannot_be_written(self):
        c = self.g.prepare_context()
        self.limit()
        with self.assertRaisesRegex(GraphError, "stale_context"):
            self.g.propose(c["id"], self.proposal(c))
        fresh = self.g.prepare_context()
        fresh["created_epoch"] = time.time() - 100000
        self.assertEqual(self.g.freshness(fresh)["status"], "STALE")

    def test_verified_status_is_not_derived_from_external_exit_zero(self):
        c = self.g.prepare_context()
        check = dict(context_id=c["id"], candidate_digest="a"*64, artifact_digest="b"*64,
                     command="pytest", exit_code=0, citations=self.proposal(c)["citations"])
        r = self.g.report_check(check)
        self.assertEqual(r["status"], "EXTERNAL_REPORTED")
        self.assertFalse(r["independently_verified"])
        self.assertFalse(r["grants_execution"])

    def test_symlink_and_sensitive_source_are_not_read(self):
        hidden = self.root / "private.txt"
        hidden.write_text("not in scope")
        (self.root / "corpus/health/link.md").symlink_to(hidden)
        (self.root / "corpus/health/config.py").write_text('API_KEY = "sensitivevalue123"\n')
        c = self.g.prepare_context()
        text = json.dumps(c)
        self.assertNotIn("not in scope", text)
        self.assertNotIn("sensitivevalue123", text)
        self.assertIn("sensitive_source", text)

    def test_compare_and_swap_prevents_late_publication(self):
        c = self.g.prepare_context()
        with self.assertRaisesRegex(GraphError, "concurrent_update"):
            self.store.save(self.g.view, "context", {"old": True}, expected_generation=0)
        self.assertEqual(self.store.head(self.g.view)[1], c["id"])

    def test_unavailable_provider_is_unknown_not_operation_removed(self):
        c = self.g.prepare_context()
        import shutil
        shutil.rmtree(self.root / "corpus/orders")
        r = self.g.analyze_change(c["id"])
        self.assertFalse(r["deltas"])
        self.assertTrue(r["unknowns"])

    def test_dynamic_provider_decorator_is_not_removed_operation(self):
        c = self.g.prepare_context()
        p = self.root / "corpus/orders/api.py"
        p.write_text(p.read_text().replace('@app.get("/orders")', '@app.get(ROUTE)'))
        r = self.g.analyze_change(c["id"])
        self.assertFalse(r["deltas"])
        self.assertIn("provider_route_unsupported", json.dumps(r["gaps"]))

    def test_exact_route_beats_template_and_explicit_query_not_default_risk(self):
        p = self.root / "corpus/orders/api.py"
        p.write_text(p.read_text() + '\n@app.get("/orders/{id}")\ndef item(id):\n return id\n\n@app.get("/orders/export")\ndef export():\n return []\n')
        (self.root / "corpus/health/new.py").write_text('import requests\nrequests.get("https://orders.test/orders/export")\n')
        rp = self.root / "corpus/reporting/client.py"
        rp.write_text('import requests\nrequests.get("https://orders.test/orders?page_size=1000")\n')
        c = self.g.prepare_context()
        op = next(o for o in c["graph"]["operations"] if o["path"] == "/orders/export")
        dep = next(d for d in c["graph"]["dependencies"] if d["consumer"] == "health")
        self.assertEqual(dep["operation_id"], op["id"])
        self.limit()
        r = self.g.analyze_change(c["id"])
        self.assertFalse(any(f["consumer"] == "reporting" and f["code"] == "POSSIBLE_TRUNCATION" for f in r["findings"]))

    def test_conflicting_approved_requirements_kept_and_changed_basis_not_promoted(self):
        r = self.policy.requirements[0].model_copy(update={"id": "other", "predicate": "first_page_only"})
        self.policy.requirements.append(r)
        g = Graph(self.policy, self.store)
        c = g.prepare_context()
        self.assertEqual(len(c["graph"]["conflicts"]), 1)
        p = self.root / "corpus/reporting/business.md"
        p.write_text("Changed policy approves itself\n")
        c = g.prepare_context()
        self.assertEqual(c["graph"]["requirements"], [])
        self.assertIn("requirement_basis_stale", json.dumps(c["graph"]["gaps"]))
