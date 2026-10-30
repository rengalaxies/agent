"""Author cases: response type, path template, compound intent and mutable decorators.

Expected data is read only by this verifier, never supplied to Policy/Graph.
"""
import argparse
from contextlib import contextmanager
import json
import os
from pathlib import Path
import threading
import time

from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store
from agent_service.intent import match_intent

PROVIDER = '''from fastapi import FastAPI
api = FastAPI()
@api.get("/records/{record_id}")
def read(record_id: int):
    return {"state": "open"}
@api.post("/records/{record_id}")
def write(record_id: int):
    return {"accepted": True}
'''
MUTATED = '''from fastapi import FastAPI
api = FastAPI()
setattr(api, "get", lambda path: (lambda fn: fn))
@api.get("/records/{record_id}")
def read(record_id: int):
    return {"state": "ghost"}
'''


@contextmanager
def server(source, calls):
    from fastapi import FastAPI, Request
    import uvicorn
    app = FastAPI()
    for prefix, text in (("/edge/catalog/v3", source),
                         ("/edge/admin/v3", PROVIDER.replace('"open"', '"admin"'))):
        namespace = {}
        exec(compile(text, prefix + "/api.py", "exec"), namespace)
        app.mount(prefix, namespace["api"])

    @app.middleware("http")
    async def observe(request: Request, call_next):
        response = await call_next(request)
        calls.append(dict(method=request.method, path=request.url.path, port=request.url.port,
                          address=request.url.hostname, status=response.status_code))
        return response

    running = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="error"))
    thread = threading.Thread(target=running.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not running.started:
            if time.monotonic() > deadline or not thread.is_alive():
                raise RuntimeError("author_fixture_start_failed")
            time.sleep(.01)
        yield f"http://127.0.0.1:{running.servers[0].sockets[0].getsockname()[1]}"
    finally:
        running.should_exit = True
        thread.join(timeout=10)


def callers(origin):
    def direct(method, prefix):
        return (f'from requests import request as send\nBASE = "{origin}{prefix}"\n'
                f'def run():\n    return send("{method}", BASE + "/records/7", timeout=3)\n')
    return dict(display=direct("GET", "/edge/catalog/v3"), submit=direct("POST", "/edge/catalog/v3"),
                admin_display=direct("GET", "/edge/admin/v3"),
                wrong_prefix=direct("GET", "/edge/catalog/v4"), wrong_method=direct("DELETE", "/edge/catalog/v3"),
                wrapper=('import requests\ndef transport(url):\n    return requests.get(url, timeout=3)\n'
                         f'def run():\n    return transport("{origin}/edge/catalog/v3/records/7")\n'))


def execute(source):
    result = {}
    for name, text in source.items():
        ns = {}
        exec(compile(text, name + "/client.py", "exec"), ns)
        response = ns["run"]()
        result[name] = response.json() if response.status_code == 200 else response.status_code
    return result


def run(root, *, runtime=False):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    expected = json.loads(Path(__file__).with_name("candidate_expectations.json").read_text())
    (root / "expectations-before.json").write_text(json.dumps(expected, indent=2))
    calls, before, after = [], None, None
    if runtime:
        # Each runtime phase uses a fresh ephemeral origin; requests record the actual port.
        # Static sources below use the first configured origin, not an expected consumer map.
        with server(PROVIDER, calls) as origin:
            before = execute(callers(origin))
        with server(PROVIDER.replace('"open"', '42'), calls) as changed_origin:
            after = execute(callers(changed_origin))
        assert before == expected["before"] and after == expected["after"]
    else:
        origin = "http://127.0.0.1:19073"
    source = dict(catalog=PROVIDER, admin=PROVIDER.replace('"open"', '"admin"'), **callers(origin))
    for name, text in source.items():
        directory = root / "repos" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "app.py").write_text(text)
    policy = Policy.model_validate(dict(installation_id="candidate-author", environment="test", subject="author",
        capabilities=["read_context", "maintain", "propose"], requirements=[],
        repositories=[dict(id=n, service=n, root=str(root / "repos" / n), revision="authored") for n in source],
        addresses=[dict(service=n, base_url=origin + "/edge/" + n + "/v3") for n in ("catalog", "admin")]))
    store = Store(root / "state")
    try:
        graph = Graph(policy, store)
        base = graph.prepare_context()
        ops = {o["id"]: o for o in base["graph"]["operations"]}
        edges = {d["consumer"]: [ops[d["operation_id"]]["service"], ops[d["operation_id"]]["method"]]
                 for d in base["graph"]["dependencies"]}
        assert edges == expected["supported_edges"], edges
        intent = []
        for case in expected["intent"]:
            result = match_intent(list(ops.values()), [case["text"]])
            actual = sorted(ops[oid]["service"] + ":" + ops[oid]["method"] for oid in result.operation_ids)
            intent.append(dict(**case, actual=actual, status="PASS" if actual == case["expected"] else "FAIL"))
        path = root / "repos/catalog/app.py"
        path.write_text(PROVIDER.replace('"open"', '42'))
        analysis = graph.analyze_change(base["id"])
        assert {f["consumer"] for f in analysis["findings"]} == {"display"}
        assert all(f["test_executed"] is False and f["compatibility_confirmed"] is False
                   and f["requirement_ids"] == [] for f in analysis["findings"])
        path.write_text(MUTATED)
        mutated = graph.prepare_context()
        actual_mutated = [o["path"] for o in mutated["graph"]["operations"] if o["service"] == "catalog"]
        mutation = dict(expected=[], actual=actual_mutated, status="PASS" if not actual_mutated else "FAIL")
        # Actual FastAPI registration is a separate oracle from AST discovery, including static-only runs.
        ns = {}
        exec(compile(MUTATED, "authored_mutation.py", "exec"), ns)
        assert "/records/{record_id}" not in {r.path for r in ns["api"].routes}
        supported = set(expected["supported_edges"])
        runtime_truth = supported | set(expected["runtime_only"])
        return dict(level="CI" if os.environ.get("GITHUB_ACTIONS") == "true" else "LOCAL",
                    status="PASS" if mutation["status"] == "PASS" and all(x["status"] == "PASS" for x in intent) else "FAIL",
                    author_written=True, independent_held_out=False, edges=edges, intent=intent,
                    mutable_decorator=mutation, findings=analysis["findings"], before=before, after=after,
                    http=calls, no_approved_requirement=True,
                    quality=dict(denominator_runtime_successful_callers=len(runtime_truth),
                                 false_positives=len(set(edges) - runtime_truth),
                                 supported_false_negatives=len(supported - set(edges)),
                                 all_runtime_false_negatives=len(runtime_truth - set(edges)),
                                 unsupported_abstentions=len(set(expected["runtime_only"]) - set(edges)),
                                 provider_false_positives=len(actual_mutated)),
                    limitations="FN includes unsupported wrapper; abstentions overlap FN, not a different denominator. Wrong method/prefix are observed HTTP calls but no declared operation. No customer-completeness estimate.")
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    result = run(args.output, runtime=args.runtime)
    (args.output / "observations.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("status", "quality", "intent", "mutable_decorator")}))
