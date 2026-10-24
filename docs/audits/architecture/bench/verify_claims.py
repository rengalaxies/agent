"""Check lifecycle claims on the real core: second repo, second user, unrelated edit.

usage: verify_claims.py REPO_ROOT
"""
import json
import os
import sys
import tempfile
from pathlib import Path

repo = Path(sys.argv[1]).resolve()
sys.path[:0] = [str(repo / "src"), str(repo / "examples" / "agent_graph")]
sys.path.append(str(Path(__file__).resolve().parent))
import bench_shim  # noqa: E402,F401
from agent_graph.contracts import GraphError, Policy  # noqa: E402
from agent_graph.engine import Graph  # noqa: E402
from agent_graph.store import Store  # noqa: E402
from fixture import create_fixture  # noqa: E402


def correction(graph, context):
    dep = next(d for d in context["graph"]["dependencies"] if d["consumer"] == "reporting")
    return graph.propose(context["id"], dict(key="reporting-usage", kind="human_correction",
                                             statement="Reporting needs every order", citations=dep["evidence"]))


with tempfile.TemporaryDirectory() as tmp:
    root = Path(tmp)
    policy = create_fixture(root)
    store = Store(root / "state")
    g = Graph(policy, store)
    ctx = g.prepare_context()
    p = correction(g, ctx)
    print("1 correction stored:", p["trust"], "| visible:", len(g.dependencies(ctx["id"])["proposals"]))

    # Regular change: an unrelated file in another repository changes by one line.
    other = root / "corpus/health/client.py"
    other.write_text(other.read_text() + "\n# unrelated edit\n")
    ctx2 = g.prepare_context()
    rows = g.dependencies(ctx2["id"])["proposals"]
    cited = {c["source_id"] for c in p["proposal"]["citations"]}
    print("2 after unrelated edit in health/: correction status =", [r["status"] for r in rows],
          "| cited file unchanged:", cited <= set(ctx2["sources"]))

    # Second user in the same view prepares a context: the first user's context is superseded.
    try:
        correction(g, ctx)
        print("3 propose on previous context: accepted")
    except GraphError as exc:
        print("3 propose on previous context after another prepare_context:", exc.code)

    # Second repository: append one repository to the policy.
    extra = root / "corpus/billing"
    extra.mkdir()
    (extra / "client.py").write_text("import requests\n")
    data = policy.model_dump()
    data["repositories"].append(dict(id="billing", service="billing", root=str(extra), revision="r1",
                                     include=["*.py"]))
    g2 = Graph(Policy.model_validate(data), store)
    ctx3 = g2.prepare_context()
    print("4 after adding a repository: view changed =", g2.view != g.view,
          "| proposals visible =", len(g2.dependencies(ctx3["id"])["proposals"]),
          "| previous context readable =", end=" ")
    try:
        g2.context(ctx2["id"])
        print(True)
    except GraphError as exc:
        print(exc.code)
    store.close()
