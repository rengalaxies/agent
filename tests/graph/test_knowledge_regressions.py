"""R6/R7: current-corpus freshness, stable knowledge and atomic active limits."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from agent_graph.contracts import GraphError, canonical, digest
from agent_graph.engine import Graph
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/agent_graph"))
from fixture import create_fixture


class KnowledgeRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = create_fixture(self.root)
        self.store = Store(self.root/"state")
        self.graph = Graph(self.policy, self.store)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def proposal(self, context, key="usage", kind="hypothesis"):
        s = next(s for s in context["sources"].values() if s["repository"] == "reporting" and s["path"] == "client.py")
        return dict(key=key, kind=kind, statement="Needs a complete-data check", citations=[dict(
            source_id=s["id"], start_line=1, end_line=1, quote=s["text"].splitlines()[0])])

    def test_r6_changed_corpus_makes_candidates_and_corrections_stale(self):
        c = self.graph.prepare_context()
        for kind in ("hypothesis", "human_correction"):
            self.graph.propose(c["id"], self.proposal(c, key=kind, kind=kind))
        (self.root/"corpus/reporting/client.py").write_text("# caller removed\n")
        result = self.graph.dependencies(c["id"])
        self.assertEqual(result["freshness"]["status"], "STALE")
        self.assertEqual({p["status"] for p in result["proposals"]}, {"STALE"})

    def test_r6_ttl_unknown_and_inventory_are_not_current(self):
        c = self.graph.prepare_context()
        self.graph.propose(c["id"], self.proposal(c))
        with patch("agent_graph.engine.time.time", return_value=c["created_epoch"]+100000):
            self.assertEqual(self.graph.proposals(c)[0]["status"], "STALE")
        with patch("agent_graph.engine.collect", side_effect=GraphError("scan_timeout")):
            self.assertEqual(self.graph.proposals(c)[0]["status"], "UNKNOWN")
        (self.root/"corpus/health/new.py").write_text("# new inventory\n")
        self.assertEqual(self.graph.proposals(c)[0]["status"], "STALE")

    def test_r6_legacy_extractor_context_remains_readable_but_not_comparable(self):
        with patch("agent_graph.engine.PROFILE", "http-requests-1"), patch("agent_graph.sources.PROFILE", "http-requests-1"):
            c = self.graph.prepare_context()
        self.assertEqual(self.graph.context(c["id"]), c)
        self.assertEqual(self.graph.freshness(c)["status"], "STALE")
        with self.assertRaisesRegex(GraphError, "base_profile_mismatch"):
            self.graph.analyze_change(c["id"])
        self.assertEqual(self.store.head(self.graph.view)[1], c["id"])

    def test_r7_unchanged_basis_is_idempotent_across_contexts(self):
        self.policy.limits.max_proposals = 1
        ids = []
        for _ in range(3):
            c = self.graph.prepare_context()
            ids.append(self.graph.propose(c["id"], self.proposal(c))["id"])
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.store.proposals(self.graph.view)), 1)

    def test_r7_stale_history_does_not_exhaust_current_basis(self):
        self.policy.limits.max_proposals = 1
        old = self.graph.prepare_context()
        previous = self.graph.propose(old["id"], self.proposal(old))
        p = self.root/"corpus/reporting/client.py"
        p.write_text(p.read_text()+"\n# changed source\n")
        new = self.graph.prepare_context()
        current = self.graph.propose(new["id"], self.proposal(new))
        self.assertNotEqual(previous["id"], current["id"])
        statuses = {p["id"]: p["status"] for p in self.graph.proposals(new)}
        self.assertEqual(statuses, {previous["id"]: "STALE", current["id"]: "CURRENT"})

    def test_r7_human_replacement_is_allowed_at_capacity_and_history_remains(self):
        self.policy.limits.max_proposals = 1
        c = self.graph.prepare_context()
        old = self.graph.propose(c["id"], self.proposal(c))
        correction = {**self.proposal(c), "kind": "human_correction", "supersedes": old["id"], "statement": "Owner clarification"}
        new = self.graph.propose(c["id"], correction)
        self.assertEqual(new, self.graph.propose(c["id"], correction))
        self.assertEqual({p["id"]: p["status"] for p in self.graph.proposals(c)},
                         {old["id"]: "SUPERSEDED", new["id"]: "CURRENT"})
        with self.assertRaisesRegex(GraphError, "proposal_limit"):
            self.graph.propose(c["id"], self.proposal(c, key="another"))
        self.assertEqual(len(self.store.proposals(self.graph.view)), 2)

    def test_r7_concurrent_writers_cannot_exceed_active_limit(self):
        self.policy.limits.max_proposals = 1
        c = self.graph.prepare_context()
        barrier = threading.Barrier(2)
        original = Store.propose
        def publish(store, *args, **kwargs):
            barrier.wait(timeout=5)
            return original(store, *args, **kwargs)
        def worker(key):
            store = Store(self.root/"state")
            try:
                try:
                    return Graph(self.policy, store).propose(c["id"], self.proposal(c, key=key))["id"]
                except GraphError as exc:
                    return exc.code
            finally:
                store.close()
        with patch.object(Store, "propose", publish), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, ("first", "second")))
        self.assertEqual(results.count("proposal_limit"), 1)
        self.assertEqual(len(self.store.proposals(self.graph.view)), 1)

    def test_r7_legacy_publication_keeps_identity_when_reused(self):
        c = self.graph.prepare_context()
        p = self.proposal(c)
        legacy = dict(proposal={**p, "supersedes": None}, context_id=c["id"], basis=c["basis"],
                      actor=self.policy.subject, origin="external", trust="UNAPPROVED_CANDIDATE")
        old_id = digest([self.graph.view, legacy])
        legacy["id"] = old_id
        self.store.db.execute("INSERT INTO proposals VALUES(?,?,?)", (old_id, self.graph.view, canonical(legacy)))
        new = self.graph.prepare_context()
        reused = self.graph.propose(new["id"], self.proposal(new))
        self.assertEqual(reused, legacy)
        self.assertEqual(len(self.store.proposals(self.graph.view)), 1)

    def test_r7_concurrent_replacements_cannot_silently_replace_the_same_target(self):
        self.policy.limits.max_proposals = 1
        c = self.graph.prepare_context()
        old = self.graph.propose(c["id"], self.proposal(c))
        barrier = threading.Barrier(2)
        original = Store.propose
        def publish(store, *args, **kwargs):
            barrier.wait(timeout=5)
            return original(store, *args, **kwargs)
        def worker(statement):
            store = Store(self.root/"state")
            try:
                p = {**self.proposal(c), "kind": "human_correction", "supersedes": old["id"], "statement": statement}
                try:
                    return Graph(self.policy, store).propose(c["id"], p)["id"]
                except GraphError as exc:
                    return exc.code
            finally:
                store.close()
        with patch.object(Store, "propose", publish), ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, ("Clarification one", "Clarification two")))
        self.assertEqual(results.count("concurrent_update"), 1)
        self.assertEqual(len(self.store.proposals(self.graph.view)), 2)
