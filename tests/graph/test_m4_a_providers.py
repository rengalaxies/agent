"""M4-A author regressions: impostor decorators cannot prove an HTTP declaration."""
from pathlib import Path
import importlib.util
import tempfile
import sys
import types
from unittest.mock import patch
import unittest

from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store

REAL = '''from fastapi import FastAPI as Factory
api = Factory()
@api.get("/parcels")
def parcels(page_size: int = 40): return {"items": []}
'''
IMPOSTORS = {
    "relative_import": '''from .fastapi import FastAPI
api = FastAPI()
@api.get("/parcels")
def parcels(page_size: int = 40): return {"items": []}
''',
    "shadowed_factory": '''from fastapi import FastAPI
class FastAPI:
    def get(self, path): return lambda fn: fn
api = FastAPI()
@api.get("/parcels")
def parcels(page_size: int = 40): return {"items": []}
''',
    "rebound_application": '''from fastapi import FastAPI
api = FastAPI()
class Plain:
    def get(self, path): return lambda fn: fn
api = Plain()
@api.get("/parcels")
def parcels(page_size: int = 40): return {"items": []}
''',
    "mutated_decorator": '''from fastapi import FastAPI
api = FastAPI()
api.get = lambda path: (lambda fn: fn)
@api.get("/parcels")
def parcels(page_size: int = 40): return {"items": []}
''',
}


class M4AProviderRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.api = self.root / "api.py"
        self.api.write_text(REAL)
        self.store = Store(self.root / "state")
        self.addCleanup(self.store.close)
        self.policy = Policy.model_validate(dict(installation_id="m4-a", environment="test", subject="author",
            capabilities=["read_context", "maintain"],
            repositories=[dict(id="depot", service="depot", root=str(self.root), revision="author")], addresses=[]))
        self.graph = Graph(self.policy, self.store)

    def test_impostors_are_gaps_not_resolved_api_operations(self):
        for name, source in IMPOSTORS.items():
            with self.subTest(name=name):
                self.api.write_text(source)
                context = self.graph.prepare_context()
                self.assertEqual(context["graph"]["operations"], [])
                self.assertEqual(context["coverage"], "PARTIAL")
                self.assertIn("provider_route_unsupported", {g["code"] for g in context["graph"]["gaps"]})

    def test_transition_to_an_impostor_is_not_a_proven_removal(self):
        base = self.graph.prepare_context()
        self.api.write_text(IMPOSTORS["mutated_decorator"])
        analysis = self.graph.analyze_change(base["id"])
        self.assertEqual(analysis["deltas"], [])
        self.assertTrue(analysis["gaps"])

    def test_unsupported_router_or_module_factory_is_not_a_proven_removal(self):
        for source in (REAL.replace("from fastapi import FastAPI as Factory", "from fastapi import APIRouter as Factory"),
                       REAL.replace("from fastapi import FastAPI as Factory", "import fastapi")
                           .replace("api = Factory()", "api = fastapi.FastAPI()")):
            with self.subTest(source=source):
                self.api.write_text(REAL)
                base = self.graph.prepare_context()
                self.api.write_text(source)
                analysis = self.graph.analyze_change(base["id"])
                self.assertEqual(analysis["deltas"], [])
                self.assertIn("provider_route_unsupported", {g["code"] for g in analysis["gaps"]})

    @unittest.skipUnless(importlib.util.find_spec("fastapi") is not None,
                         "optional FastAPI absent; full Core CI executes provider registration")
    def test_executed_impostor_decorators_register_no_http_route(self):
        class Plain:
            def get(self, path):
                return lambda fn: fn
        local = types.ModuleType("m4_local.fastapi")
        local.FastAPI = Plain
        with patch.dict(sys.modules, {"m4_local.fastapi": local}):
            for name, source in IMPOSTORS.items():
                with self.subTest(name=name):
                    namespace = {"__name__": "m4_local.api", "__package__": "m4_local"}
                    exec(compile(source, "author-impostor-fixture", "exec"), namespace)
                    self.assertNotIn("/parcels", {r.path for r in getattr(namespace["api"], "routes", [])})

    def test_unmodified_absolute_import_and_alias_still_resolve(self):
        self.assertEqual([(o["method"], o["path"]) for o in self.graph.prepare_context()["graph"]["operations"]],
                         [("GET", "/parcels")])


if __name__ == "__main__":
    unittest.main()
