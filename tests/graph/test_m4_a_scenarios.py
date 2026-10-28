"""Author-written scenarios on a fresh Depot/Dispatch fixture; not a held-out benchmark."""
import json
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from agent_graph.contracts import GraphError
from agent_graph.engine import Graph
from agent_graph.graph_query import GraphQuery
from agent_graph.graph_store import GraphStore
from tests.graph.m4_a_fixture import Fixture


HAS_ASGI = all(importlib.util.find_spec(name) is not None for name in ("fastapi", "httpx"))
ASGI_REASON = "optional FastAPI/httpx absent; full Core CI executes the ASGI oracle"


class M4AScenarios(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.fixture = Fixture(Path(tmp.name))
        self.addCleanup(self.fixture.close)

    @unittest.skipUnless(HAS_ASGI, ASGI_REASON)
    def test_documentation_commit_does_not_change_the_executed_api_or_produce_delta(self):
        f = self.fixture
        base = f.context()
        with f.runtime() as (exports, _):
            before = exports["dispatch"]()
        f.change("depot", "README.md", "Document GET /parcels and POST /labels. No API change.\n", "docs")
        analysis = f.analyze(base)
        with f.runtime() as (exports, _):
            self.assertEqual(exports["dispatch"](), before)
        self.assertEqual(analysis["deltas"], [])
        self.assertEqual(analysis["findings"], [])

    @unittest.skipUnless(HAS_ASGI, ASGI_REASON)
    def test_configured_prefix_and_shared_route_resolve_only_the_authorized_address(self):
        f = self.fixture
        # Requirements do not discover the caller: repeat discovery without them.
        context = f.context(Graph(f.make_policy(requirements=False), f.store))
        [dep] = context["graph"]["dependencies"]
        operation = next(o for o in context["graph"]["operations"] if o["id"] == dep["operation_id"])
        self.assertEqual((dep["consumer"], operation["service"], operation["path"]),
                         ("dispatch", "depot", "/parcels"))
        with f.runtime() as (exports, calls):
            self.assertEqual(exports["dispatch"](), list(range(9)))
        self.assertEqual(calls[0]["url"], "https://edge.example.test/v2/parcels")

    @unittest.skipUnless(HAS_ASGI, ASGI_REASON)
    def test_wrapper_really_calls_the_api_but_is_not_promoted_to_a_static_dependency(self):
        f = self.fixture
        context = f.context()
        self.assertNotIn("wrapped", {d["consumer"] for d in context["graph"]["dependencies"]})
        wrapped = {s["id"] for s in context["sources"].values() if s["repository"] == "wrapped"}
        self.assertTrue(any(g["code"] == "dynamic_or_unsupported_call"
                            and g.get("evidence", {}).get("source_id") in wrapped for g in context["graph"]["gaps"]))
        with f.runtime() as (exports, _):
            self.assertEqual(exports["wrapped"](), list(range(9)))
        provider = f.repositories / "depot/api.py"
        f.change("depot", "api.py", provider.read_text().replace("page_size: int = 40", "page_size: int = 3"), "limit")
        analysis = f.analyze(context)
        with f.runtime() as (exports, _):
            actual = {name: fn() for name, fn in exports.items()}
        self.assertEqual(actual, {"dispatch": [0, 1, 2], "wrapped": [0, 1, 2]})
        self.assertEqual({(x["consumer"], x["code"]) for x in analysis["findings"]},
                         {("dispatch", "POSSIBLE_TRUNCATION")})
        self.assertTrue(all(not x["test_executed"] for x in analysis["findings"]))

    def test_new_cited_git_source_makes_the_basis_stale_without_rewriting_pinned_history(self):
        f = self.fixture
        base = f.context()
        s = next(s for s in base["sources"].values() if s["repository"] == "dispatch" and s["path"] == "client.py")
        proposal = dict(key="author-review", kind="human_correction", statement="Inspect export completeness",
            citations=[dict(source_id=s["id"], start_line=1, end_line=1, quote=s["text"].splitlines()[0])])
        old = f.graph.propose(base["id"], proposal)
        p = f.repositories / "dispatch/client.py"
        f.change("dispatch", "client.py", p.read_text() + "\n# cited source changed\n", "source")
        newer = f.context()
        self.assertEqual(f.graph.freshness(base)["status"], "CURRENT")  # the old pinned tree is immutable
        [row] = f.graph.proposals(newer)
        self.assertEqual((row["id"], row["status"]), (old["id"], "STALE"))
        self.assertIn("proposal_basis_differs", row["freshness"]["reasons"])

    def test_revocation_cannot_reuse_a_wide_context_after_the_source_changed(self):
        f = self.fixture
        wide = f.context()
        narrow = Graph(f.make_policy(exclude=("dispatch",)), f.store)
        with self.assertRaisesRegex(GraphError, "not_found"):
            narrow.context(wide["id"])
        current = f.context(narrow, exclude=("dispatch",))
        self.assertNotIn("dispatch", {d["consumer"] for d in current["graph"]["dependencies"]})
        self.assertNotIn("dispatch", {s["repository"] for s in current["sources"].values()})
        self.assertNotIn("R-dispatch-all", json.dumps(current["graph"]["requirements"]))

    def test_old_profile_knowledge_needs_revalidation_even_if_its_quotes_are_unchanged(self):
        f = self.fixture
        with patch("agent_graph.engine.PROFILE", "http-requests-previous"), \
             patch("agent_graph.sources.PROFILE", "http-requests-previous"):
            old = f.context()
            source = next(s for s in old["sources"].values() if s["repository"] == "dispatch"
                          and s["path"] == "client.py")
            f.graph.propose(old["id"], dict(key="old-profile", kind="hypothesis", statement="Review this call",
                citations=[dict(source_id=source["id"], start_line=1, end_line=1,
                                quote=source["text"].splitlines()[0])]))
        current = f.context()
        self.assertEqual(f.graph.freshness(current)["status"], "CURRENT")
        self.assertEqual([p["status"] for p in f.graph.proposals(current)], ["STALE"])

    def test_old_extractor_profile_cannot_stay_current_just_because_git_trees_are_pinned(self):
        f = self.fixture
        with patch("agent_graph.engine.PROFILE", "http-requests-previous"), \
             patch("agent_graph.sources.PROFILE", "http-requests-previous"):
            old = f.context()
        self.assertEqual(f.graph.freshness(old)["status"], "STALE")

    def test_legacy_knowledge_without_config_digest_checks_its_original_profile(self):
        f = self.fixture
        for profile, expected in (("http-requests-4", "STALE"), ("http-requests-5", "CURRENT")):
            with self.subTest(profile=profile), patch("agent_graph.engine.PROFILE", profile), \
                 patch("agent_graph.sources.PROFILE", profile):
                old = f.context()
                source = next(s for s in old["sources"].values() if s["repository"] == "dispatch"
                              and s["path"] == "client.py")
                proposal = f.graph.propose(old["id"], dict(key=profile, kind="hypothesis", statement=profile,
                    citations=[dict(source_id=source["id"], start_line=1, end_line=1,
                                    quote=source["text"].splitlines()[0])]))
                # Legacy schema-1 proposals have no stored configuration digest.
                f.store.db.execute("UPDATE proposal_bases SET config=NULL WHERE id=?", (proposal["id"],))
            current = f.context()
            rows = {p["id"]: p for p in f.graph.proposals(current)}
            self.assertEqual(rows[proposal["id"]]["status"], expected)
            self.assertEqual(f.graph.context(old["id"]), old)

    def test_persisted_code_is_stale_before_profile_rebuild_and_history_survives(self):
        f = self.fixture
        gs = GraphStore(f.store)
        with patch("agent_graph.engine.PROFILE", "http-requests-4"), \
             patch("agent_graph.sources.PROFILE", "http-requests-4"):
            old = f.context()
        gs.sync_code(old)
        query = GraphQuery.for_policy(gs, f.policy)
        previous = [b for b in gs.bases(query.scope) if b["origin"] == "code"]
        self.assertTrue(previous)
        self.assertEqual({query.basis_freshness(b)["status"] for b in previous}, {"STALE"})
        gs.sync_code(f.context())
        query = GraphQuery.for_policy(gs, f.policy)
        history = {b["id"]: b for b in gs.bases(query.scope)}
        self.assertTrue(all(history[b["id"]]["closed_version"] is not None for b in previous))
        active = [b for b in history.values() if b["closed_version"] is None]
        self.assertEqual({query.basis_freshness(b)["status"] for b in active}, {"CURRENT"})
        self.assertEqual(f.graph.context(old["id"]), old)

    def test_untagged_persisted_code_is_stale_until_revalidated(self):
        f = self.fixture
        gs = GraphStore(f.store)
        gs.sync_code(f.context())
        for id, raw in f.store.db.execute("SELECT id,data FROM graph_bases WHERE origin='code'").fetchall():
            data = json.loads(raw)
            data.pop("profile", None)  # representation written by profile 4
            f.store.db.execute("UPDATE graph_bases SET data=? WHERE id=?", (json.dumps(data), id))
        query = GraphQuery.for_policy(gs, f.policy)
        self.assertEqual({query.basis_freshness(b)["status"] for b in gs.bases(query.scope)}, {"STALE"})


if __name__ == "__main__":
    unittest.main()
