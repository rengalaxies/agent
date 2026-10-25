"""Measure a job with many citations: one evidence_batch process versus one process per citation.

Runs the real CLI (`python -m agent_graph`) as the demo worker does: prepare_context,
analyze_change after a page-size change, dependencies, then citation validation.
Wall time is measured per step; peak RSS per process comes from os.wait4, so it is
reported on Linux only (None elsewhere). Nothing is extrapolated: the per-citation
mode runs every citation it reports. No network, model or secret is used.

Usage: python tests/graph/bench_citations.py --output work/citation-measurement.json
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
PROVIDER = '''from fastapi import FastAPI

app = FastAPI()


@app.get("/orders")
def list_orders(day: str, page_size: int | None = {default}):
    return {{"items": store.read(day, page_size)}}
'''
CONSUMER = '''import requests

BASE_URL = "https://orders.test"


def load_{n}(day):
    response = requests.get(BASE_URL + "/orders", params={{"day": day}}, timeout=10)
    return response.json()["items"]
'''


def corpus(root: Path, repositories: int, files: int):
    (root / "orders").mkdir(parents=True)
    (root / "orders" / "api.py").write_text(PROVIDER.format(default=100))
    repos = [dict(id="orders", service="orders", root=str(root / "orders"), revision="bench")]
    for r in range(repositories):
        folder = root / f"consumer{r}"
        folder.mkdir()
        for f in range(files):
            (folder / f"client_{f}.py").write_text(CONSUMER.format(n=f))
        repos.append(dict(id=f"consumer{r}", service=f"consumer{r}", root=str(folder), revision="bench"))
    policy = dict(installation_id="bench", environment="ci", subject="bench",
                  capabilities=["read_context", "maintain"], repositories=repos,
                  addresses=[dict(service="orders", base_url="https://orders.test")],
                  limits=dict(max_files=repositories * files + 8, scan_seconds=120))
    (root / "policy.json").write_text(json.dumps(policy))
    return root / "policy.json"


def run(policy, state, command, *extra, message=None, work=None):
    args = [sys.executable, "-m", "agent_graph", "--policy", str(policy), "--state", str(state), command, *extra]
    if message is not None:
        path = Path(work) / "message.json"
        path.write_text(json.dumps(message))
        args += ["--input", str(path)]
    env = {"PATH": os.defpath, "PYTHONPATH": str(ROOT / "src"), "PYTHONDONTWRITEBYTECODE": "1"}
    if os.name == "nt":
        env["SYSTEMROOT"] = os.environ.get("SYSTEMROOT", r"C:\Windows")
    started = time.perf_counter()
    proc = subprocess.Popen(args, env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    output = proc.stdout.read()
    proc.stdout.close()
    rss = None
    if hasattr(os, "wait4"):
        _, status, usage = os.wait4(proc.pid, 0)
        proc.returncode = os.waitstatus_to_exitcode(status)
        rss = usage.ru_maxrss  # kilobytes on Linux
    else:
        proc.wait()
    seconds = time.perf_counter() - started
    value = json.loads(output)
    if proc.returncode or value.get("status") == "ERROR":
        raise SystemExit(f"{command} failed: {value.get('code')}")
    return value, dict(seconds=round(seconds, 3), max_rss_kb=rss)


def citations(value, found):
    if isinstance(value, dict):
        if {"source_id", "start_line", "end_line", "quote"} <= value.keys():
            found.setdefault(json.dumps([value[k] for k in ("source_id", "start_line", "end_line")]),
                             {k: value[k] for k in ("source_id", "start_line", "end_line", "quote")})
        else:
            for child in value.values():
                citations(child, found)
    elif isinstance(value, list):
        for child in value:
            citations(child, found)
    return found


def measure(repositories, files):
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        policy = corpus(root / "corpus", repositories, files)
        state = root / "state"
        steps = {}
        base, steps["prepare_context"] = run(policy, state, "prepare_context")
        (root / "corpus" / "orders" / "api.py").write_text(PROVIDER.format(default=20))
        analysis, steps["analyze_change"] = run(policy, state, "analyze_change", "--context", base["context_id"])
        graph, steps["dependencies"] = run(policy, state, "dependencies", "--context", analysis["context_used_id"])
        found = list(citations([graph, analysis], {}).values())
        contexts = [analysis["context_used_id"], analysis["base_context_id"]]
        batch, steps["evidence_batch"] = run(policy, state, "evidence_batch", work=root, message=dict(
            items=[dict(contexts=contexts, citation=c) for c in found]))
        assert all("evidence" in r for r in batch["results"]), "batch rejected a citation"
        per_citation = dict(processes=0, seconds=0.0, max_rss_kb=None)
        for citation in found:
            context = next(r["context_id"] for r in batch["results"] if r["evidence"]["quote"] == citation["quote"])
            _, measured = run(policy, state, "evidence", "--context", context, message=citation, work=root)
            per_citation["processes"] += 1
            per_citation["seconds"] += measured["seconds"]
            if measured["max_rss_kb"] is not None:
                per_citation["max_rss_kb"] = max(per_citation["max_rss_kb"] or 0, measured["max_rss_kb"])
        per_citation["seconds"] = round(per_citation["seconds"], 3)
        return dict(consumer_files=repositories * files, findings=len(analysis["findings"]),
                    unique_citations=len(found), steps=steps,
                    batch_mode=dict(core_processes=4, seconds=round(sum(s["seconds"] for s in steps.values()), 3)),
                    per_citation_mode=dict(core_processes=3 + per_citation["processes"],
                                           evidence_seconds=per_citation["seconds"],
                                           evidence_max_rss_kb=per_citation["max_rss_kb"],
                                           seconds=round(per_citation["seconds"] + sum(
                                               s["seconds"] for k, s in steps.items() if k != "evidence_batch"), 3)))


def summary(report) -> str:
    """One ::notice line with the numbers, readable from public check-run annotations."""
    r = report["result"]
    steps = ", ".join(f"{k} {v['seconds']}s/{v['max_rss_kb']}KiB" for k, v in r["steps"].items())
    text = (f"{report['platform']}, Python {report['python']}, {report['cpus']} CPU: {r['consumer_files']} consumer files, "
            f"{r['unique_citations']} citations. Batch: {r['batch_mode']['core_processes']} processes, "
            f"{r['batch_mode']['seconds']}s. Per citation: {r['per_citation_mode']['core_processes']} processes, "
            f"{r['per_citation_mode']['seconds']}s, evidence peak {r['per_citation_mode']['evidence_max_rss_kb']}KiB. "
            f"Steps: {steps}.")
    return "::notice title=citation measurement::" + text.replace("%", "%25").replace("\n", "%0A")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--output", type=Path)
    p.add_argument("--summarize", type=Path, help="print the ::notice line of a saved report and exit")
    p.add_argument("--repositories", type=int, default=8)
    p.add_argument("--files", type=int, default=25)
    a = p.parse_args(argv)
    if a.summarize:
        print(summary(json.loads(a.summarize.read_text())))
        return
    if a.output is None:
        p.error("--output is required")
    report = dict(schema="citation-measurement-1", measured_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                  platform=platform.platform(), python=platform.python_version(), cpus=os.cpu_count(),
                  memory_source="os.wait4 ru_maxrss (KiB)" if hasattr(os, "wait4") else "unavailable on this OS",
                  result=measure(a.repositories, a.files))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["result"], indent=2))


if __name__ == "__main__":
    main()
