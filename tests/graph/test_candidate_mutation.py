"""New author regression: explicit builtin mutation is not positive API evidence."""
from pathlib import Path
import tempfile
import unittest

from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store
from tests.graph.candidate_matrix import MUTATED, PROVIDER


class MutableDeclarationTest(unittest.TestCase):
    def test_setattr_on_the_app_is_unknown_but_mutating_another_object_keeps_the_route(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            api = root / "api.py"
            policy = Policy.model_validate(dict(installation_id="mutation-author", environment="test", subject="author",
                capabilities=["read_context", "maintain"], addresses=[],
                repositories=[dict(id="catalog", service="catalog", root=str(root), revision="author")]))
            store = Store(root / "state")
            try:
                graph = Graph(policy, store)
                api.write_text(PROVIDER)
                base = graph.prepare_context()
                api.write_text(MUTATED)
                context = graph.prepare_context()
                self.assertEqual(context["graph"]["operations"], [])
                self.assertEqual(context["coverage"], "PARTIAL")
                self.assertIn("provider_route_unsupported", {g["code"] for g in context["graph"]["gaps"]})
                self.assertEqual(graph.analyze_change(base["id"])["deltas"], [])
                api.write_text(PROVIDER.replace("api = FastAPI()", 'api = FastAPI()\nother = type("Other", (), {})()\nsetattr(other, "get", lambda path: None)'))
                self.assertEqual({o["method"] for o in graph.prepare_context()["graph"]["operations"]}, {"GET", "POST"})
            finally:
                store.close()
