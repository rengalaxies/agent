"""Rewrite infra/agent_graph_demo/core.lock.json from git blobs of a core commit.

usage: repin_lock.py CORE_SHA PROFILE   (run in the repository root)
Hashes come from `git show`, not the working tree, so CRLF checkouts cannot leak in.
"""
import hashlib
import json
import subprocess
import sys

sha, profile = sys.argv[1], sys.argv[2]
path = "infra/agent_graph_demo/core.lock.json"
lock = json.load(open(path, encoding="utf-8"))
lock["sha"], lock["profile"] = sha, profile
for name in lock["files"]:
    blob = subprocess.run(["git", "show", f"{sha}:src/agent_graph/{name}"], capture_output=True, check=True).stdout
    lock["files"][name] = hashlib.sha256(blob).hexdigest()
with open(path, "w", encoding="utf-8", newline="\n") as f:
    f.write(json.dumps(lock, indent=2) + "\n")
