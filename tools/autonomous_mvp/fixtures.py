"""Case repositories as real Git commits with a platform-independent identity.

A case file carries every repository file inline. The expected commit SHA is
computed here from bytes alone (Git object format), then compared with the commit
that the Git CLI actually produced. A CRLF checkout, a changed mode or an extra
file therefore fails before any model sees the corpus.
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path, PurePosixPath
import re
import subprocess

AUTHOR = "autonomous-mvp-fixture <fixtures@autonomous-mvp.invalid>"
EPOCH = "1793404800 +0000"  # 2026-10-31T00:00:00Z, fixed so commits are reproducible.
MESSAGE = "fixture snapshot\n"
REPO_ID = re.compile(r"^[a-zA-Z0-9_.-]{1,64}$")


class FixtureError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _check_path(path):
    p = PurePosixPath(path)
    if (not path or p.is_absolute() or any(part in ("", ".", "..") for part in p.parts)
            or "\\" in path or any(part.startswith(".") for part in p.parts)):
        raise FixtureError("invalid_fixture_path")
    return p


def _object(kind, body):
    return hashlib.sha1(kind.encode() + b" " + str(len(body)).encode() + b"\0" + body).digest()


def tree_sha(files):
    """Git tree hash of {posix path: utf-8 text}; all entries are 100644 blobs."""
    root = {}
    for path, text in files.items():
        parts = _check_path(path).parts
        node = root
        for part in parts[:-1]:
            node = node.setdefault(part, {})
            if not isinstance(node, dict):
                raise FixtureError("fixture_path_conflict")
        if parts[-1] in node:
            raise FixtureError("fixture_path_conflict")
        node[parts[-1]] = text.encode("utf-8")

    def build(node):
        entries = []
        for name, value in node.items():
            if isinstance(value, dict):
                entries.append((name + "/", b"40000 " + name.encode() + b"\0" + build(value)))
            else:
                entries.append((name, b"100644 " + name.encode() + b"\0" + _object("blob", value)))
        # Git orders tree entries as if directory names ended with "/".
        return _object("tree", b"".join(e for _, e in sorted(entries)))

    return build(root).hex()


def commit_sha(files):
    body = (f"tree {tree_sha(files)}\nauthor {AUTHOR} {EPOCH}\ncommitter {AUTHOR} {EPOCH}\n\n{MESSAGE}").encode()
    return _object("commit", body).hex()


def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_AUTHOR_NAME="autonomous-mvp-fixture", GIT_AUTHOR_EMAIL="fixtures@autonomous-mvp.invalid",
               GIT_COMMITTER_NAME="autonomous-mvp-fixture", GIT_COMMITTER_EMAIL="fixtures@autonomous-mvp.invalid",
               GIT_AUTHOR_DATE=EPOCH, GIT_COMMITTER_DATE=EPOCH, GIT_CONFIG_NOSYSTEM="1",
               GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0")
    # No hooks, templates, filters or attributes from the environment: the
    # fixture is data, never executed by Git machinery.
    base = ["git", "-c", "core.hooksPath=" + os.devnull, "-c", "core.autocrlf=false",
            "-c", "core.fileMode=false", "-c", "init.templateDir=", "-c", "commit.gpgSign=false"]
    result = subprocess.run(base + list(args), cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise FixtureError("git_command_failed")
    return result.stdout.strip()


def materialize(case, work):
    """Create one Git repository per available case repository.

    Returns {repo_id: {"root", "commit", "service"}} for available repositories
    and leaves unavailable ones absent on disk, as an unreachable source would be.
    """
    work = Path(work)
    result = {}
    for repo in case["repositories"]:
        if not REPO_ID.fullmatch(repo["id"]):
            raise FixtureError("invalid_repository_id")
        expected = commit_sha(repo["files"])
        if repo["availability"] != "available":
            result[repo["id"]] = dict(root=str(work / repo["id"]), commit=expected,
                                      service=repo["service"], available=False)
            continue
        root = work / repo["id"]
        root.mkdir(parents=True)
        for path, text in sorted(repo["files"].items()):
            target = root.joinpath(*_check_path(path).parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(text.encode("utf-8"))
        _git(root, "init", "-q")
        _git(root, "add", "--all")
        _git(root, "commit", "-q", "-m", MESSAGE.strip())
        actual = _git(root, "rev-parse", "HEAD")
        if actual != expected:
            raise FixtureError("fixture_commit_mismatch")
        if _git(root, "status", "--porcelain"):
            raise FixtureError("fixture_worktree_dirty")
        result[repo["id"]] = dict(root=str(root), commit=actual, service=repo["service"], available=True)
    return result
