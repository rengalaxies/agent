"""Durable state: schema versions on disk, verified backups, restore.

What is backed up: the service queue (``service/service.sqlite``: events,
jobs, publication intents with comment IDs, append-only history, notices,
reconciliation checkpoints) and the graph store (``core/graph.sqlite3``:
contexts, proposals, graph, source versions), plus the owner's box.yaml and
the generated configuration. SQLite files are copied with the online backup
API, so a running service yields a consistent copy of each database.

Not backed up: Git mirrors (re-cloned from the source), secrets.env (keep it
in the company's secret store), the release itself (immutable, re-stageable).

A restore never deletes the current databases before the replacement is in
place: it copies and checks the backup next to them, records the swap in
``<state>/.restore.json``, renames the current files aside, renames the
copies in, checks the row counts and only then drops the old files. Any
failure, or a box run after a killed restore, puts the old set back
(``recover``). The service refuses to start while the marker exists, so it
never opens a half-restored state or creates an empty queue in its place.
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
SIDECARS = ("", "-wal", "-shm", "-journal")  # a WAL file can hold committed rows: it moves with its database
FORMAT = "agent-service-backup-1"
MARKER = ".restore.json"


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
    try:
        return _create(layout, tmp, name, label, release)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)  # a full disk must not also keep a half-written copy
        raise


def _create(layout: Layout, tmp: Path, name: str, label: str, release: dict | None) -> dict:
    files = {}
    for key, rel in DATABASES.items():
        src = layout.state / rel
        if src.is_file():
            _copy_db(src, tmp / "state" / rel)
            files[f"state/{rel.as_posix()}"] = None
    identity = layout.state / ".box-state.json"
    if identity.is_file():
        (tmp / "state").mkdir(exist_ok=True)
        shutil.copy2(identity, tmp / "state" / identity.name)
        files[f"state/{identity.name}"] = None
    bindings = layout.bindings(release["name"]) if release else None
    for src, rel in ((layout.config, "config/box.yaml"),
                     (bindings and bindings / "service.json", "config/service.json"),
                     (bindings and bindings / "policy.json", "config/policy.json")):
        if src and src.is_file():
            (tmp / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, tmp / rel)
            files[rel] = None
    for rel in files:
        files[rel] = _sha(tmp / rel)
        if rel in {f"state/{r.as_posix()}" for r in DATABASES.values()} and not _integrity(tmp / rel):
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
    if meta.get("name") != name or not isinstance(meta.get("files"), dict):
        raise BackupError("backup_manifest_invalid")
    allowed = {f"state/{r.as_posix()}" for r in DATABASES.values()} | {
        "state/.box-state.json", "config/box.yaml", "config/service.json", "config/policy.json"}
    for rel, digest in meta["files"].items():
        if rel not in allowed:
            raise BackupError("unsafe_backup_member")
        path = root / rel
        if not path.is_file() or _sha(path) != digest:
            raise BackupError("backup_file_modified", rel)
        if rel in {f"state/{r.as_posix()}" for r in DATABASES.values()} and not _integrity(path):
            raise BackupError("backup_integrity_failed", rel)
    return meta


def restore_unfinished(state: Path) -> bool:
    return (state / MARKER).is_file()


def _fsync(path: Path):
    with open(path, "r+b") as f:  # Windows refuses fsync on a read-only handle
        os.fsync(f.fileno())


def _write_marker(state: Path, value: dict):
    tmp = state / f"{MARKER}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, state / MARKER)


def _entries(state: Path) -> list[dict]:
    """Every database file and sidecar the restore replaces, with where it goes aside and where its copy waits."""
    out = []
    for rel in DATABASES.values():
        target = state / rel
        for suffix in SIDECARS:
            out.append({"path": f"{rel.as_posix()}{suffix}",
                        "aside": f"{rel.parent.as_posix()}/.{target.name}{suffix}.pre-restore",
                        "staged": f"{rel.parent.as_posix()}/.{target.name}.restore" if suffix == "" else None})
    out.append({"path": ".box-state.json", "aside": ".box-state.json.pre-restore",
                "staged": ".box-state.json.restore"})
    return out


def recover(layout: Layout) -> dict | None:
    """Finish what a killed or failed restore left: the old set back, or the verified new one kept."""
    state = layout.state
    try:
        marker = json.loads((state / MARKER).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError:
        marker = {"phase": "swapping", "existed": [e["path"] for e in _entries(state)]}
    entries = _entries(state)
    if marker.get("phase") == "committing":  # the new set was in place and counted: only cleanup was left
        for e in entries:
            (state / e["aside"]).unlink(missing_ok=True)
        outcome = "kept_restored_state"
    else:
        existed = set(marker.get("existed", []))
        for e in entries:
            target, aside = state / e["path"], state / e["aside"]
            if aside.exists():
                os.replace(aside, target)
            elif e["path"] not in existed:
                target.unlink(missing_ok=True)  # a copy moved in where nothing was before
        outcome = "returned_previous_state"
    for e in entries:
        if e["staged"]:
            (state / e["staged"]).unlink(missing_ok=True)
    (state / MARKER).unlink()
    return {"backup": marker.get("backup"), "outcome": outcome}


def restore(layout: Layout, name: str, *, chown=None, fault=None) -> dict:
    """Replace the databases with the backup's (service must be stopped). Config files are not touched.

    ``fault(point)`` is a test hook called at "staged", "aside" and "swapped".
    """
    fault = fault or (lambda point: None)
    meta = verify(layout, name)
    root = layout.backups / name
    state = layout.state
    recover(layout)
    entries = _entries(state)
    staged = []
    try:  # 1. copies next to the targets; the current databases are not touched yet
        for rel in DATABASES.values():
            source = root / "state" / rel
            if source.is_file():
                target = state / rel
                target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                tmp = target.with_name(f".{target.name}.restore")
                staged.append(tmp)
                shutil.copyfile(source, tmp)
                os.chmod(tmp, 0o600)
                _fsync(tmp)
                if _sha(tmp) != meta["files"][f"state/{rel.as_posix()}"] or not _integrity(tmp):
                    raise BackupError("restore_copy_differs", rel.as_posix())
        identity = root / "state/.box-state.json"
        if identity.is_file():
            tmp = state / ".box-state.json.restore"
            staged.append(tmp)
            shutil.copyfile(identity, tmp)
            os.chmod(tmp, 0o600)
            _fsync(tmp)
            if _sha(tmp) != meta["files"]["state/.box-state.json"]:
                raise BackupError("restore_copy_differs", ".box-state.json")
        fault("staged")
        _write_marker(state, {"backup": name, "phase": "swapping",
                              "existed": [e["path"] for e in entries if (state / e["path"]).exists()]})
    except BaseException:
        for tmp in staged:
            tmp.unlink(missing_ok=True)
        raise
    try:  # 2. renames only: no data is copied, so a full disk cannot stop it half way
        for e in entries:
            if (state / e["path"]).exists():
                os.replace(state / e["path"], state / e["aside"])
        fault("aside")
        for e in entries:
            if e["staged"] and (state / e["staged"]).exists():
                os.replace(state / e["staged"], state / e["path"])
                if chown:
                    chown(state / e["path"])
                fault("file:" + e["path"])
        fault("swapped")
        if counts(state) != meta["counts"]:
            raise BackupError("restore_counts_differ")
        _write_marker(state, {"backup": name, "phase": "committing"})
    except BaseException:
        recover(layout)
        raise
    recover(layout)  # 3. drop the old files
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
