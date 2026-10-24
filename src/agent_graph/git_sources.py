"""Pinned Git snapshots. Reads objects, never a working tree, and executes nothing.

Only plumbing runs: `rev-parse`, `for-each-ref --contains` and one `cat-file
--batch-command` process per repository snapshot. No checkout, so repository
hooks, filters, attributes and textconv never run; fsmonitor and hooks are also
disabled on the command line, global/system configuration is not read and lazy
fetching of missing objects is refused. Every commit, tree and blob is hashed
again here, so a file is accepted only if it is reachable from the pinned commit
by verified object IDs. Callers pass commit SHAs from trusted configuration or
the validated request; a model never supplies URLs, paths outside the snapshot
or refs.
"""
from __future__ import annotations

import fnmatch
import hashlib
import os
from pathlib import Path
import re
import subprocess
import threading
import time

from .contracts import GraphError

SHA = re.compile(r"^([0-9a-f]{40}|[0-9a-f]{64})$")
LFS = b"version https://git-lfs.github.com/spec/v1\n"
MIN_GIT = (2, 36)  # cat-file --batch-command
NO_LAZY_FETCH_GIT = (2, 44)  # GIT_NO_LAZY_FETCH is honoured


def _git_version(env):
    out = subprocess.run(["git", "version"], env=env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                         timeout=10, check=True).stdout.decode()
    match = re.search(r"(\d+)\.(\d+)", out)
    return (int(match.group(1)), int(match.group(2))) if match else (0, 0)


def _environment():
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_TERMINAL_PROMPT="0",
               GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_ATTR_NOSYSTEM="1",
               GIT_OPTIONAL_LOCKS="0", GIT_PAGER="cat", LANG="C", LC_ALL="C", HOME=os.devnull)
    return env


def git_dir(root: Path) -> Path:
    """Operator-configured repository: a non-bare repo's .git directory or a bare repo."""
    root = Path(root)
    if not root.is_absolute() or root.is_symlink():
        raise GraphError("invalid_source_root")
    dot = root / ".git"
    if dot.is_dir() and not dot.is_symlink():
        return dot
    if dot.exists():
        raise GraphError("unsupported_git_layout")  # gitfile indirection is not followed
    if (root / "HEAD").is_file() and (root / "objects").is_dir():
        return root
    raise GraphError("source_unavailable")


