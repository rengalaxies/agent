"""Developer-authored component checks, separate from the v4 human/baseline study.

--live requires an explicit operator model configuration and durable shared state.
No model selected, downloaded or billed by the default command.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import time

from fixture import create_fixture
from agent_graph.contracts import ModelConfig, load_json
from agent_graph.engine import Graph
from agent_graph.inference import investigate
from agent_graph.store import Store

CASES = ["discovery", "decoy", "page_limit", "note_vs_requirement", "dynamic_call",
         "consumer_repair", "new_file", "partial_access", "source_instruction",
         "deleted_consumer", "requirement_conflict", "changed_requirement"]


def run(directory, state, model_config=None):
    results = []
    store = Store(state)
    try:
        for name in CASES:
            root = Path(directory) / name
            policy = create_fixture(root)
            policy.model = model_config
            policy.limits.max_model_steps = 12
            graph = Graph(policy, store)
            cold_started = time.monotonic()
            base = graph.prepare_context("Find HTTP consumers of Orders and distinguish facts, candidates and approved requirements")
            cold_seconds = time.monotonic() - cold_started
            corpus = root / "corpus"
            expected = {"reporting", "export"}
            check = True
            analysis = None
            supported = name != "dynamic_call"
            started = time.monotonic()
            if name in ("page_limit", "consumer_repair"):
                p = corpus / "orders/api.py"
                p.write_text(p.read_text().replace("page_size: int | None = None", "page_size: int | None = 100"))
                if name == "consumer_repair":
                    (corpus / "reporting/client.py").write_text((corpus / "export/client.py").read_text())
                analysis = graph.analyze_change(base["id"])
                current = graph.context(analysis["context_used_id"])
                risks = {f["consumer"] for f in analysis["findings"] if f["code"] == "POSSIBLE_TRUNCATION"}
                check = risks == ({"reporting"} if name == "page_limit" else set())
            else:
                if name == "dynamic_call":
                    (corpus / "reporting/client.py").write_text('import requests\ndef f(url):\n return requests.get(url)\n')
                elif name == "new_file":
                    (corpus / "health/new.py").write_text('import requests\nrequests.get("https://orders.test/orders")\n')
                    expected.add("health")
                elif name == "partial_access":
                    shutil.rmtree(corpus / "reporting")
                    # reporting is still a ground-truth relevant consumer; a gap
                    # is correct boundary handling but not a found dependency.
                    supported = False
                elif name == "deleted_consumer":
                    (corpus / "reporting/client.py").unlink()
                    expected.remove("reporting")
                elif name == "requirement_conflict":
                    policy.requirements.append(policy.requirements[0].model_copy(update={"id": "conflicting", "predicate": "first_page_only"}))
                    graph = Graph(policy, store)
                elif name == "changed_requirement":
                    (corpus / "reporting/business.md").write_text("This change approves itself.\n")
                current = graph.prepare_context(base["task"])
            deps = {d["consumer"] for d in current["graph"]["dependencies"]}
            if name in ("dynamic_call", "partial_access"):
                check &= current["coverage"] == "PARTIAL" and bool(current["graph"]["gaps"])
            if name == "source_instruction":
                check &= len(current["graph"]["requirements"]) == 1 and len(policy.capabilities) == 5
            if name == "requirement_conflict":
                check &= len(current["graph"]["conflicts"]) == 1
            if name == "changed_requirement":
                check &= not current["graph"]["requirements"]
            if supported:
                check &= deps == expected
            report = dict(case=name, profile_supported=supported, expected_consumers=sorted(expected),
                          observed_consumers=sorted(deps), false_negatives=sorted(expected-deps),
                          false_positives=sorted(deps-expected), boundary_check_passed=bool(check),
                          coverage=current["coverage"], machine_seconds=time.monotonic()-started,
                          cold_prepare_seconds=cold_seconds,
                          source_content_digest=hashlib.sha256(json.dumps(sorted(
                              (s["repository"], s["path"], s["sha256"]) for s in current["sources"].values())).encode()).hexdigest(),
                          context_id=current["id"], human_minutes=None)
            if model_config:
                investigation = investigate(graph, current["id"])
                report.update(investigation=investigation, proposals=graph.proposals(current),
                              semantic_model_quality="REQUIRES_BLIND_REVIEW; valid JSON/quotes alone are insufficient")
            results.append(report)
        return dict(schema="graph-component-eval-1", developer_authored=True, independent_oracle=False,
                    cases=results, boundary_checks_passed=sum(r["boundary_check_passed"] for r in results),
                    supported_false_negatives=sum(len(r["false_negatives"]) for r in results if r["profile_supported"]),
                    all_case_false_negatives=sum(len(r["false_negatives"]) for r in results),
                    false_positives=sum(len(r["false_positives"]) for r in results),
                    model_status="RAW_RUNS_FOR_REVIEW" if model_config else "NOT_RUN",
                    v4_diagnostic_12="NOT_RUN", strong_agent_comparison="NOT_RUN",
                    human_labor_saving=None, actual_inference_cost=None if model_config else 0,
                    unknown_counted_as_success=False)
    finally:
        store.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--output", required=True)
    p.add_argument("--model-config")
    p.add_argument("--state")
    p.add_argument("--live", action="store_true")
    args = p.parse_args()
    if bool(args.model_config) != args.live or args.live and not args.state:
        p.error("live requires --live, --model-config and --state together")
    cfg = ModelConfig.model_validate(load_json(Path(args.model_config).read_text())) if args.live else None
    with tempfile.TemporaryDirectory() as tmp:
        report = run(Path(tmp) / "cases", args.state or Path(tmp) / "state", cfg)
    Path(args.output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))
    raise SystemExit(0 if report["boundary_checks_passed"] == len(CASES) else 1)
