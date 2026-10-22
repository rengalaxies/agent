"""Repro: non-literal page_size default change is invisible to analyze_change.

Runs the pinned core logic (discovery + Graph.analyze_change) on an in-memory
corpus. fcntl and the filesystem collector are stubbed because this host is
Windows; extraction and delta logic are the real code.
Usage, from the repository root: python docs/audits/pr-integration/repro_page_default.py .
"""
import hashlib
import sys
import types

sys.modules.setdefault("fcntl", types.ModuleType("fcntl"))
sys.path.insert(0, sys.argv[1] + "/src")

from agent_graph import engine  # noqa: E402
from agent_graph.contracts import Policy, digest  # noqa: E402

CONSUMER = 'import requests\n\n\ndef run():\n    return requests.get("http://orders:8000/orders", timeout=5).json()\n'
VARIANTS = {
    "literal": ("page_size: int | None = None", "page_size: int | None = 100"),
    "fastapi_query": ("page_size: int | None = Query(None)", "page_size: int | None = Query(100)"),
    "module_constant": ("page_size: int | None = DEFAULT", "page_size: int | None = DEFAULT"),
}
PROVIDER = ("from fastapi import FastAPI, Query\n\nDEFAULT = {default}\napp = FastAPI()\n\n\n"
            "@app.get(\"/orders\")\ndef orders({param}):\n    return {{}}\n")


def corpus(param, default="None"):
    files = {("orders", "app.py"): PROVIDER.format(param=param, default=default),
             ("reporting", "client.py"): CONSUMER}
    sources, inventory = {}, []
    for (repo, path), text in files.items():
        sha = hashlib.sha256(text.encode()).hexdigest()
        sid = digest(["i", "e", repo, "r", path, sha])
        sources[sid] = dict(id=sid, repository=repo, service=repo.title(), path=path,
                            revision="r", sha256=sha, text=text)
        inventory.append([repo, "r", path, sha])
    return dict(sources=sources, gaps=[], basis=digest(inventory), inventory=inventory, bytes_read=0)


class MemoryStore:
    def __init__(self):
        self.items, self.heads = {}, {}

    def head(self, view):
        return self.heads.get(view, (0, None))

    def save(self, view, kind, artifact, expected_generation=None):
        artifact = {**artifact, "id": digest([view, kind, artifact])}
        self.items[artifact["id"]] = artifact
        if expected_generation is not None:
            self.heads[view] = (expected_generation + 1, artifact["id"])
        return artifact

    def get(self, view, id, kind="context"):
        return self.items[id]

    def proposals(self, view):
        return []


policy = Policy.model_validate(dict(
    installation_id="i", environment="e", subject="s",
    capabilities=["read_context", "maintain", "propose"],
    repositories=[dict(id="orders", service="Orders", root="/x/orders", revision="r"),
                  dict(id="reporting", service="Reporting", root="/x/reporting", revision="r")],
    addresses=[dict(service="Orders", base_url="http://orders:8000")]))

for name, (before, after) in VARIANTS.items():
    current = {"c": corpus(before, "None")}
    engine.collect = lambda _policy: current["c"]
    graph = engine.Graph(policy, MemoryStore())
    base = graph.prepare_context()
    current["c"] = corpus(after, "100") if name == "module_constant" else corpus(after)
    result = graph.analyze_change(base["id"])
    op = base["graph"]["operations"][0]
    print(f"{name:16} default_known={op['default_known']!s:5} coverage={result['coverage']:24} "
          f"gaps={[g['code'] for g in result['gaps']]} deltas={[d['code'] for d in result['deltas']]} "
          f"findings={[(f['consumer'], f['code']) for f in result['findings']]}")