class _Objects:
    """One cat-file --batch-command process, killed at the snapshot deadline."""

    def __init__(self, reader):
        self.reader = reader
        self.proc = subprocess.Popen(reader.argv("cat-file", "--batch-command"), env=reader.env,
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self.timer = threading.Timer(max(0.001, reader.deadline - time.monotonic()), self.proc.kill)
        self.timer.daemon = True
        self.timer.start()

    def close(self):
        self.timer.cancel()
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()
                self.proc.wait()
        self.proc.stdout.close()

    def _command(self, verb, oid):
        if time.monotonic() >= self.reader.deadline:
            raise GraphError("scan_timeout")
        try:
            self.proc.stdin.write(f"{verb} {oid}\n".encode())
            self.proc.stdin.flush()
            header = self.proc.stdout.readline()
        except OSError:
            header = b""
        if not header:
            raise GraphError("scan_timeout" if time.monotonic() >= self.reader.deadline else "git_unavailable")
        parts = header.split()
        if len(parts) == 2 and parts[1] == b"missing":
            return None
        if len(parts) != 3 or parts[0].decode() != oid or not parts[2].isdigit():
            raise GraphError("git_protocol_error")
        return parts[1].decode(), int(parts[2])

    def info(self, oid):
        return self._command("info", oid)

    def contents(self, oid, expected_type):
        header = self._command("contents", oid)
        if header is None:
            return None
        kind, size = header
        data = self.proc.stdout.read(size + 1)
        if len(data) != size + 1 or data[-1:] != b"\n":
            raise GraphError("scan_timeout" if time.monotonic() >= self.reader.deadline else "git_protocol_error")
        data = data[:-1]
        if kind != expected_type:
            raise GraphError("unexpected_object_type")
        self.reader.verify(oid, kind, data)
        return data


class GitReader:
    def __init__(self, root, *, deadline):
        self.dir = git_dir(root)
        self.deadline = deadline
        self.env = _environment()
        version = _git_version(self.env)
        if version < MIN_GIT:
            raise GraphError("git_too_old")
        self.format = self._run("rev-parse", "--show-object-format").strip() or "sha1"
        if self.format not in ("sha1", "sha256"):
            raise GraphError("unsupported_object_format")
        partial = self._run("config", "--get", "extensions.partialclone", check=False).strip()
        if partial and version < NO_LAZY_FETCH_GIT:
            raise GraphError("partial_clone_requires_git_2_44")

    def argv(self, *args):
        return ["git", "--no-pager", "--no-replace-objects", "--literal-pathspecs", "--git-dir", str(self.dir),
                "-c", "core.fsmonitor=false", "-c", "core.hooksPath=" + os.devnull, *args]

    def _run(self, *args, check=True):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise GraphError("scan_timeout")
        try:
            out = subprocess.run(self.argv(*args), env=self.env, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 stdin=subprocess.DEVNULL, timeout=remaining)
        except subprocess.TimeoutExpired:
            raise GraphError("scan_timeout") from None
        except OSError:
            raise GraphError("git_unavailable") from None
        if check and out.returncode:
            raise GraphError("git_command_failed")
        return out.stdout.decode("utf-8", "replace")

    def verify(self, oid, kind, data):
        actual = hashlib.new(self.format, f"{kind} {len(data)}\0".encode() + data).hexdigest()
        if actual != oid:
            raise GraphError("object_hash_mismatch")

    def resolve(self, commit, allowed_refs):
        """Tree of a commit reachable from an allowed ref of THIS repository, or None."""
        if not isinstance(commit, str) or not SHA.fullmatch(commit):
            raise GraphError("invalid_revision")
        objects = _Objects(self)
        try:
            raw = objects.contents(commit, "commit") if objects.info(commit) else None
        except GraphError as exc:
            if exc.code != "unexpected_object_type":
                raise
            raw = None
        finally:
            objects.close()
        if raw is None:
            return None
        refs = self._run("for-each-ref", "--format=%(refname)", "--contains", commit, *allowed_refs, check=False)
        if not refs.strip():
            return None
        first = raw.split(b"\n", 1)[0].decode("ascii", "replace")
        if not first.startswith("tree ") or not SHA.fullmatch(first[5:]):
            raise GraphError("git_protocol_error")
        return first[5:]

    def _entries(self, data):
        width = 20 if self.format == "sha1" else 32
        position = 0
        while position < len(data):
            space = data.index(b" ", position)
            nul = data.index(b"\0", space)
            mode = data[position:space].decode("ascii")
            name = data[space + 1:nul]
            oid = data[nul + 1:nul + 1 + width].hex()
            if len(oid) != width * 2:
                raise GraphError("git_protocol_error")
            position = nul + 1 + width
            yield mode, name, oid

    def files(self, tree, *, include, ignored_dirs, sensitive, limits, budget, gaps, repository):
        """Yield (path, blob, bytes) of allowed regular files; record every omission as a gap."""
        objects = _Objects(self)
        try:
            stack = [("", tree)]
            visited = 0
            while stack:
                prefix, oid = stack.pop()
                data = objects.contents(oid, "tree")
                if data is None:
                    gaps.append(dict(code="object_unavailable", repository=repository, path=prefix or "."))
                    continue
                for mode, raw_name, child in sorted(self._entries(data), key=lambda e: e[1]):
                    visited += 1
                    if visited > limits.max_files * 20:
                        raise GraphError("inventory_limit")
                    try:
                        name = raw_name.decode("utf-8")
                    except UnicodeError:
                        name = None
                    if (not name or name in (".", "..") or any(c in name for c in "/\\\0")
                            or name.lower() == ".git"):
                        gaps.append(dict(code="invalid_source_path", repository=repository, path=prefix or "."))
                        continue
                    path = prefix + name
                    if mode == "40000":
                        if name not in ignored_dirs and not name.startswith("."):
                            stack.append((path + "/", child))
                        continue
                    if mode == "160000":
                        gaps.append(dict(code="submodule_omitted", repository=repository, path=path))
                        continue
                    if mode == "120000":
                        gaps.append(dict(code="symlink_omitted", repository=repository, path=path))
                        continue
                    if mode not in ("100644", "100755"):
                        gaps.append(dict(code="not_regular_source", repository=repository, path=path))
                        continue
                    if (name.startswith(".") or any(s in path.lower() for s in sensitive)
                            or not any(fnmatch.fnmatchcase(path, p) for p in include)):
                        continue
                    info = objects.info(child)
                    if info is None:
                        gaps.append(dict(code="object_unavailable", repository=repository, path=path))
                        continue
                    if info[1] > limits.max_file_bytes:
                        gaps.append(dict(code="file_limit", repository=repository, path=path))
                        continue
                    budget(info[1])
                    data_ = objects.contents(child, "blob")
                    if data_ is None:
                        gaps.append(dict(code="object_unavailable", repository=repository, path=path))
                        continue
                    if data_.startswith(LFS):
                        gaps.append(dict(code="lfs_pointer_omitted", repository=repository, path=path))
                        continue
                    if b"\0" in data_:
                        gaps.append(dict(code="binary_omitted", repository=repository, path=path))
                        continue
                    yield path, child, data_
        finally:
            objects.close()
