"""OpenAPI page_size default behind $ref: does analyze_change notice a change?

Runs the real discovery + Graph.analyze_change on an in-memory-like temp corpus.
usage: repro_openapi_ref.py   (core at ./core/src)
"""
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "core" / "src"))
sys.path.insert(0, str(HERE))
import bench_shim  # noqa: E402,F401
from agent_graph.contracts import Policy  # noqa: E402
from agent_graph.engine import Graph  # noqa: E402
from agent_graph.store import Store  # noqa: E402

CONSUMER = '''import requests

def all_orders():
    return requests.get("http://orders:8000/orders").json()["items"]
'''


def spec(variant, default):
    if variant == "schema_ref":
        param = {"name": "page_size", "in": "query", "schema": {"$ref": "#/components/schemas/PageSize"}}
        components = {"schemas": {"PageSize": {"type": "integer", "default": default}}}
    elif variant == "parameter_ref":
        param = {"$ref": "#/components/parameters/PageSize"}
        components = {"parameters": {"PageSize": {"name": "page_size", "in": "query",
                                                   "schema": {"type": "integer", "default": default}}}}
    else:  # literal, the supported control
        param = {"name": "page_size", "in": "query", "schema": {"type": "integer", "default": default}}
        components = {}
    return json.dumps({"openapi": "3.1.0", "info": {"title": "Orders", "version": "1"},
                       "paths": {"/orders": {"get": {"parameters": [param]}}},
                       "components": components}, indent=2)


def run(variant):
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "orders").mkdir()
        (tmp / "reporting").mkdir()
        (tmp / "orders" / "openapi.json").write_text(spec(variant, None))
        (tmp / "reporting" / "client.py").write_text(CONSUMER)
        policy = Policy.model_validate(dict(
            installation_id="r", environment="r", subject="r",
            capabilities=["read_context", "maintain"],
            repositories=[dict(id="orders", service="Orders", root=str(tmp / "orders"), revision="1"),
                          dict(id="reporting", service="Reporting", root=str(tmp / "reporting"), revision="1")],
            addresses=[dict(service="Orders", base_url="http://orders:8000")]))
        store = Store(tmp / "state")
        g = Graph(policy, store)
        base = g.prepare_context("t")
        (tmp / "orders" / "openapi.json").write_text(spec(variant, 100))
        a = g.analyze_change(base["id"])
        store.close()
        print(f"{variant:14} deltas={[d['code'] for d in a['deltas']]} "
              f"findings={[(f['consumer'], f['code']) for f in a['findings']]} "
              f"gaps={sorted({x['code'] for x in a['gaps']})} unknowns={bool(a['unknowns'])}")


for v in ("literal", "schema_ref", "parameter_ref"):
    run(v)
