"""Deterministic synthetic HTTP corpus: one FastAPI provider, R consumer repos.

usage: gen_corpus.py OUT FILES DEPS_PER_FILE NOISE_PER_FILE [--version A|B]
Writes OUT/repos/<repo>/... and OUT/policy.json. Version B changes the
page_size default of route /r0 from None to 100 (the demo's change kind).
"""
import json
import random
import sys
from pathlib import Path

ROUTES_PER_FILE = 20


def provider(n_routes, version):
    files = {}
    for f in range(0, n_routes, ROUTES_PER_FILE):
        lines = ["from fastapi import FastAPI", "", "app = FastAPI()", ""]
        for j in range(f, min(f + ROUTES_PER_FILE, n_routes)):
            default = "100" if (version == "B" and j == 0) else "None"
            lines += [f'@app.get("/r{j}")',
                      f"def list_r{j}(cursor: str | None = None, page_size: int | None = {default}):",
                      f"    items = load_r{j}(cursor, page_size)",
                      "    return {\"items\": items, \"next_cursor\": None}", ""]
        files[f"api_{f // ROUTES_PER_FILE:03d}.py"] = "\n".join(lines) + "\n"
    return files


def consumer(i, deps, noise, n_routes, rnd):
    out = [f'"""Module {i}: report assembly."""', "import os", "import requests", "",
           'BASE = "http://orders:8000"', "LIMIT = 50", "", "",
           f"class Report{i}:", "    def __init__(self, cfg):", "        self.cfg = cfg",
           '        self.timeout = cfg.get("timeout", 10)', ""]
    for k in range(deps):
        j = 0 if k == 0 and i % 50 == 0 else rnd.randrange(n_routes)
        style = k % 3
        out.append(f"    def load_{k}(self):")
        if style == 0:
            out += [f'        r = requests.get(BASE + "/r{j}", timeout=5)', '        return r.json()["items"]']
        elif style == 1:
            out += [f'        r = requests.get(BASE + "/r{j}", params={{"page_size": LIMIT}}, timeout=5)',
                    '        return r.json()["items"]']
        else:
            out += ["        cursor, rows = None, []", "        while True:",
                    f'            r = requests.get(BASE + "/r{j}", params={{"cursor": cursor}}, timeout=5)',
                    "            body = r.json()", '            rows += body["items"]',
                    '            cursor = body["next_cursor"]', "            if not cursor:",
                    "                return rows"]
        out.append("")
    out += ["", f"def helper_{i}(data):", "    out = {}", "    for row in data:"]
    for n in range(noise):
        out.append(f'        out[row.get("k{n}")] = os.environ.get("V{n}", "x")' if n % 2 == 0
                   else f'        out["s{n}"] = sorted(row.items(), key=lambda kv: kv[0])')
    if not noise:
        out.append("        out[len(out)] = row")
    out += ["    return out", ""]
    return "\n".join(out) + "\n"


def main():
    out, n_files, deps, noise = Path(sys.argv[1]), int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
    version = sys.argv[sys.argv.index("--version") + 1] if "--version" in sys.argv else "A"
    rnd = random.Random(42)
    n_routes = 200
    repos = {"orders": ("Orders", provider(n_routes, version))}
    n_consumers = max(1, min(7, n_files // 50 or 1))
    for c in range(n_consumers):
        repos[f"consumer{c}"] = (f"Consumer{c}", {})
    names = [r for r in repos if r != "orders"]
    for i in range(n_files):
        repos[names[i % len(names)]][1][f"pkg{i // 100:03d}/mod_{i:05d}.py"] = consumer(i, deps, noise, n_routes, rnd)
    for repo, (_, files) in repos.items():
        for rel, text in files.items():
            p = out / "repos" / repo / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            # Rewrite only changed files, so version B touches one file as a real edit does.
            if not p.exists() or p.read_text() != text:
                p.write_text(text, newline="\n")
    policy = dict(installation_id="bench", environment="bench", subject="bench",
                  capabilities=["read_context", "maintain", "propose", "correct", "report_check"],
                  repositories=[dict(id=r, service=s, root=f"repos/{r}", revision="r1")
                                for r, (s, _) in repos.items()],
                  addresses=[dict(service="Orders", base_url="http://orders:8000")],
                  limits=dict(max_files=10000, max_file_bytes=262144, max_corpus_bytes=20_000_000,
                              scan_seconds=120))
    (out / "policy.json").write_text(json.dumps(policy, indent=1))


if __name__ == "__main__":
    main()
