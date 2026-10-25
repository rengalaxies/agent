"""Operating system differences in one place.

Linux is the service platform. Windows is a development host only: it has no
openat/O_NOFOLLOW and no POSIX mode bits, so its fallbacks check links and file
identity around the open and rely on NTFS ACLs of the user profile. They are
narrower than the POSIX path and are not a security boundary.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat

POSIX = os.name == "posix"

if POSIX:
    import fcntl
else:  # pragma: no cover - exercised on Windows development hosts
    import msvcrt

_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def lock_nonblocking(fd: int) -> None:
    """Exclusive advisory lock or BlockingIOError. Released when fd is closed."""
    if POSIX:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return
    try:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
    except OSError as exc:
        raise BlockingIOError(str(exc.errno)) from None


def private_directory(path: Path) -> bool:
    if path.is_symlink():
        return False
    if POSIX:
        return not path.stat().st_mode & 0o077
    return not path.lstat().st_file_attributes & _REPARSE


def open_lock_file(path: Path) -> int:
    flags = os.O_CREAT | os.O_RDWR | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    return os.open(path, flags, 0o600)


def _is_link(st) -> bool:
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & _REPARSE)


def read_regular(root: Path, parts: tuple[str, ...], limit: int, error) -> bytes:
    """Read root/parts without following links; `error(code)` builds the exception."""
    if POSIX:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = nxt
            final = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
        finally:
            os.close(fd)
    else:
        path = Path(root)
        if _is_link(os.lstat(path)):
            raise error("invalid_source_root")
        for part in parts:
            path = path / part
            if _is_link(os.lstat(path)):
                raise OSError("link_component")
        before = os.lstat(path)
        final = os.open(path, os.O_RDONLY | os.O_BINARY)
        after = os.fstat(final)
        if (before.st_ino, before.st_dev) != (after.st_ino, after.st_dev):
            os.close(final)
            raise error("source_changed_during_read")
    try:
        if not stat.S_ISREG(os.fstat(final).st_mode):
            raise error("not_regular_source")
        with os.fdopen(final, "rb", closefd=False) as stream:
            raw = stream.read(limit + 1)
        if len(raw) > limit:
            raise error("file_limit")
        return raw
    finally:
        os.close(final)
