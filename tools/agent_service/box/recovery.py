"""Recovery contract of the supported manager, not a promise about old CLIs.

Schema compatibility is checked separately. Semantics are opaque values compared
for equality; profile numbers have no ordering here. Unknown legacy releases fail
closed. The sole legacy adapter is the byte-verified published release14e.
"""

from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from . import release as rel
from .config import write_json

IDENTITY = ".box-state.json"
TRANSITION = ".box-recovery.json"
LEGACY_14E = "9fdd6e8aa48e5e09d803840ef262c1c3d57bb01af9c884a690f86a98888533a9"


def semantics(manifest: dict, manifest_sha: str) -> dict:
    contract = manifest.get("contracts", {}).get("recovery")
    if contract is not None:
        if (not isinstance(contract, dict) or contract.get("protocol") != 1
                or not isinstance(contract.get("state_semantics"), dict)
                or set(contract["state_semantics"]) != {"extractor_profile", "graph_schema", "output_schema"}
                or not all(isinstance(v, str) and v for v in contract["state_semantics"].values())):
            raise rel.ReleaseError("unknown_recovery_contract")
        return contract["state_semantics"]
    if manifest_sha == LEGACY_14E:
        core = manifest["contracts"]["core"]
        return {"extractor_profile": core["profile"], "graph_schema": core["schema"],
                "output_schema": core["output_schema_version"]}
    raise rel.ReleaseError("unknown_legacy_state_semantics")


def record(manifest: dict, manifest_sha: str) -> dict:
    return {"name": manifest["name"], "release_id": manifest["release_id"],
            "commit": manifest["code"]["commit"], "manifest_sha256": manifest_sha}


def read_identity(state: Path) -> dict | None:
    try:
        value = json.loads((state / IDENTITY).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError:
        raise rel.ReleaseError("state_identity_unreadable") from None
    if not isinstance(value, dict):
        raise rel.ReleaseError("state_identity_unreadable")
    if value.get("protocol") != 1 or not isinstance(value.get("semantics"), dict):
        raise rel.ReleaseError("state_identity_unreadable")
    return value


def identify(state: Path, manifest: dict, manifest_sha: str, *, reconcile=None, token=None) -> dict:
    previous = read_identity(state)
    if previous is None or previous.get("writer") != record(manifest, manifest_sha):
        previous = {}
    if reconcile is None:
        reconcile = previous.get("reconcile_required", False)
    if token is None:
        token = previous.get("recovery_token", "update")
    value = {"protocol": 1, "writer": record(manifest, manifest_sha),
             "semantics": semantics(manifest, manifest_sha), "reconcile_required": reconcile,
             "recovery_token": token}
    write_json(state / IDENTITY, value)
    return value


def adopt_legacy(state: Path, manifest: dict, manifest_sha: str):
    """Only bootstrap a known legacy state whose stored contexts agree with its profile.

    A state previously opened through an unsafe old CLI is not silently certified.
    This is an adapter for release14e, not arbitrary legacy provenance inference.
    """
    expected = semantics(manifest, manifest_sha)
    if manifest_sha != LEGACY_14E:
        raise rel.ReleaseError("unlabelled_state_provenance_unknown")
    path = state / "core/graph.sqlite3"
    if path.is_file():
        db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            for (raw,) in db.execute("SELECT data FROM artifacts"):
                profile = json.loads(raw).get("profile")
                if profile is not None and profile != expected["extractor_profile"]:
                    raise rel.ReleaseError("legacy_state_contains_other_profile")
        finally:
            db.close()
    identify(state, manifest, manifest_sha)


def pending(state: Path) -> dict | None:
    try:
        return json.loads((state / TRANSITION).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except ValueError:
        raise rel.ReleaseError("recovery_marker_unreadable") from None


def hold(state: Path, value: dict):
    write_json(state / TRANSITION, value)
    # The guarded supervisor runs as the service user. No secret values here.
    (state / TRANSITION).chmod(0o644)


def verify_backup(layout, meta: dict, manifest: dict, manifest_sha: str):
    from .state import BackupError

    if not backup_matches(meta, manifest, manifest_sha):
        raise BackupError("backup_release_mismatch")
    required = {"state/service/service.sqlite", "state/core/graph.sqlite3", "config/box.yaml",
                "config/service.json", "config/policy.json"}
    if not required <= set(meta["files"]):
        raise BackupError("backup_incomplete")
    root = layout.backups / meta["name"]
    identity = read_identity(root / "state")
    if identity is None:
        # Legacy backups are not rewritten to add an identity.
        if manifest_sha != LEGACY_14E:
            raise BackupError("backup_semantics_unknown")
        path = root / "state/core/graph.sqlite3"
        db = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
        try:
            if any(json.loads(row[0]).get("profile", semantics(manifest, manifest_sha)["extractor_profile"])
                   != semantics(manifest, manifest_sha)["extractor_profile"]
                   for row in db.execute("SELECT data FROM artifacts")):
                raise BackupError("backup_semantics_mismatch")
        finally:
            db.close()
    elif (identity["semantics"] != semantics(manifest, manifest_sha)
          or identity.get("writer") != record(manifest, manifest_sha)):
        raise BackupError("backup_semantics_mismatch")
    cfg = json.loads((root / "config/service.json").read_text(encoding="utf-8"))
    if ((cfg.get("analysis") or {}).get("code_version") != manifest["release_id"]
            or Path(cfg.get("state_path", "")).resolve() != (layout.state / "service/service.sqlite").resolve()
            or Path((cfg.get("core") or {}).get("state_dir", "")).resolve() != (layout.state / "core").resolve()
            or Path((cfg.get("core") or {}).get("policy_path", "")).resolve()
            != (layout.bindings(manifest["name"]) / "policy.json").resolve()):
        raise BackupError("backup_configuration_mismatch")


def restore_config(layout, meta: dict, manifest: dict):
    from .config import write_bytes

    root = layout.backups / meta["name"] / "config"
    for name in ("service.json", "policy.json"):
        write_bytes(layout.bindings(manifest["name"]) / name, (root / name).read_bytes(), 0o640)
    write_bytes(layout.config, (root / "box.yaml").read_bytes(), 0o644)
    write_bytes(layout.bindings(manifest["name"]) / "box.yaml", (root / "box.yaml").read_bytes(), 0o640)


def backup_matches(meta: dict, manifest: dict, manifest_sha: str) -> bool:
    saved = meta.get("release") or {}
    return (saved.get("name") == manifest["name"] and saved.get("manifest_sha256") == manifest_sha
            and saved.get("commit") == manifest["code"]["commit"])


def check_start(state: Path, manifest: dict, manifest_sha: str) -> dict:
    value = read_identity(state)
    if (value is None or value["semantics"] != semantics(manifest, manifest_sha)
            or value.get("writer") != record(manifest, manifest_sha)):
        raise rel.ReleaseError("state_semantics_mismatch")
    marker = state / TRANSITION
    if marker.exists():
        pending = json.loads(marker.read_text(encoding="utf-8"))
        if pending.get("phase") != "READY_TO_START" or pending.get("target") != record(manifest, manifest_sha):
            raise rel.ReleaseError("recovery_unfinished")
    return value
