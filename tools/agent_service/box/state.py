"""Durable state: schema versions on disk, verified backups, restore.

What is backed up: the service queue (``service/service.sqlite``: events,
jobs, publication intents with comment IDs, append-only history, notices,
reconciliation checkpoints) and the graph store (``core/graph.sqlite3``:
contexts, proposals, graph, source versions), plus the owner's box.yaml and
the generated configuration. SQLite files are copied with the online backup
API, so a running service yields a consistent copy of each database.

Not backed up: Git mirrors (re-cloned from the source), secrets.env (keep it
in the company's secret store), the release itself (immutable, re-stageable).
"""

from __future__ import annotations

import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3

from .layout import Layout

DATABASES = {"service": Path("service") / "service.sqlite", "graph": Path("core") / "graph.sqlite3"}
FORMAT = "agent-service-backup-1"


class BackupError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code} {detail}".strip())
        self.code, self.detail = code, detail


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30)


def schemas(state: Path) -> dict:
    """{"service_store": int|None, "graph_store": int|None} read from the files themselves."""
    out = {"service_store": None, "graph_store": None}
    service, graph = state / DATABASES["service"], state / DATABASES["graph"]
    if service.is_file():
        c = _ro(service)
        try:
            row = c.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
            out["service_store"] = int(row[0]) if row else None
        finally:
            c.close()
    if graph.is_file():
        c = _ro(graph)
        try:
            row = c.execute("SELECT value FROM meta WHERE key='store_schema'").fetchone()
            out["graph_store"] = int(row[0]) if row else 1
        finally:
            c.close()
    return out


def counts(state: Path) -> dict:
    """Row counts that a restore must reproduce (no contents)."""
    out = {}
    service = state / DATABASES["service"]
    if service.is_file():
        c = _ro(service)
        try:
            for table in ("events", "resources", "jobs", "intents", "history"):
                out[table] = c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
            out["delivered_comments"] = c.execute(
                "SELECT count(*) FROM resources WHERE comment_id IS NOT NULL").fetchone()[0]
        finally:
            c.close()
    graph = state / DATABASES["graph"]
    if graph.is_file():
        c = _ro(graph)
        try:
            for table in ("artifacts", "proposals"):
                out[f"graph_{table}"] = c.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        finally:
            c.close()
    return out


def compatible(release_state: dict, disk: dict) -> tuple[bool, list[str]]:
    """Whether a release (manifest contracts.state) opens the state on disk without restoring a backup."""
    problems = []
    service, graph = release_state["service_store"], release_state["graph_store"]
    if disk["service_store"] is not None and disk["service_store"] != service["version"]:
        problems.append(f"service_store {disk['service_store']} on disk, release opens only {service['version']}")
    if disk["graph_store"] is not None and disk["graph_store"] > graph["version"]:
        problems.append(f"graph_store {disk['graph_store']} on disk, release opens up to {graph['version']}")
    return not problems, problems


def _copy_db(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    source = _ro(src)
    target = sqlite3.connect(dst)
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()


def _integrity(path: Path) -> bool:
    c = _ro(path)
    try:
        return c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        c.close()


def create(layout: Layout, *, label: str, release: dict | None) -> dict:
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    if not re.fullmatch(r"[a-z0-9-]{1,40}", label):
        raise BackupError("invalid_label")
    name = f"{stamp}-{label}"
    layout.backups.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = layout.backups / f".{name}.tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(mode=0o700)
    files = {}
    for key, rel in DATABASES.items():
        src = layout.state / rel
        if src.is_file():
            _copy_db(src, tmp / "state" / rel)
            files[f"state/{rel.as_posix()}"] = None
    for src, rel in ((layout.config, "config/box.yaml"), (layout.generated / "service.json", "config/service.json"),
                     (layout.generated / "policy.json", "config/policy.json")):
        if src.is_file():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tmp / rel)
            files[rel] = None
    for rel in files:
        files[rel] = _sha(tmp / rel)
        if rel.startswith("state/") and not _integrity(tmp / rel):
            raise BackupError("backup_integrity_failed", rel)
    meta = {"format": FORMAT, "name": name, "label": label,
            "created_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "release": release, "schemas": schemas(tmp / "state"), "counts": counts(tmp / "state"), "files": files}
    (tmp / "backup.json").write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    for dirpath, _, filenames in os.walk(tmp):
        for f in filenames:
            os.chmod(Path(dirpath) / f, 0o600)
    tmp.rename(layout.backups / name)
    return meta


def listing(layout: Layout) -> list[dict]:
    out = []
    if layout.backups.is_dir():
        for d in sorted(layout.backups.iterdir()):
            if d.name.startswith(".") or not (d / "backup.json").is_file():
                continue
            out.append(json.loads((d / "backup.json").read_text(encoding="utf-8")))
    return out


def verify(layout: Layout, name: str) -> dict:
    root = layout.backups / name
    if not re.fullmatch(r"[0-9TZ]+-[a-z0-9-]+", name) or not (root / "backup.json").is_file():
        raise BackupError("backup_not_found", name)
    meta = json.loads((root / "backup.json").read_text(encoding="utf-8"))
    if meta.get("format") != FORMAT:
        raise BackupError("unknown_backup_format")
    for rel, digest in meta["files"].items():
        path = root / rel
        if not path.is_file() or _sha(path) != digest:
            raise BackupError("backup_file_modified", rel)
        if rel.startswith("state/") and not _integrity(path):
            raise BackupError("backup_integrity_failed", rel)
    return meta


def restore(layout: Layout, name: str, *, chown=None) -> dict:
    """Replace the databases with the backup's (service must be stopped). Config files are not touched."""
    meta = verify(layout, name)
    root = layout.backups / name
    for key, rel in DATABASES.items():
        target = layout.state / rel
        for suffix in ("", "-wal", "-shm", "-journal"):
            Path(f"{target}{suffix}").unlink(missing_ok=True)
        source = root / "state" / rel
        if source.is_file():
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            tmp = target.with_name(f".{target.name}.restore")
            shutil.copyfile(source, tmp)
            os.chmod(tmp, 0o600)
            tmp.replace(target)
            if chown:
                chown(target)
    restored = counts(layout.state)
    expected = {k: v for k, v in meta["counts"].items()}
    if restored != expected:
        raise BackupError("restore_counts_differ")
    return meta


def prune(layout: Layout, keep: int, protect: set[str]) -> list[str]:
    """Delete the oldest backups beyond ``keep``; never the protected ones (rollback points)."""
    names = [m["name"] for m in listing(layout)]
    removed = []
    for name in names[:-keep] if len(names) > keep else []:
        if name in protect:
            continue
        shutil.rmtree(layout.backups / name)
        removed.append(name)
    return removed
