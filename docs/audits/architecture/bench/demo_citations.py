"""How many CLI `evidence` calls does one demo analyze_change job (A->B) make?

Builds versions A and B with examples/agent_graph_demo/scenarios.py and the
policy shape of snapshots.materialize, runs the real core in-process and
counts unique citations in graph+result, which worker.py resolves one CLI
process each.
"""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "core" / "src"), str(HERE / "core"), str(HERE)]
import bench_shim  # noqa: E402,F401
from agent_graph.contracts import Policy  # noqa: E402
from agent_graph.engine import Graph  # noqa: E402
from agent_graph.store import Store  # noqa: E402
from examples.agent_graph_demo.scenarios import REPOSITORIES, REQUIREMENT, build_version  # noqa: E402


def citations(value, seen):
    if isinstance(value, dict):
        if {"source_id", "start_line", "end_line", "quote"} <= value.keys():
            seen.add((value["source_id"], value["start_line"], value["end_line"]))
        else:
            for v in value.values():
                citations(v, seen)
    elif isinstance(value, list):
        for v in value:
            citations(v, seen)
    return seen


with tempfile.TemporaryDirectory() as tmp:
    work = Path(tmp) / "work"
    build_version(work, "A")
    policy = Policy.model_validate(dict(
        installation_id="http-demo", environment="s", subject="demo-operator",
        capabilities=["read_context", "maintain", "propose", "correct", "report_check"],
        repositories=[dict(id=r, service=s, root=str(work / r), revision="r") for r, s in REPOSITORIES.items()],
        addresses=[dict(service="Orders", base_url="http://orders:8000"),
                   dict(service="Status", base_url="http://status:8000")],
        requirements=[dict(id="reporting-complete", repository="reporting", path="requirement.md",
                           sha256=hashlib.sha256(REQUIREMENT.encode()).hexdigest(), issuer="demo-owner",
                           service="Orders", path_template="/orders", consumer="Reporting",
                           predicate="complete_collection")]))
    store = Store(Path(tmp) / "state")
    g = Graph(policy, store)
    a = g.prepare_context("demo")
    graph_a = g.dependencies(a["id"])
    build_version(work, "B")
    result = g.analyze_change(a["id"])
    graph_b = g.dependencies(result["context_used_id"])
    print(json.dumps(dict(
        files=len(a["inventory"]), dependencies=len(a["graph"]["dependencies"]), gaps=len(a["graph"]["gaps"]),
        gap_codes=sorted({x["code"] for x in a["graph"]["gaps"]}),
        prepare_job_evidence_calls=len(citations(graph_a, set())),
        analyze_job_evidence_calls=len(citations([graph_b, result], set())),
        findings=[(f["consumer"], f["code"]) for f in result["findings"]])))
    store.close()
