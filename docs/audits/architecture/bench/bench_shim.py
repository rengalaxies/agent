"""Windows shim for benchmarking the unmodified agent_graph core.

Replaces only what Windows cannot do: openat/O_NOFOLLOW reads, the 0700 mode
check and fcntl.flock. Parsing, hashing, JSON, SQLite and engine logic run as-is.
"""
import os
import pathlib
import stat
import sys
import types

if sys.platform == "win32":
    fcntl = types.ModuleType("fcntl")
    fcntl.LOCK_EX, fcntl.LOCK_NB, fcntl.LOCK_UN = 2, 4, 8
    fcntl.flock = lambda fd, op: None
    sys.modules["fcntl"] = fcntl

    import agent_graph.sources as sources
    import agent_graph.store as store
    from agent_graph.contracts import GraphError

    def read_relative(root, relative, limit):
        parts = pathlib.Path(relative).parts
        if not parts or pathlib.Path(relative).is_absolute() or any(p in ("..", ".") for p in parts):
            raise GraphError("invalid_source_path")
        path = pathlib.Path(root, relative)
        if not stat.S_ISREG(os.lstat(path).st_mode):
            raise GraphError("not_regular_source")
        with open(path, "rb") as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise GraphError("file_limit")
        return raw

    sources.read_relative = read_relative

    class PrivatePath(type(pathlib.Path())):
        def stat(self, *a, **k):
            s = super().stat(*a, **k)
            return os.stat_result((s.st_mode & ~0o077,) + tuple(s)[1:])

    store.Path = PrivatePath
