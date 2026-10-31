"""Pinned agent-service release: build from one Git commit, verify before use.

Standard library only: the installer imports this module with the host
Python before any dependency exists.

A release is one reproducible archive:

    agent-service-<version>-g<sha12>-<platform>/
      box              installer entry (copy of app/tools/agent_service/box/bootstrap.py)
      manifest.json    commit, every file hash, wheel hashes, contract and state versions
      app/...          blobs of the allowlisted paths read from the commit (no working tree)
      wheels/*.whl     dependencies, each listed in infra/agent_service/requirements.lock

Identity is the archive sha256 plus the commit SHA in the manifest, never a tag.
Build:

    python tools/agent_service/box/release.py build --commit HEAD --platform linux-x86_64-cp312 --output dist
"""

from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

FORMAT = "agent-service-release-1"
REPOSITORY = "github.com/rengalaxies/agent"
# Everything the service, its installer and its offline smoke need, nothing else.
APP_PATHS = (
    "src/agent_graph",
    "src/agent_service",
    "constitutions/agent-service-v1.yaml",
    "schemas/agent-graph-output-2.json",
    "examples/orders_reporting",
    "tools/agent_service/box",
    "infra/agent_service",
)
LOCK = "infra/agent_service/requirements.lock"
VERSION_FILE = "infra/agent_service/VERSION"
PLATFORMS = {
    "linux-x86_64-cp312": dict(python="3.12", pip=["manylinux_2_28_x86_64", "manylinux_2_17_x86_64",
                                                   "manylinux2014_x86_64"]),
    "win-amd64-cp314": dict(python="3.14", pip=["win_amd64"]),
}
SHA = re.compile(r"^[0-9a-f]{40}$")
LOCK_LINE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._-]*)==([^\s\\]+)")
LOCK_HASH = re.compile(r"--hash=sha256:([0-9a-f]{64})")


class ReleaseError(Exception):
    """A release that must not be installed or run; ``code`` is safe to print."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(code if not detail else f"{code}: {detail}")
        self.code = code
        self.detail = detail


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def lock_hashes(text: str) -> dict[str, tuple[str, set[str]]]:
    """{canonical name: (version, {sha256})} from a --require-hashes lock."""
    out: dict[str, tuple[str, set[str]]] = {}
    current = None
    for line in text.splitlines():
        line = line.split("#", 1)[0] if not line.lstrip().startswith("--hash") else line
        m = LOCK_LINE.match(line.strip())
        if m:
            current = re.sub(r"[-_.]+", "-", m.group(1)).lower()
            out[current] = (m.group(2), set())
        for h in LOCK_HASH.findall(line):
            if current is None:
                raise ReleaseError("lock_malformed")
            out[current][1].add(h)
    if not out or any(not hashes for _, hashes in out.values()):
        raise ReleaseError("lock_malformed", "every requirement needs a sha256")
    return out


# -- build ---------------------------------------------------------------------


def _git(repo: Path, *args, input: bytes | None = None) -> bytes:
    return subprocess.run(["git", "-C", str(repo), "-c", "core.autocrlf=false", *args], input=input,
                          stdout=subprocess.PIPE, check=True).stdout


def commit_blobs(repo: Path, commit: str) -> dict[str, tuple[int, bytes]]:
    """{path: (mode, bytes)} of APP_PATHS exactly as stored in the commit (no filters, no working tree)."""
    listing = _git(repo, "ls-tree", "-r", "-z", "--full-tree", commit, "--", *APP_PATHS)
    entries = []
    for item in listing.split(b"\0"):
        if not item:
            continue
        meta, path = item.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        path = path.decode("utf-8")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise ReleaseError("unsupported_tree_entry", f"{path} {mode} {kind}")
        if "__pycache__" in path.split("/") or path.startswith("tools/agent_service/box/tests/"):
            continue  # caches and the box's own unit tests are not part of a release
        entries.append((path, int(mode, 8), oid))
    present = {p for p, _, _ in entries}
    for required in APP_PATHS:
        if not any(p == required or p.startswith(required + "/") for p in present):
            raise ReleaseError("missing_release_path", required)
    batch = _git(repo, "cat-file", "--batch", input="".join(oid + "\n" for _, _, oid in entries).encode())
    blobs, pos = {}, 0
    for path, mode, oid in entries:
        header_end = batch.index(b"\n", pos)
        got_oid, kind, size = batch[pos:header_end].decode().split()
        if got_oid != oid or kind != "blob":
            raise ReleaseError("git_protocol_error")
        start = header_end + 1
        blobs[path] = (mode, batch[start:start + int(size)])
        pos = start + int(size) + 1
    return blobs


def introspect(app: Path, python: str) -> dict:
    """Versions the code itself reports: core identity, constitution, schema and state versions."""
    script = r"""
