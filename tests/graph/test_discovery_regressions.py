"""R2-R4: regression cases for the closed HTTP grammar, not a v4 benchmark."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from agent_graph.engine import Graph
from agent_graph.store import Store

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "examples/agent_graph"))
from fixture import create_fixture


class DiscoveryRegressions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.policy = create_fixture(self.root)
        self.store = Store(self.root/"state")
        self.graph = Graph(self.policy, self.store)
        self.client = self.root/"corpus/reporting/client.py"

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def reporting(self, context):
        return [d for d in context["graph"]["dependencies"] if d["consumer"] == "reporting"]

    def limit(self):
        path = self.root/"corpus/orders/api.py"
        path.write_text(path.read_text().replace("page_size: int | None = None", "page_size: int | None = 100"))

    def test_r2_operation_parameter_overrides_path_and_change_is_found(self):
        (self.root/"corpus/orders/api.py").unlink()
        def parameter(value):
            return dict(name="page_size", **{"in": "query"}, schema=dict(default=value))
        doc = dict(openapi="3.1.1", paths={"/orders": dict(parameters=[parameter(100)], get=dict(parameters=[parameter(None)]))})
        path = self.root/"corpus/orders/openapi.json"
        path.write_text(json.dumps(doc))
        base = self.graph.prepare_context()
        doc["paths"]["/orders"]["get"]["parameters"] = [parameter(10)]
        path.write_text(json.dumps(doc))
        result = self.graph.analyze_change(base["id"])
        self.assertEqual([(d["before"], d["after"]) for d in result["deltas"]], [(None, 10)])
        self.assertTrue(any(f["consumer"] == "reporting" and f["code"] == "POSSIBLE_TRUNCATION" for f in result["findings"]))

    def test_r2_override_without_default_and_parameter_location(self):
        (self.root/"corpus/orders/api.py").unlink()
        path = self.root/"corpus/orders/openapi.json"
        query = dict(name="page_size", **{"in": "query"}, schema=dict(default=100))
        for override, known, value in [
            (dict(name="page_size", **{"in": "query"}, schema=dict(type="integer")), False, None),
            (dict(name="page_size", **{"in": "header"}, schema=dict(default=500)), True, 100),
        ]:
            with self.subTest(override=override):
                doc = dict(openapi="3.1.1", paths={"/orders": dict(parameters=[query], get=dict(parameters=[override]))})
                path.write_text(json.dumps(doc))
                op = self.graph.prepare_context()["graph"]["operations"][0]
                self.assertEqual(op["default_known"], known)
                if known:
                    self.assertEqual(op["page_size_default"], value)

    def provider(self, constant, parameter):
        original = Path(__file__).resolve().parents[2]/"examples/agent_graph/corpus/orders/api.py"
        (self.root/"corpus/orders/api.py").write_text(
            original.read_text().replace("page_size: int | None = None", parameter)
            .replace("from fastapi import FastAPI", "from fastapi import FastAPI, Query\n\nDEFAULT = " + constant))

    def test_r5_unresolved_page_default_change_requires_recheck_not_silence(self):
        # Audit 2026-10-22: Query(None) -> Query(100) produced no delta and no finding.
        self.provider("None", "page_size: int | None = Query(None)")
        base = self.graph.prepare_context()
        self.assertIn("page_size_default_unresolved", {g["code"] for g in base["graph"]["gaps"]})
        self.provider("None", "page_size: int | None = Query(100)")
        result = self.graph.analyze_change(base["id"])
        self.assertEqual([(d["code"], d["before"], d["after"]) for d in result["deltas"]],
                         [("PAGE_DEFAULT_UNRESOLVED", "UNRESOLVED", "UNRESOLVED")])
        self.assertEqual([(f["consumer"], f["code"]) for f in result["findings"]
                          if f["consumer"] == "reporting"], [("reporting", "RECHECK_REQUIRED")])
        self.assertEqual(result["unknowns"], [])
        unchanged = self.graph.analyze_change(self.graph.prepare_context()["id"])
        self.assertEqual(unchanged["deltas"], [])

    def test_r5_module_constant_page_default_change_is_classified(self):
        # Audit 2026-10-22: DEFAULT = None -> DEFAULT = 100 left the signature text unchanged.
        self.provider("None", "page_size: int | None = DEFAULT")
        base = self.graph.prepare_context()
        self.provider("100", "page_size: int | None = DEFAULT")
        result = self.graph.analyze_change(base["id"])
        self.assertEqual([(d["code"], d["before"], d["after"]) for d in result["deltas"]],
                         [("PAGE_DEFAULT_CHANGED", None, 100)])
        self.assertTrue(any(f["consumer"] == "reporting" and f["code"] == "POSSIBLE_TRUNCATION"
                            for f in result["findings"]))

    def test_r6_referenced_openapi_page_default_change_requires_recheck_not_silence(self):
        # Architecture audit 2026-10-22: a pretty-printed contract whose page_size schema or
        # parameter is a $ref changed None -> 100 with no delta, and the schema case had no gap.
        (self.root/"corpus/orders/api.py").unlink()
        path = self.root/"corpus/orders/openapi.json"
        def contract(default, by_reference):
            if by_reference == "schema":
                parameter = dict(name="page_size", **{"in": "query"}, schema={"$ref": "#/components/schemas/Page"})
                components = dict(schemas=dict(Page=dict(type="integer", default=default)))
            else:
                parameter = {"$ref": "#/components/parameters/Page"}
                components = dict(parameters=dict(Page=dict(name="page_size", **{"in": "query"},
                                                            schema=dict(type="integer", default=default))))
            return json.dumps(dict(openapi="3.1.1", paths={"/orders": dict(get=dict(parameters=[parameter]))},
                                   components=components), indent=2)
        for by_reference in ("schema", "parameter"):
            with self.subTest(by_reference=by_reference):
                path.write_text(contract(None, by_reference))
                base = self.graph.prepare_context()
                self.assertIn("page_size_default_unresolved", {g["code"] for g in base["graph"]["gaps"]})
                self.assertEqual(base["coverage"], "PARTIAL")
                path.write_text(contract(100, by_reference))
                result = self.graph.analyze_change(base["id"])
                self.assertEqual([d["code"] for d in result["deltas"]], ["PAGE_DEFAULT_UNRESOLVED"])
                self.assertEqual([(f["consumer"], f["code"]) for f in result["findings"]
                                  if f["consumer"] == "reporting"], [("reporting", "RECHECK_REQUIRED")])
                unchanged = self.graph.analyze_change(self.graph.prepare_context()["id"])
                self.assertEqual(unchanged["deltas"], [])

    def test_r3_shadowed_imports_never_become_resolved_edges(self):
        cases = [
            'from requests import get\ndef get(url):\n return []\nget("https://orders.test/orders")\n',
            'import requests as http\nimport unrelated as http\nhttp.get("https://orders.test/orders")\n',
            'from requests import get\nclass get:\n def __init__(self, url): pass\nget("https://orders.test/orders")\n',
            'from requests import get\nfrom other import get\nget("https://orders.test/orders")\n',
            'from requests import get\ntry:\n pass\nexcept Exception as get:\n pass\nget("https://orders.test/orders")\n',
            'from .requests import get\nget("https://orders.test/orders")\n',
            'import requests\nrequests.get = replacement\nrequests.get("https://orders.test/orders")\n',
        ]
        for source in cases:
            with self.subTest(source=source):
                self.client.write_text(source)
                context = self.graph.prepare_context()
                self.assertEqual(self.reporting(context), [])
                self.assertTrue(any(g.get("evidence", {}).get("source_id") in {
                    s["id"] for s in context["sources"].values() if s["repository"] == "reporting"
                } for g in context["graph"]["gaps"]))

    def test_r3_aliases_and_unshadowed_constants_still_work(self):
        self.client.write_text('from requests import get as fetch\nBASE="https://orders.test"\nfetch(BASE+"/orders")\n')
        self.assertEqual(len(self.reporting(self.graph.prepare_context())), 1)

    def test_extractor_upgrade_invalidates_prior_basis(self):
        with patch("agent_graph.sources.PROFILE", "http-requests-1"):
            previous = self.graph.prepare_context()
        self.assertEqual(self.graph.freshness(previous)["status"], "STALE")

    def test_r4_none_or_empty_values_use_default(self):
        for params in ['{"page_size": None}', '{"page_size": []}', '{"page_size": [None]}']:
            with self.subTest(params=params):
                self.client.write_text('import requests\nrequests.get("https://orders.test/orders", params=' + params + ')\n')
                context = self.graph.prepare_context()
                self.assertEqual(self.reporting(context)[0]["usage"], "SINGLE_REQUEST_OBSERVED")
        base = self.graph.prepare_context()
        self.limit()
        result = self.graph.analyze_change(base["id"])
        self.assertTrue(any(f["consumer"] == "reporting" and f["code"] == "POSSIBLE_TRUNCATION" for f in result["findings"]))

    def test_r4_get_positional_params_and_post_body_are_distinct(self):
        self.client.write_text('import requests\nrequests.get("https://orders.test/orders", {"page_size": 500})\n')
        base = self.graph.prepare_context()
        self.assertEqual(self.reporting(base)[0]["usage"], "EXPLICIT_PAGE_SIZE")
        self.limit()
        result = self.graph.analyze_change(base["id"])
        self.assertFalse(any(f["consumer"] == "reporting" and f["code"] == "POSSIBLE_TRUNCATION" for f in result["findings"]))
        self.client.write_text('import requests\nrequests.post("https://orders.test/orders", {"page_size": 500})\n')
        p = self.root/"corpus/orders/api.py"
        p.write_text(p.read_text().replace('@app.get(', '@app.post('))
        self.assertEqual(self.reporting(self.graph.prepare_context())[0]["usage"], "SINGLE_REQUEST_OBSERVED")

    def test_r4_dynamic_values_and_duplicate_bindings_are_unknown(self):
        args = ['params={"page_size": value}', 'params={"cursor": cursor}',
                '{"page_size": 500}, params={"page_size": 10}',
                'params={**extra}', 'params="page_size=500"']
        for arg in args:
            with self.subTest(arg=arg):
                self.client.write_text('import requests\nrequests.get("https://orders.test/orders", ' + arg + ')\n')
                context = self.graph.prepare_context()
                self.assertEqual(self.reporting(context)[0]["usage"], "UNKNOWN_USAGE")
                self.assertIn("dynamic_parameters", {g["code"] for g in context["graph"]["gaps"]})
