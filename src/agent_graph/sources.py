"""Bounded local collection. Never imports, executes, follows links or fetches URLs."""
from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
import stat
import time

from . import PROFILE
from .contracts import GraphError, Policy, digest

IGNORED_DIRS = {".git", ".venv", "node_modules", "__pycache__"}
SENSITIVE = ("secret", "credential", "private_key", "id_rsa", "id_ed25519")


def read_relative(root: Path, relative: str, limit: int) -> bytes:
    """openat + O_NOFOLLOW for every component: traversal and symlink race safe."""
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or any(p in ("..", ".") for p in parts):
        raise GraphError("invalid_source_path")
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = nxt
        final = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        try:
            if not stat.S_ISREG(os.fstat(final).st_mode):
                raise GraphError("not_regular_source")
            with os.fdopen(final, "rb", closefd=False) as stream:
                raw = stream.read(limit + 1)
            if len(raw) > limit:
                raise GraphError("file_limit")
            return raw
        finally:
            os.close(final)
    finally:
        os.close(fd)


def collect(policy: Policy):
    policy.require("read_context")
    sources, gaps, inventory = {}, [], []
    started = time.monotonic()
    used_bytes = 0
    visited = 0
    for repo in policy.repositories:
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
                    import re
                    if re.search(r"(?i)(api[_-]?key|password|secret|token)\s*[:=]\s*['\"][^'\"\s]{8,}", text):
                        raise GraphError("sensitive_source")
                    sha = hashlib.sha256(raw).hexdigest()
                    source_id = digest([policy.installation_id, policy.environment, repo.id,
                                        repo.revision, relative, sha])
                    sources[source_id] = dict(id=source_id, repository=repo.id, service=repo.service,
                                              path=relative, revision=repo.revision, sha256=sha, text=text)
                    inventory.append([repo.id, repo.revision, relative, sha])
                except (OSError, UnicodeError, GraphError) as exc:
                    if isinstance(exc, GraphError) and exc.code == "corpus_limit":
                        raise
                    code = exc.code if isinstance(exc, GraphError) else "source_unreadable"
                    gaps.append(dict(code=code, repository=repo.id, path=relative))
                    inventory.append([repo.id, repo.revision, relative, code])
    basis = digest([inventory, policy.addresses_dump(), [r.model_dump() for r in policy.requirements], PROFILE])
    return dict(sources=sources, gaps=gaps, basis=basis, inventory=inventory,
                bytes_read=used_bytes, elapsed_seconds=time.monotonic() - started)