import json, sys
from pathlib import Path
app = Path(sys.argv[1])
sys.path[:0] = [str(app / "src"), str(app)]
import agent_graph
from agent_graph import constitution, output_contracts, store
from agent_service import queue
_, constitution_version = constitution.load(app / "constitutions" / "agent-service-v1.yaml")
print(json.dumps(dict(core=agent_graph.core_identity(), constitution_version=constitution_version,
                      output_schema_version=output_contracts.SCHEMA_VERSION,
                      state=dict(service_store=queue.SCHEMA_VERSION, graph_store=store.STORE_SCHEMA))))
"""
    out = subprocess.run([python, "-I", "-B", "-c", script, str(app)], stdout=subprocess.PIPE, check=True)
    return json.loads(out.stdout)


def contracts_of(app: Path, python: str) -> dict:
    found = introspect(app, python)
    return {
        "core": found["core"],
        "output_schema_version": found["output_schema_version"],
        "constitution": {"path": "constitutions/agent-service-v1.yaml", "version_id": found["constitution_version"]},
        # The service store refuses any other version; the graph store migrates older files up and
        # refuses newer ones (agent_graph.store._migrate). The installer decides rollback from these.
        "state": {"service_store": {"version": found["state"]["service_store"], "opens": "equal"},
                  "graph_store": {"version": found["state"]["graph_store"], "opens": "older_or_equal"}},
        "recovery": {"protocol": 1, "state_semantics": {
            "extractor_profile": found["core"]["profile"], "graph_schema": found["core"]["schema"],
            "output_schema": found["core"]["output_schema_version"]}},
    }


def fetch_wheels(lock_path: Path, platform: str, dest: Path, wheelhouse: Path | None) -> dict[str, str]:
    """Wheels for ``platform``, every one checked against the lock; returns {file: sha256}."""
    pins = lock_hashes(lock_path.read_text(encoding="utf-8"))
    dest.mkdir(parents=True)
    if wheelhouse:
        for wheel in sorted(wheelhouse.glob("*.whl")):
            shutil.copy2(wheel, dest / wheel.name)
    else:
        spec = PLATFORMS[platform]
        cmd = [sys.executable, "-m", "pip", "download", "--quiet", "--disable-pip-version-check",
               "--require-hashes", "--no-deps", "--only-binary=:all:", "--implementation", "cp",
               "--python-version", spec["python"], "-d", str(dest), "-r", str(lock_path)]
        for tag in spec["pip"]:
            cmd += ["--platform", tag]
        subprocess.run(cmd, check=True)
    wheels = {}
    seen = set()
    for wheel in sorted(dest.iterdir()):
        name = re.sub(r"[-_.]+", "-", wheel.name.split("-")[0]).lower()
        digest = sha256_file(wheel)
        if name not in pins or digest not in pins[name][1]:
            wheel.unlink()  # a wheelhouse may hold other platforms' files; keep only locked ones
            continue
        if name in seen:
            raise ReleaseError("duplicate_wheel", name)
        seen.add(name)
        wheels[wheel.name] = digest
    missing = sorted(set(pins) - seen)
    if missing:
        raise ReleaseError("missing_wheels", ",".join(missing))
    return wheels


def _tar_add(tar: tarfile.TarFile, name: str, data: bytes, mode: int, mtime: int):
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(data), mode, mtime
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    tar.addfile(info, io.BytesIO(data))


def build(repo: Path, commit: str, platform: str, output: Path, *, python: str = sys.executable,
          wheelhouse: Path | None = None) -> dict:
    if platform not in PLATFORMS:
        raise ReleaseError("unknown_platform", platform)
    sha = _git(repo, "rev-parse", "--verify", f"{commit}^{{commit}}").decode().strip()
    tree = _git(repo, "rev-parse", f"{sha}^{{tree}}").decode().strip()
    committed = int(_git(repo, "show", "-s", "--format=%ct", sha).decode().strip())
    blobs = commit_blobs(repo, sha)
    version = blobs[VERSION_FILE][1].decode().strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+([ab]\d+)?", version):
        raise ReleaseError("invalid_version", version)
    name = f"agent-service-{version}-g{sha[:12]}-{platform}"
    with tempfile.TemporaryDirectory() as tmp:
        app = Path(tmp) / "app"
        for path, (_, data) in blobs.items():
            target = app / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        contracts = contracts_of(app, python)
        wheels = fetch_wheels(app / LOCK, platform, Path(tmp) / "wheels", wheelhouse)
        manifest = {
            "format": FORMAT,
            "release_id": f"{version}+g{sha[:12]}.{platform}",
            "name": name,
            "version": version,
            "platform": platform,
            "python": PLATFORMS[platform]["python"],
            "code": {"repository": REPOSITORY, "commit": sha, "tree": tree,
                     "committed_at": datetime.datetime.fromtimestamp(committed, datetime.timezone.utc)
                     .strftime("%Y-%m-%dT%H:%M:%SZ"), "paths": list(APP_PATHS)},
            "files": {f"app/{p}": sha256_bytes(d) for p, (_, d) in sorted(blobs.items())},
            "dependencies": {"lock": LOCK, "lock_sha256": sha256_bytes(blobs[LOCK][1]), "wheels": wheels},
            "contracts": contracts,
            "entrypoints": {"installer": "box", "service": "app/tools/agent_service/box/launch.py",
                            "smoke": "python -m agent_service smoke"},
        }
        manifest_bytes = canonical_json(manifest)
        output.mkdir(parents=True, exist_ok=True)
        archive = output / f"{name}.tar.gz"
        raw = io.BytesIO()
        with tarfile.open(fileobj=raw, mode="w", format=tarfile.PAX_FORMAT) as tar:
            bootstrap = blobs["tools/agent_service/box/bootstrap.py"][1]
            members = [("box", bootstrap, 0o755), ("manifest.json", manifest_bytes, 0o644)]
            members += [(f"app/{p}", d, 0o755 if m == 0o100755 else 0o644) for p, (m, d) in blobs.items()]
            members += [(f"wheels/{w}", (Path(tmp) / "wheels" / w).read_bytes(), 0o644) for w in wheels]
            for member, data, mode in sorted(members):
                _tar_add(tar, f"{name}/{member}", data, mode, committed)
        with open(archive, "wb") as f, gzip.GzipFile(filename="", mode="wb", fileobj=f, mtime=0) as gz:
            gz.write(raw.getvalue())
    digest = sha256_file(archive)
    (output / f"{name}.tar.gz.sha256").write_bytes(f"{digest}  {name}.tar.gz\n".encode())
    (output / f"{name}.manifest.json").write_bytes(manifest_bytes)
    return {"archive": str(archive), "archive_sha256": digest, "release_id": manifest["release_id"],
            "manifest_sha256": sha256_bytes(manifest_bytes), "commit": sha}


# -- verify --------------------------------------------------------------------


def load_manifest(root: Path) -> tuple[dict, str]:
    raw = (root / "manifest.json").read_bytes()
    try:
        manifest = json.loads(raw)
    except ValueError:
        raise ReleaseError("manifest_unreadable") from None
    if manifest.get("format") != FORMAT:
        raise ReleaseError("unknown_release_format", str(manifest.get("format")))
    if not SHA.fullmatch(manifest.get("code", {}).get("commit", "")):
        raise ReleaseError("manifest_without_commit")
    return manifest, sha256_bytes(raw)


def _walk(root: Path, top: str, ignore=("__pycache__",)):
    base = root / top
    if not base.exists():
        return
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in ignore]
        for d in dirnames:
            if (Path(dirpath) / d).is_symlink():
                raise ReleaseError("symlink_in_release", str(Path(dirpath, d).relative_to(root)))
        for f in filenames:
            p = Path(dirpath) / f
            if p.is_symlink() or not p.is_file():
                raise ReleaseError("unexpected_file_type", str(p.relative_to(root)))
            yield PurePosixPath(p.relative_to(root).as_posix()), p


def verify_tree(root: Path, *, wheels: bool = True) -> tuple[dict, str]:
    """Every app file and wheel matches the manifest and nothing else is there."""
    manifest, manifest_sha = load_manifest(root)
    expected = dict(manifest["files"])
    if wheels:
        expected.update({f"wheels/{w}": h for w, h in manifest["dependencies"]["wheels"].items()})
    actual = {}
    for top in ("app", "wheels") if wheels else ("app",):
        for rel, path in _walk(root, top):
            actual[str(rel)] = path
    extra = sorted(set(actual) - set(expected))
    missing = sorted(set(expected) - set(actual))
    if extra:
        raise ReleaseError("unexpected_release_file", extra[0])
    if missing:
        raise ReleaseError("missing_release_file", missing[0])
    for rel, digest in expected.items():
        if sha256_file(actual[rel]) != digest:
            raise ReleaseError("release_file_modified", rel)
    if (root / "box").exists() and sha256_file(root / "box") != manifest["files"]["app/tools/agent_service/box/bootstrap.py"]:
        raise ReleaseError("release_file_modified", "box")
    lock = root / "app" / manifest["dependencies"]["lock"]
    pins = lock_hashes(lock.read_text(encoding="utf-8"))
    if wheels:
        for wheel, digest in manifest["dependencies"]["wheels"].items():
            name = re.sub(r"[-_.]+", "-", wheel.split("-")[0]).lower()
            if name not in pins or digest not in pins[name][1]:
                raise ReleaseError("wheel_not_in_lock", wheel)
    return manifest, manifest_sha


def install_wheels(wheels: list[Path], site_packages: Path) -> list[str]:
    """Unpack hash-verified wheels into a venv's site-packages without pip or network.

    Only the parts the service needs: package files and ``.data/{purelib,platlib}``.
    Console scripts are skipped (the service runs with ``python -m``).
    """
    installed = []
    for wheel in wheels:
        with zipfile.ZipFile(wheel) as z:
            for info in z.infolist():
                name = PurePosixPath(info.filename)
                if name.is_absolute() or ".." in name.parts:
                    raise ReleaseError("unsafe_wheel_member", wheel.name)
                parts = name.parts
                if len(parts) > 2 and parts[0].endswith(".data"):
                    if parts[1] not in ("purelib", "platlib", "scripts"):
                        raise ReleaseError("unsupported_wheel_data", f"{wheel.name}:{parts[1]}")
                    if parts[1] == "scripts":
                        continue
                    parts = parts[2:]
                if info.is_dir():
                    continue
                target = site_packages.joinpath(*parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
        installed.append(wheel.name)
    return installed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Build or verify a pinned agent-service release.")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[3])
    b.add_argument("--commit", default="HEAD")
    b.add_argument("--platform", default="linux-x86_64-cp312", choices=sorted(PLATFORMS))
    b.add_argument("--output", type=Path, required=True)
    b.add_argument("--wheelhouse", type=Path, help="use these wheels instead of downloading (still hash-checked)")
    v = sub.add_parser("verify")
    v.add_argument("directory", type=Path, help="an extracted release directory")
    args = parser.parse_args(argv)
    try:
        if args.command == "build":
            result = build(args.repo, args.commit, args.platform, args.output, wheelhouse=args.wheelhouse)
        else:
            manifest, manifest_sha = verify_tree(args.directory)
            result = {"status": "VERIFIED", "release_id": manifest["release_id"], "manifest_sha256": manifest_sha,
                      "commit": manifest["code"]["commit"]}
    except ReleaseError as exc:
        print(json.dumps({"status": "REJECTED", "code": exc.code, "detail": exc.detail}))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
