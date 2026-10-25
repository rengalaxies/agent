"""Bounded collection of pinned Git snapshots or a local worktree.

Never imports, executes, follows links or fetches URLs.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
import re
import time

from . import PROFILE
from .contracts import GraphError, Policy, digest
from .git_sources import SHA, GitReader
from .portable import read_regular

IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
SENSITIVE = ("secret", "credential", "private_key", "id_rsa", "id_ed25519")


def read_relative(root: Path, relative: str, limit: int) -> bytes:
    """openat + O_NOFOLLOW for every component on Linux: traversal and symlink race safe."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in ("..", ".") for p in parts):
        raise GraphError("invalid_source_path")
    return read_regular(Path(root), parts, limit, GraphError)


SECRET_TEXT = re.compile(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"\s]{8,}")


def pins(policy: Policy, revisions):
    """Commit per git repository: request map first, then a full SHA in configuration."""
    revisions = dict(revisions or {})
    known = {r.id for r in policy.repositories}
    if any(repo not in known for repo in revisions):
        raise GraphError("repository_not_allowed")
    result = {}
    for repo in policy.repositories:
        if repo.snapshot != "git":
            if repo.id in revisions:
                raise GraphError("worktree_cannot_be_pinned")
            continue
        pin = revisions.get(repo.id, repo.revision)
        if not isinstance(pin, str) or not SHA.fullmatch(pin):
            raise GraphError("revision_required")
        result[repo.id] = pin
    return result


def _collect_git(policy, repo, commit, deadline, sources, gaps, inventory, snapshots, budget):
    try:
        reader = GitReader(Path(repo.root), deadline=deadline)
        tree = reader.resolve(commit, repo.allowed_refs)
    except GraphError as exc:
        if exc.code not in ("source_unavailable", "git_command_failed"):
            raise
        tree = None
    if tree is None:
        # A missing or foreign commit is never replaced by the current branch.
        gaps.append(dict(code="commit_unavailable", repository=repo.id))
        inventory.append([repo.id, commit, "commit_unavailable"])
        snapshots.append(dict(repository=repo.id, mode="GIT_COMMIT", commit=commit, tree=None))
        return
    snapshots.append(dict(repository=repo.id, mode="GIT_COMMIT", commit=commit, tree=tree))
    for relative, blob, raw in reader.files(tree, include=repo.include, ignored_dirs=IGNORED_DIRS,
                                            sensitive=SENSITIVE, limits=policy.limits, budget=budget,
                                            gaps=gaps, repository=repo.id):
        if len(inventory) >= policy.limits.max_files:
            raise GraphError("file_count_limit")
        try:
            text = raw.decode("utf-8")
        except UnicodeError:
            gaps.append(dict(code="binary_omitted", repository=repo.id, path=relative))
            inventory.append([repo.id, commit, relative, blob, "binary_omitted"])
            continue
        if SECRET_TEXT.search(text):
            gaps.append(dict(code="sensitive_source", repository=repo.id, path=relative))
            inventory.append([repo.id, commit, relative, blob, "sensitive_source"])
            continue
        sha = hashlib.sha256(raw).hexdigest()
        source_id = digest([policy.installation_id, policy.environment, repo.id, commit, relative, blob])
        sources[source_id] = dict(id=source_id, repository=repo.id, service=repo.service, path=relative,
                                  revision=commit, sha256=sha, text=text, snapshot="GIT_COMMIT",
                                  commit=commit, blob=blob)
        inventory.append([repo.id, commit, relative, blob])


