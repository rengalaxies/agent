"""Prototype: per-file extraction cache and content-addressed source blobs.

Question it answers: with the unchanged Python extractor, what does a refresh
cost after a one-file edit if work is keyed by file content, and does the
result stay identical to the full extract()?

usage: proto_incremental.py POLICY EDIT_PATH STEPS
Runs STEPS edits of one consumer file. After each edit: full collect+extract
(as the core does today) vs incremental (stat cache -> rehash changed files ->
reuse per-file provider/consumer results). Compares graphs byte for byte and
reports the store growth of "full corpus per context" vs "blobs + manifest".
"""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "core" / "src"))
sys.path.insert(0, str(HERE))
import bench_shim  # noqa: E402,F401
from agent_graph import PROFILE, discovery  # noqa: E402
from agent_graph.contracts import Policy, canonical, digest, load_json  # noqa: E402
from agent_graph.sources import collect  # noqa: E402


class Incremental:
    def __init__(self, policy):
        self.policy = policy
        self.stat = {}      # path -> (size, mtime_ns, sha)
        self.text = {}      # sha -> text
        self.prov = {}      # (sha, PROFILE) -> (operations, gaps)
        self.cons = {}      # (sha, ops_key) -> (deps, gaps)

    def scan(self):
        sources, hashed = {}, 0
        for repo in self.policy.repositories:
            root = Path(repo.root)
            for directory, dirs, files in os.walk(root):
                dirs[:] = sorted(d for d in dirs if d not in {".git", "__pycache__"} and not d.startswith("."))
                for name in sorted(files):
                    p = Path(directory) / name
                    rel = p.relative_to(root).as_posix()
                    if not rel.endswith((".py", ".json", ".md")):
                        continue
                    st = p.stat()
                    key = (st.st_size, st.st_mtime_ns)
                    cached = self.stat.get(str(p))
                    if cached and cached[:2] == key:
                        sha = cached[2]
                    else:
                        raw = p.read_bytes()
                        sha = hashlib.sha256(raw).hexdigest()
                        self.text.setdefault(sha, raw.decode("utf-8"))
                        self.stat[str(p)] = (*key, sha)
                        hashed += 1
                    sid = digest([self.policy.installation_id, self.policy.environment, repo.id,
                                  repo.revision, rel, sha])
                    sources[sid] = dict(id=sid, repository=repo.id, service=repo.service, path=rel,
                                        revision=repo.revision, sha256=sha, text=self.text[sha])
        return sources, hashed

    def extract(self, sources):
        ops, gaps = [], []
        for sid, s in sources.items():
            k = (s["sha256"], s["id"], PROFILE)
            if k not in self.prov:
                self.prov[k] = discovery.providers(self.policy, {sid: s})
            o, g = self.prov[k]
            ops += json.loads(json.dumps(o))
            gaps += g
        # Same grouping as providers(): rerun it over cached per-file operations.
        grouped = {}
        for op in ops:
            if op["id"] not in grouped:
                grouped[op["id"]] = op
                continue
            old = grouped[op["id"]]
            old["evidence"].extend(op["evidence"])
            if op.get("page_size_declared"):
                old["page_size_declared"] = True
            if old["default_known"] and op["default_known"] and old["page_size_default"] != op["page_size_default"]:
                old["default_conflict"] = True
                gaps.append(dict(code="provider_declaration_conflict", operation_id=op["id"]))
            elif op["default_known"]:
                old.update(default_known=True, page_size_default=op["page_size_default"])
        operations = sorted(grouped.values(), key=lambda o: o["id"])
        ops_key = digest([[o["id"], o["service"], o["method"], o["path"]] for o in operations])
        deps, cgaps = [], []
        for sid, s in sources.items():
            k = (s["sha256"], s["id"], ops_key)
            if k not in self.cons:
                self.cons[k] = discovery.consumers(self.policy, {sid: s}, operations)
            d, g = self.cons[k]
            deps += d
            cgaps += g
        return dict(operations=operations, dependencies=sorted(deps, key=lambda d: d["id"]), gaps=gaps + cgaps)


