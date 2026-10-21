"""Reproducible cold -> diff -> consumer repair -> new callsite loop; no inference."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from fixture import create_fixture
from agent_graph.engine import Graph
from agent_graph.store import Store


def demo(directory):
    policy = create_fixture(directory)
    graph = Graph(policy, Store(Path(directory) / "state"))
    try:
        base = graph.prepare_context("Limit Orders default page size to 100")
        root = Path(directory) / "corpus"
        file = root / "orders/api.py"
        file.write_text(file.read_text().replace("page_size: int | None = None", "page_size: int | None = 100"))
        first = graph.analyze_change(base["id"])
        stale = graph.freshness(base)
        (root / "reporting/client.py").write_text((root / "export/client.py").read_text())
        repaired = graph.analyze_change(base["id"])
        (root / "health/new_client.py").write_text('import requests\nrequests.get("https://orders.test/orders")\n')
        expanded = graph.analyze_change(base["id"])
        return dict(schema="graph-demo-1", synthetic=True, real_model_run=False,
                    base_consumers=sorted(d["consumer"] for d in base["graph"]["dependencies"]),
                    first_findings=first["findings"], old_context_freshness=stale,
                    repaired_findings=repaired["findings"], expanded_findings=expanded["findings"],
                    contexts_differ=len({base["id"], first["context_used_id"], repaired["context_used_id"], expanded["context_used_id"]}) == 4,
                    baseline_comparison="NOT_RUN", human_time="NOT_MEASURED", paid_inference_cost=0)
    finally:
        graph.store.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output")
    args = p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        report = demo(tmp)
    text = json.dumps(report, indent=2, ensure_ascii=False)
    if args.output:
        Path(args.output).write_text(text + "\n")
    print(text)
