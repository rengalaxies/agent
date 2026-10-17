"""Offline Git review export. No remote, hooks, inherited config or source writes."""
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .adapters import read_repository_file

SAFE_PATH = re.compile(r"[A-Za-z0-9_/-]+(?:\.[A-Za-z0-9_-]+)*\Z")


def export_review_bundle(baseline: Path, candidate: Path, paths: list[str], output: Path):
    if (type(paths) is not list or not 1 <= len(paths) <= 64 or len(set(paths)) != len(paths)
            or any(type(p) is not str or not SAFE_PATH.fullmatch(p) or p.startswith("/")
                   or any(part in {"..", ".git"} for part in p.split("/")) for p in paths)):
        raise ValueError("unsafe_git_paths")
    # Capture both snapshots with existing symlink-safe bounded reads first.
    before, after, total = {}, {}, 0
    for root, snapshot in ((baseline, before), (candidate, after)):
        for path in paths:
            data = read_repository_file(root, path)
            total += len(data)
            if total > 4_000_000:
                raise ValueError("git_snapshot_limit")
            snapshot[path] = data
    git = shutil.which("git")
    if git is None:
        raise ValueError("git_unavailable")
    if any(output.resolve().is_relative_to(root.resolve()) for root in (baseline, candidate)):
        raise ValueError("output_must_differ")
    # Exclusive output also rejects writing through an existing output symlink.
    if any(parent.is_symlink() for parent in output.absolute().parents):
        raise ValueError("symlink_output_parent")
    output.mkdir(mode=0o700, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="change-review-") as temp:
        repo = Path(temp) / "repo"
        repo.mkdir()
        home = Path(temp) / "home"
        home.mkdir()
        empty_hooks = Path(temp) / "hooks"
        empty_hooks.mkdir()
        env = {"PATH": os.defpath, "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1",
               "GIT_CONFIG_GLOBAL": os.devnull, "GIT_TERMINAL_PROMPT": "0", "LC_ALL": "C",
               "GIT_AUTHOR_NAME": "Change Completion", "GIT_AUTHOR_EMAIL": "offline@example.invalid",
               "GIT_COMMITTER_NAME": "Change Completion", "GIT_COMMITTER_EMAIL": "offline@example.invalid",
               "GIT_AUTHOR_DATE": "2000-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2000-01-01T00:00:00Z"}
        common = [git, "-c", f"core.hooksPath={empty_hooks}", "-c", "commit.gpgSign=false",
                  "-c", "core.autocrlf=false", "-c", "protocol.allow=never"]

        def run(*args):
            proc = subprocess.run(common + list(args), cwd=repo, env=env, input=None,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, check=False)
            if proc.returncode:
                raise ValueError("git_export_failed")
            return proc.stdout

        run("init", "--quiet", "--initial-branch=review", "--template=")
        for snapshot in (before, after):
            for path, content in snapshot.items():
                target = repo / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(content)
            run("add", "--", *paths)
            run("commit", "--quiet", "--allow-empty", "-m", "Baseline" if snapshot is before else "Candidate")
        base = run("rev-parse", "HEAD~1").decode().strip()
        head = run("rev-parse", "HEAD").decode().strip()
        patch = run("diff", "--no-ext-diff", "--no-textconv", "HEAD~1", "HEAD", "--", *paths)
        (output / "candidate.patch").write_bytes(patch)
        # Full two-commit bundle is independently cloneable, not a prerequisite-only delta.
        run("bundle", "create", str((output / "candidate.bundle").resolve()), "HEAD")
        run("bundle", "verify", str((output / "candidate.bundle").resolve()))
    return {"status": "EXPORTED", "baseline_commit": base, "candidate_commit": head,
            "paths": paths, "effects_authorized": False, "remote_contacted": False}
