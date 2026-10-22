"""Shared host lock order: workload -> operator runtime guard -> session/SQLite."""

from contextlib import contextmanager
import fcntl
from pathlib import Path


@contextmanager
def locked(path, nonblocking=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        try:
            yield
        finally:
            fcntl.flock(handle, fcntl.LOCK_UN)
