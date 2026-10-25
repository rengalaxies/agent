"""Shared host lock order: workload -> operator runtime guard -> session/SQLite."""

from contextlib import contextmanager
import os
from pathlib import Path
import time

if os.name == "posix":
    import fcntl
else:  # Windows development host
    import msvcrt


@contextmanager
def locked(path, nonblocking=False):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as handle:
        if os.name == "posix":
            fcntl.flock(handle, fcntl.LOCK_EX | (fcntl.LOCK_NB if nonblocking else 0))
        else:
            while True:
                try:
                    os.lseek(handle.fileno(), 0, os.SEEK_SET)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if nonblocking:
                        raise BlockingIOError("locked") from None
                    time.sleep(0.02)
        try:
            yield
        finally:
            if os.name == "posix":
                fcntl.flock(handle, fcntl.LOCK_UN)
            else:
                os.lseek(handle.fileno(), 0, os.SEEK_SET)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
