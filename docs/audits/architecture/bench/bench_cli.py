"""Subprocess (CLI) cost of the core, as the demo worker invokes it.

usage: bench_cli.py RUN_DIR GEN_ARGS_JSON [EVIDENCE_SAMPLE]
Reproduces one worker analyze_change job: CLI analyze_change, CLI dependencies,
then one CLI `evidence` call per unique citation in graph+result
(src/agent_graph_demo/worker.py). Up to EVIDENCE_SAMPLE calls are executed;
the rest are extrapolated from their median and marked as such.
"""
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
PY = sys.executable


def run(args, peak=True):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    fd, peak_file = tempfile.mkstemp()
    os.close(fd)
    env["BENCH_PEAK_FILE"] = peak_file
    s = time.perf_counter()
    p = subprocess.run([PY, str(HERE / "cli_shim.py"), *args], capture_output=True, env=env)
    wall = time.perf_counter() - s
    out = json.loads(p.stdout) if p.stdout.strip() else None
    peak_bytes = int(Path(peak_file).read_text() or 0)
    os.unlink(peak_file)
    if p.returncode:
        raise SystemExit(f"cli failed {args[4:]} -> {p.stdout[:300]!r} {p.stderr[-800:]!r}")
    return out, wall, peak_bytes


def citations(value, acc):
    keys = {"source_id", "start_line", "end_line", "quote"}
    if isinstance(value, dict):
        if keys <= value.keys():
            acc.setdefault(json.dumps({k: value[k] for k in sorted(keys)}, sort_keys=True), None)
        else:
            for v in value.values():
                citations(v, acc)
    elif isinstance(value, list):
        for v in value:
            citations(v, acc)
    return acc


def main():
    run_dir, gen = Path(sys.argv[1]), json.loads(sys.argv[2])
    sample = int(sys.argv[3]) if len(sys.argv) > 3 else 40
    policy, state = run_dir / "policy.json", run_dir / "cli-state"
    base = ["--policy", str(policy), "--state", str(state)]
    r = {}
    s = time.perf_counter(); subprocess.run([PY, "-c", "pass"]); r["python_bare"] = time.perf_counter() - s
    s = time.perf_counter(); subprocess.run([PY, "-c", "import pydantic"]); r["python_pydantic"] = time.perf_counter() - s
    subprocess.run([PY, str(HERE / "gen_corpus.py"), *gen, "--version", "A"], check=True)
    ctx, r["prepare_context_cold"], r["prepare_context_peak"] = run(base + ["prepare_context", "--task", "b"])
    _, r["dependencies"], r["dependencies_peak"] = run(base + ["dependencies", "--context", ctx["context_id"]])
    subprocess.run([PY, str(HERE / "gen_corpus.py"), *gen, "--version", "B"], check=True)
    t_job = time.perf_counter()
    result, r["analyze_change"], r["analyze_change_peak"] = run(base + ["analyze_change", "--context", ctx["context_id"]])
    graph, r["dependencies_after"], _ = run(base + ["dependencies", "--context", result["context_used_id"]])
    cites = list(citations([graph, result], {}))
    msg = run_dir / "message.json"
    times, peaks = [], []
    for c in cites[:sample]:
        msg.write_text(c)
        _, w, pk = run(base + ["evidence", "--context", graph["context_id"], "--input", str(msg)])
        times.append(w); peaks.append(pk)
    measured = time.perf_counter() - t_job
    rest = max(0, len(cites) - sample)
    r.update(unique_citations=len(cites), evidence_calls_measured=len(times),
             evidence_median=statistics.median(times) if times else 0,
             evidence_peak=max(peaks) if peaks else 0,
             job_seconds_measured=measured,
             job_seconds_extrapolated=measured + rest * (statistics.median(times) if times else 0),
             extrapolated=rest > 0, findings=len(result["findings"]), deltas=len(result["deltas"]),
             cli_stdout_bytes_dependencies=len(json.dumps(graph)),
             state_bytes=sum(p.stat().st_size for p in state.glob("*")))
    print(json.dumps({k: round(v, 4) if isinstance(v, float) else v for k, v in r.items()}))


if __name__ == "__main__":
    main()
