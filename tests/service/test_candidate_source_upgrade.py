"""Real core/source availability must reach the existing basis-reconciliation gate."""
from pathlib import Path
import tempfile
import unittest

from agent_service.smoke import SmokeBench
from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.graph_store import GraphStore
from agent_graph.graph_store_sync import GraphMaintainer
from agent_graph.store import Store


class SourceUpgradeTest(unittest.TestCase):
    def test_unsupported_dynamic_call_is_partial_but_does_not_mean_the_source_is_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "client.py").write_text("import requests\ndef call(url):\n    return requests.get(url)\n")
            policy = Policy.model_validate(dict(installation_id="source-control", environment="test", subject="author",
                capabilities=["read_context", "maintain"], addresses=[],
                repositories=[dict(id="client", service="client", root=str(root), revision="author")]))
            store = Store(root / "state")
            try:
                graph = Graph(policy, store)
                context = graph.prepare_context()
                self.assertEqual(context["coverage"], "PARTIAL")
                self.assertEqual(GraphMaintainer(graph, GraphStore(store)).on_code_event()["status"], "OK")
            finally:
                store.close()

    def test_missing_git_source_does_not_commit_a_new_basis_then_recovery_reanalyses_same_comments(self):
        with tempfile.TemporaryDirectory() as tmp:
            bench = SmokeBench(Path(tmp))
            try:
                bench.deliver_jira()
                bench.deliver_pr("opened")
                bench.drain()
                bench.service.reconcile()
                bench.drain()
                original_basis = bench.service.store.checkpoint("analysis_basis")
                original_ids = ([c["id"] for c in bench.pr_comments()],
                                [c["id"] for c in bench.jira.comments["10012"]])
                bench.analyzer.analysis_basis = lambda: "author-next-basis"
                source = bench.stand.repo("orders")
                hidden = source.with_name(source.name + "-unavailable")
                source.rename(hidden)
                try:
                    result = bench.service.reconcile()
                    self.assertEqual(result["reanalysed"], 0)
                    self.assertEqual(bench.service.store.checkpoint("analysis_basis"), original_basis)
                    self.assertIn("graph_source_unavailable", {n["kind"] for n in bench.service.store.notices()})
                finally:
                    hidden.rename(source)
                result = bench.service.reconcile()
                self.assertEqual(result["reanalysed"], 2)
                bench.drain()
                self.assertEqual(([c["id"] for c in bench.pr_comments()],
                                  [c["id"] for c in bench.jira.comments["10012"]]), original_ids)
                self.assertNotIn("graph_source_unavailable", {n["kind"] for n in bench.service.store.notices()})
            finally:
                bench.close()
