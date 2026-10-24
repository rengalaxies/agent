"""In-process phase timings of the unmodified core on one corpus.

usage: bench_phases.py POLICY STATE GEN_ARGS_JSON
Runs: prepare_context (cold store) -> dependencies -> evidence -> second
prepare_context (warm store) -> switch corpus to version B -> analyze_change.
Prints one JSON object. Wall time per public operation, plus cumulative time
inside collect/extract/json/sqlite measured by wrapping module functions.
"""
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "core" / "src"))
sys.path.insert(0, str(HERE))
t0 = time.perf_counter()
import bench_shim  # noqa: E402,F401
from agent_graph import contracts, engine, store as store_mod  # noqa: E402
from agent_graph.contracts import Policy, load_json  # noqa: E402
import_seconds = time.perf_counter() - t0

acc = defaultdict(float)
calls = defaultdict(int)
each = {}


def wrap(module, name, label):
    fn = getattr(module, name)

    def timed(*a, **k):
        s = time.perf_counter()
        try:
            return fn(*a, **k)
        finally:
            acc[label] += time.perf_counter() - s
            calls[label] += 1
            each.setdefault(label, []).append(round(time.perf_counter() - s, 4))
    setattr(module, name, timed)


wrap(engine, "collect", "collect")
wrap(engine, "extract", "extract")
wrap(store_mod, "canonical", "json_dump")
wrap(store_mod, "load_json", "json_load")
wrap(store_mod, "digest", "digest")
orig_exec = None


class TimedDB:
    def __init__(self, db):
        self.db = db

    def execute(self, *a):
        s = time.perf_counter()
        try:
            return self.db.execute(*a)
        finally:
            acc["sqlite"] += time.perf_counter() - s

    def __getattr__(self, n):
        return getattr(self.db, n)


def snapshot():
    return dict(acc), dict(calls)


def phase(label, fn, results):
    acc.clear(); calls.clear(); each.clear()
    s = time.perf_counter()
    value = fn()
    wall = time.perf_counter() - s
    results[label] = dict(wall=round(wall, 4), **{k: round(v, 4) for k, v in acc.items()},
                          calls=dict(calls), each=dict(each))
    return value


def main():
    policy_path, state, gen = Path(sys.argv[1]), sys.argv[2], json.loads(sys.argv[3])
    policy = Policy.model_validate(load_json(policy_path.read_text()))
    for repo in policy.repositories:
        repo.root = str((policy_path.parent / repo.root).absolute())
    s = time.perf_counter()
    touched = 0
    for repo in policy.repositories:  # absorb first-open cost (OS cache, AV scan) once
        for f in Path(repo.root).rglob("*"):
            if f.is_file():
                touched += len(f.read_bytes())
    first_touch = time.perf_counter() - s
    st = store_mod.Store(state)
    st.db = TimedDB(st.db)
    g = engine.Graph(policy, st)
    r = {}
    c = phase("prepare_cold", lambda: g.prepare_context("bench"), r)
    deps = phase("dependencies", lambda: g.dependencies(c["id"]), r)
    cited = [d["evidence"][0] for d in deps["dependencies"]] + [g["evidence"] for g in deps["gaps"] if "evidence" in g]
    ev = cited[0] if cited else None
    if ev:
        phase("evidence", lambda: g.get_evidence(c["id"], ev), r)
    phase("store_get", lambda: g.context(c["id"]), r)
    c2 = phase("prepare_warm", lambda: g.prepare_context("bench"), r)
    if isinstance(gen, str):  # real corpus: one-line edit of a single file
        target = Path(gen)
        target.write_text(target.read_text(encoding="utf-8") + "\n# bench edit\n", encoding="utf-8")
    else:
        subprocess.run([sys.executable, str(HERE / "gen_corpus.py"), *gen, "--version", "B"], check=True)
    a = phase("analyze_change", lambda: g.analyze_change(c2["id"]), r)
    st.db.db.close()
    db = Path(state) / "graph.sqlite3"
    out = dict(import_seconds=round(import_seconds, 4), first_touch_seconds=round(first_touch, 4), phases=r,
               files=len(c["inventory"]), bytes=c["metrics"]["bytes_read"] // 2,
               operations=len(c["graph"]["operations"]), dependencies=len(c["graph"]["dependencies"]),
               gaps=len(c["graph"]["gaps"]),
               gap_codes={k: sum(1 for x in c["graph"]["gaps"] if x["code"] == k)
                          for k in {x["code"] for x in c["graph"]["gaps"]}},
               context_json_bytes=len(contracts.canonical(c)),
               dependencies_json_bytes=len(json.dumps(deps)),
               analysis=dict(deltas=len(a["deltas"]), findings=len(a["findings"]),
                             citations=count_citations([deps, a])),
               db_bytes=db.stat().st_size + sum(p.stat().st_size for p in Path(state).glob("graph.sqlite3-*")),
               peak_wset=__import__("psutil").Process().memory_info().peak_wset)
    print(json.dumps(out))


def count_citations(value):
    keys = {"source_id", "start_line", "end_line", "quote"}
    seen = set()

    def visit(v):
        if isinstance(v, dict):
            if keys <= v.keys():
                seen.add((v["source_id"], v["start_line"], v["end_line"]))
            else:
                for x in v.values():
                    visit(x)
        elif isinstance(v, list):
            for x in v:
                visit(x)
    visit(value)
    return len(seen)


if __name__ == "__main__":
    main()
