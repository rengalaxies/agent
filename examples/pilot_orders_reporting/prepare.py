"""Build reproducible local repositories/bundles; never creates or pushes remote resources.

Usage: python examples/pilot_orders_reporting/prepare.py <new-output-directory>
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from examples.orders_reporting.stand import _git, _tree, git_env  # noqa: E402

ROOT = Path(__file__).resolve().parent


def prepare(directory):
    root = Path(directory).resolve()
    root.mkdir(parents=True, exist_ok=False)
    home = root / "git-home"
    home.mkdir()
    (home / "gitconfig").write_text("")
    env = git_env(home)
    result = {"schema": "author-pilot-preparation-1", "repositories": {}, "bundles": {}}
    for service in ("orders", "reporting"):
        files = {p.name: p.read_text() for p in sorted((ROOT / service).iterdir()) if p.is_file()}
        repo = root / service
        subprocess.run(["git", "init", "-q", "--initial-branch=main", str(repo)], env=env, check=True)
        commits = {}

        def commit(branch, content, parent=None):
            args = ["commit-tree", _tree(repo, env, content), "-m", f"author pilot {service}: {branch}"]
            if parent:
                args += ["-p", commits[parent]]
            sha = _git(repo, env, *args)
            _git(repo, env, "update-ref", f"refs/heads/{branch}", sha)
            commits[branch] = sha

        commit("main", files)
        if service == "orders":
            limit = {**files, "api.py": files["api.py"].replace("page_size: int = 100", "page_size: int = 20")}
            commit("pilot-page-limit", limit, "main")
            commit("pilot-restored", files, "pilot-page-limit")
            commit("pilot-docs-only", {**files, "README.md": files["README.md"] +
                                      "\nDocument GET /orders pagination. No API change.\n"}, "main")
        else:
            fixed = files["client.py"].replace('params={"day": day}', 'params={"day": day, "page_size": 100}')
            commit("pilot-explicit-limit", {**files, "client.py": fixed}, "main")
        bundle = root / f"agent-pilot-{service}.bundle"
        _git(repo, env, "bundle", "create", str(bundle), "--all")
        _git(repo, env, "bundle", "verify", str(bundle))
        result["repositories"][service] = {"commits": commits,
            "files": {name: hashlib.sha256(text.encode()).hexdigest() for name, text in files.items()}}
        result["bundles"][service] = {"name": bundle.name, "sha256": hashlib.sha256(bundle.read_bytes()).hexdigest()}
    (root / "prepared.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    print(json.dumps(prepare(sys.argv[1]), indent=2, sort_keys=True))