def comparable(graph):
    return canonical(dict(operations=graph["operations"], dependencies=graph["dependencies"],
                          gaps=sorted(canonical(g) for g in graph["gaps"])))


def main():
    policy_path, edit, steps = Path(sys.argv[1]), Path(sys.argv[2]), int(sys.argv[3])
    policy = Policy.model_validate(load_json(policy_path.read_text()))
    for repo in policy.repositories:
        repo.root = str((policy_path.parent / repo.root).absolute())
    inc = Incremental(policy)
    db_full = sqlite3.connect(tempfile.mktemp(suffix=".db"))
    db_blob = sqlite3.connect(tempfile.mktemp(suffix=".db"))
    db_full.execute("CREATE TABLE contexts(id TEXT PRIMARY KEY, data TEXT)")
    db_blob.execute("CREATE TABLE blobs(sha TEXT PRIMARY KEY, text TEXT)")
    db_blob.execute("CREATE TABLE contexts(id TEXT PRIMARY KEY, data TEXT)")
    db_part = sqlite3.connect(tempfile.mktemp(suffix=".db"))
    db_part.execute("CREATE TABLE blobs(sha TEXT PRIMARY KEY, text TEXT)")
    db_part.execute("CREATE TABLE parts(id TEXT PRIMARY KEY, data TEXT)")
    db_part.execute("CREATE TABLE contexts(id TEXT PRIMARY KEY, data TEXT)")
    rows = []
    for step in range(steps + 1):
        if step:
            edit.write_text(edit.read_text() + f"\n# edit {step}\n", newline="\n")
        s = time.perf_counter()
        c = collect(policy)
        full = discovery.extract(policy, c)
        t_full = time.perf_counter() - s
        s = time.perf_counter()
        sources, hashed = inc.scan()
        graph = inc.extract(sources)
        t_inc = time.perf_counter() - s
        same = comparable(graph) == comparable(full)
        ctx = dict(basis=c["basis"], sources=c["sources"], graph=full)
        with db_full:
            db_full.execute("INSERT INTO contexts VALUES(?,?)", (c["basis"], canonical(ctx)))
        with db_blob:
            for src in c["sources"].values():
                db_blob.execute("INSERT OR IGNORE INTO blobs VALUES(?,?)", (src["sha256"], src["text"]))
            manifest = {k: {x: v for x, v in src.items() if x != "text"} for k, src in c["sources"].items()}
            db_blob.execute("INSERT INTO contexts VALUES(?,?)", (c["basis"], canonical(dict(basis=c["basis"], sources=manifest, graph=full))))
        with db_part:
            refs = []
            for key, value in list(inc.prov.items()) + list(inc.cons.items()):
                pid = digest([list(key)])
                refs.append(pid)
                db_part.execute("INSERT OR IGNORE INTO parts VALUES(?,?)", (pid, canonical(value)))
            for src in c["sources"].values():
                db_part.execute("INSERT OR IGNORE INTO blobs VALUES(?,?)", (src["sha256"], src["text"]))
            db_part.execute("INSERT INTO contexts VALUES(?,?)", (c["basis"], canonical(dict(
                basis=c["basis"], sources=sorted(s["sha256"] for s in c["sources"].values()), parts=sorted(refs)))))
        size = lambda db: db.execute("PRAGMA page_count").fetchone()[0] * db.execute("PRAGMA page_size").fetchone()[0]
        rows.append(dict(step=step, full_seconds=round(t_full, 4), incremental_seconds=round(t_inc, 4),
                         rehashed_files=hashed, identical=same,
                         store_full_bytes=size(db_full), store_blob_bytes=size(db_blob), store_parts_bytes=size(db_part)))
        print(json.dumps(rows[-1]), flush=True)


if __name__ == "__main__":
    main()
