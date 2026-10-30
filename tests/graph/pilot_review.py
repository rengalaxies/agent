"""Author fixture; expectations are separate and never become extractor input."""
import argparse
import contextlib
import json
import os
from pathlib import Path
import socket
import threading
import time
from agent_graph.contracts import Policy
from agent_graph.engine import Graph
from agent_graph.store import Store

PROVIDER = '''from fastapi import FastAPI
app = FastAPI()
@app.get("/shipments")
def listing(page_size: int = 60):
    return list(range(1, 7))[:page_size]
@app.post("/shipments")
def upload():
    return {"accepted": True}
'''
REMOTE = '''from fastapi import FastAPI
app = FastAPI()
@app.get("/shipments")
def listing():
    return [99]
'''

def port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]

@contextlib.contextmanager
def servers(source, ports, calls):
    from fastapi import FastAPI, Request
    import uvicorn
    running, threads = [], []
    try:
        for name, number in zip(("warehouse", "remote"), ports):
            ns = {}
            exec(compile(source[name], name + "/app.py", "exec"), ns)
            app = FastAPI()
            app.mount("/edge/v1", ns["app"])
            async def observe(request: Request, call_next):
                response = await call_next(request)
                calls.append(dict(method=request.method, path=request.url.path,
                                  port=request.url.port, status=response.status_code))
                return response
            app.middleware("http")(observe)
            server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=number, log_level="error"))
            thread = threading.Thread(target=server.run, daemon=True)
            thread.start()
            running.append(server)
            threads.append(thread)
            deadline = time.monotonic() + 5
            while not server.started:
                if not thread.is_alive() or time.monotonic() > deadline:
                    raise RuntimeError("fixture_server_failed")
                time.sleep(.02)
        yield
    finally:
        for server in running:
            server.should_exit = True
        for thread in threads:
            thread.join(timeout=5)

def execute(source):
    result = {}
    for name in ("reader", "writer", "remote_reader", "wrong_prefix", "wrong_method", "wrapper"):
        ns = {}
        exec(compile(source[name], name + "/app.py", "exec"), ns)
        response = ns["run"]()
        result["remote" if name == "remote_reader" else name] = (
            response.status_code if response.status_code >= 400 else response.json())
    return result

def review(root, *, runtime=False):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    expected = json.loads(Path(__file__).with_name("pilot_expectations.json").read_text())
    (root / "expectations-before.json").write_text(json.dumps(expected, indent=2))
    ports = [port(), port()]
    urls = [f"http://127.0.0.1:{p}/edge/v1" for p in ports]
    source = {"warehouse": PROVIDER, "remote": REMOTE}
    for name, method, base in (("reader", "get", urls[0]), ("writer", "post", urls[0]),
                              ("remote_reader", "get", urls[1]), ("wrong_method", "delete", urls[0]),
                              ("wrong_prefix", "get", urls[0].replace("v1", "v2"))):
        source[name] = (f'import requests\nBASE = "{base}"\ndef run():\n'
                        f'    return requests.{method}(BASE + "/shipments", timeout=3)\n')
    source["wrapper"] = ('import requests\ndef transport(target):\n    return requests.get(target, timeout=3)\n'
                         f'def run():\n    return transport("{urls[0]}/shipments")\n')
    source["text"] = 'DESCRIPTION = "@app.get(/ghost) is ordinary text, not a declaration"\n'
    for name, content in source.items():
        directory = root / "repos" / name
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "app.py").write_text(content)
    policy = Policy.model_validate(dict(installation_id="author-review", environment="local", subject="author",
        capabilities=["read_context", "maintain", "propose"],
        repositories=[dict(id=n, service=n, root=str(root / "repos" / n), revision="author-fixture") for n in source],
        addresses=[dict(service=s, base_url=u) for s, u in zip(("warehouse", "remote"), urls)]))
    store = Store(root / "state")
    try:
        graph = Graph(policy, store)
        base = graph.prepare_context()
        ops = {o["id"]: o for o in base["graph"]["operations"]}
        structural = {d["consumer"]: [ops[d["operation_id"]][k] for k in ("service", "method", "path")]
                      for d in base["graph"]["dependencies"]}
        assert structural == expected["structural"], structural
        assert not any(o["path"] == "/ghost" for o in ops.values())
        before, after, calls = None, None, []
        if runtime:
            with servers(source, ports, calls):
                before = execute(source)
            assert before == expected["runtime"]
        limited = source["warehouse"].replace("page_size: int = 60", "page_size: int = 2")
        (root / "repos/warehouse/app.py").write_text(limited)
        analysis = graph.analyze_change(base["id"])
        assert sorted({f["consumer"] for f in analysis["findings"]}) == expected["changed_consumers"]
        assert all(not f["test_executed"] for f in analysis["findings"])
        if runtime:
            with servers({**source, "warehouse": limited}, ports, calls):
                after = execute(source)
            assert {k: after[k] for k in expected["limited"]} == expected["limited"]
            assert all(after[k] == before[k] for k in ("writer", "remote", "wrong_prefix", "wrong_method"))
        extra = root / "repos/text/extra.py"
        extra.write_text(source["reader"])
        added = graph.prepare_context()
        assert "text" in {d["consumer"] for d in added["graph"]["dependencies"]}
        extra.unlink()
        removed = graph.prepare_context()
        assert "text" not in {d["consumer"] for d in removed["graph"]["dependencies"]}
        evidence = next(s for s in removed["sources"].values() if s["repository"] == "reader")
        proposal = graph.propose(removed["id"], dict(key="note", kind="hypothesis", statement="Inspect this call",
            citations=[dict(source_id=evidence["id"], start_line=1, end_line=1, quote="import requests")]))
        path = root / "repos/reader/app.py"
        path.write_text(path.read_text() + "\n# cited source changed\n")
        current = graph.prepare_context()
        assert graph.proposals(current)[0]["status"] == "STALE"
        assert graph.proposals(current)[0]["id"] == proposal["id"]
        path.parent.rename(path.parent.with_name("reader-unavailable"))
        partial = graph.prepare_context()
        assert partial["coverage"] == "PARTIAL" and partial["graph"]["gaps"]
        return dict(level="CI" if os.environ.get("GITHUB_ACTIONS") == "true" else "LOCAL", status="PASS", author_written=True,
                    independent_held_out=False, structural=structural, gaps=base["graph"]["gaps"],
                    findings=analysis["findings"], before=before, limited=after, actual_http_requests=calls,
                    lifecycle=dict(add_remove="PASS", cited_source_stale="PASS", unavailable="PARTIAL"),
                    unknown_meaning=expected["notes"])
    finally:
        store.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--runtime", action="store_true")
    args = parser.parse_args()
    result = review(args.output, runtime=args.runtime)
    (args.output / "observations.json").write_text(json.dumps(result, indent=2) + "\n")
    print(result["status"])