def collect(policy: Policy, revisions=None):
    policy.require("read_context")
    sources, gaps, inventory, snapshots = {}, [], [], []
    started = time.monotonic()
    used_bytes = 0
    visited = 0
    pinned = pins(policy, revisions)

    def budget(size):
        nonlocal used_bytes
        used_bytes += size
        if used_bytes > policy.limits.max_corpus_bytes:
            raise GraphError("corpus_limit")

    for repo in policy.repositories:
        if repo.snapshot == "git":
            _collect_git(policy, repo, pinned[repo.id], started + policy.limits.scan_seconds,
                         sources, gaps, inventory, snapshots, budget)
            continue
        snapshots.append(dict(repository=repo.id, mode="WORKTREE", commit=None, tree=None))
        root = Path(repo.root)
        # root configuration is operator-controlled; do not silently resolve a link.
        if not root.is_absolute() or root.is_symlink():
            raise GraphError("invalid_source_root")
        if not root.is_dir():
            gaps.append({"code": "source_unavailable", "repository": repo.id})
            inventory.append([repo.id, repo.revision, "unavailable"])
            continue
        def walk_error(_error):
            gaps.append(dict(code="directory_unreadable", repository=repo.id))
            inventory.append([repo.id, repo.revision, "directory_unreadable"])
        for directory, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
            visited += 1
            if visited > policy.limits.max_files * 20:
                raise GraphError("inventory_limit")
            if time.monotonic() - started > policy.limits.scan_seconds:
                raise GraphError("scan_timeout")
            for d in dirs:
                if (Path(directory) / d).is_symlink():
                    gaps.append(dict(code="symlink_directory_omitted", repository=repo.id))
                    inventory.append([repo.id, repo.revision, "symlink_directory", str((Path(directory)/d).relative_to(root))])
            dirs[:] = sorted(d for d in dirs if d not in IGNORED_DIRS and not d.startswith("."))
            for name in sorted(files):
                if time.monotonic() - started > policy.limits.scan_seconds:
                    raise GraphError("scan_timeout")
                visited += 1
                if visited > policy.limits.max_files * 20:
                    raise GraphError("inventory_limit")
                relative = (Path(directory) / name).relative_to(root).as_posix()
                if (name.startswith(".") or any(s in relative.lower() for s in SENSITIVE)
                        or not any(fnmatch.fnmatchcase(relative, p) for p in repo.include)):
                    continue
                if len(inventory) >= policy.limits.max_files:
                    raise GraphError("file_count_limit")
                try:
                    raw = read_relative(root, relative, policy.limits.max_file_bytes)
                    used_bytes += len(raw)
                    if used_bytes > policy.limits.max_corpus_bytes:
                        raise GraphError("corpus_limit")
                    text = raw.decode("utf-8")
                    # Refuse rather than 'redact' a source and assert the redaction
                    # is complete. Operator still must provide a sanitized corpus.
                    if SECRET_TEXT.search(text):
                        raise GraphError("sensitive_source")
                    sha = hashlib.sha256(raw).hexdigest()
                    source_id = digest([policy.installation_id, policy.environment, repo.id,
                                        repo.revision, relative, sha])
                    sources[source_id] = dict(id=source_id, repository=repo.id, service=repo.service,
                                              path=relative, revision=repo.revision, sha256=sha, text=text,
                                              snapshot="WORKTREE", commit=None, blob=None)
                    inventory.append([repo.id, repo.revision, relative, sha])
                except (OSError, UnicodeError, GraphError) as exc:
                    if isinstance(exc, GraphError) and exc.code == "corpus_limit":
                        raise
                    code = exc.code if isinstance(exc, GraphError) else "source_unreadable"
                    gaps.append(dict(code=code, repository=repo.id, path=relative))
                    inventory.append([repo.id, repo.revision, relative, code])
    basis = digest([inventory, policy.addresses_dump(), [r.model_dump() for r in policy.requirements], PROFILE])
    return dict(sources=sources, gaps=gaps, basis=basis, inventory=inventory, snapshots=snapshots,
                revisions=pinned, bytes_read=used_bytes, elapsed_seconds=time.monotonic() - started)


def pinned_only(policy: Policy) -> bool:
    return all(repo.snapshot == "git" for repo in policy.repositories)


def pinned_freshness(policy: Policy, context):
    """A pinned snapshot does not age; it is CURRENT while every commit still resolves
    to the same tree from an allowed ref. Whether it is still the PR head is decided
    by the service (SUPERSEDED), not here."""
    from datetime import datetime, timezone
    assessed = datetime.now(timezone.utc).isoformat()
    repos = {r.id: r for r in policy.repositories}
    deadline = time.monotonic() + policy.limits.scan_seconds
    reasons = ["partial_coverage"] if context["coverage"] == "PARTIAL" else []
    for snap in context["snapshots"]:
        repo = repos.get(snap["repository"])
        if repo is None or snap["mode"] != "GIT_COMMIT":
            return dict(status="STALE", assessed_at=assessed, comparison_basis="PINNED_COMMITS",
                        reasons=["basis_changed"] + reasons)
        try:
            tree = GitReader(Path(repo.root), deadline=deadline).resolve(snap["commit"], repo.allowed_refs)
        except GraphError as exc:
            if exc.code not in ("source_unavailable", "git_command_failed"):
                return dict(status="UNKNOWN", assessed_at=assessed, comparison_basis="PINNED_COMMITS",
                            reasons=["current_corpus_unavailable"])
            # Same rule as collection: an unreadable repository is an unavailable commit.
            # Unavailable at prepare and still unavailable is no change (tree None == None).
            tree = None
        if tree != snap["tree"]:
            return dict(status="UNKNOWN" if tree is None else "STALE", assessed_at=assessed,
                        comparison_basis="PINNED_COMMITS",
                        reasons=["current_corpus_unavailable" if tree is None else "basis_changed"])
    return dict(status="CURRENT", assessed_at=assessed, comparison_basis="PINNED_COMMITS", reasons=reasons)
