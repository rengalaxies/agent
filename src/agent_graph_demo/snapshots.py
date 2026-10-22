"""Immutable byte snapshots and stable working read grants, separate from runtime."""

import hashlib
import json
import os
from pathlib import Path
import shutil

from examples.agent_graph_demo.scenarios import REPOSITORIES, REQUIREMENT, sources
from examples.agent_graph_demo.oracle import DATASET_SHA256
from .contracts import CORE_SHA, PROFILE, DemoError, canonical, digest


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w") as out:
        out.write(canonical(value) + "\n")
        out.flush()
        os.fsync(out.fileno())
    os.replace(temp, path)
    fd = os.open(path.parent, os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class Snapshots:
    def __init__(self, root, product_sha):
        self.root, self.product_sha = Path(root), product_sha

    def session_root(self, sid):
        return self.root / "sessions" / sid

    def create(self, sid):
        root = self.session_root(sid)
        root.mkdir(parents=True, mode=0o700)
        for version in ("A", "B", "D", "E"):
            data = sources(version)
            repos = []
            for repo, service in REPOSITORIES.items():
                files = [
                    dict(
                        path=k.split("/", 1)[1],
                        sha256=hashlib.sha256(v.encode()).hexdigest(),
                    )
                    for k, v in sorted(data.items())
                    if k.startswith(repo + "/")
                ]
                repos.append(
                    dict(id=repo, service=service, revision=digest(files), files=files)
                )
            m = dict(
                schema_version=1,
                scenario_version=version,
                product_sha=self.product_sha,
                extractor_profile=PROFILE,
                core_sha=CORE_SHA,
                dataset_sha256=DATASET_SHA256,
                repositories=repos,
            )
            m["manifest_sha256"] = digest(m)
            dest = root / "snapshots" / version
            for name, text in data.items():
                f = dest / "corpus" / name
                f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text(text)
                f.chmod(0o444)
            atomic_json(dest / "manifest.json", m)
            (dest / "manifest.json").chmod(0o444)
        self.materialize(sid, "A")
        return self.manifest(sid, "A")

    def manifest(self, sid, version):
        root = self.session_root(sid) / "snapshots" / version
        m = json.loads((root / "manifest.json").read_text())
        if (
            digest({k: v for k, v in m.items() if k != "manifest_sha256"})
            != m["manifest_sha256"]
        ):
            raise DemoError("snapshot_manifest_changed")
        expected = {}
        for repo in m["repositories"]:
            for f in repo["files"]:
                expected[f"{repo['id']}/{f['path']}"] = f["sha256"]
        actual = {
            str(f.relative_to(root / "corpus")): hashlib.sha256(
                f.read_bytes()
            ).hexdigest()
            for f in (root / "corpus").rglob("*")
            if f.is_file()
        }
        if actual != expected or any(
            f.is_symlink() for f in (root / "corpus").rglob("*")
        ):
            raise DemoError("snapshot_bytes_changed")
        return m

    def materialize(self, sid, version):
        m = self.manifest(sid, version)
        root = self.session_root(sid)
        work = root / "work"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(root / "snapshots" / version / "corpus", work)
        for f in work.rglob("*"):
            if f.is_file():
                f.chmod(0o600)
        policy = dict(
            installation_id="http-demo",
            environment=sid,
            subject="demo-operator",
            capabilities=[
                "read_context",
                "maintain",
                "propose",
                "correct",
                "report_check",
            ],
            repositories=[
                dict(
                    id=r["id"],
                    service=r["service"],
                    root=str(work / r["id"]),
                    revision=r["revision"],
                )
                for r in m["repositories"]
            ],
            addresses=[
                dict(service="Orders", base_url="http://orders:8000"),
                dict(service="Status", base_url="http://status:8000"),
            ],
            requirements=[
                dict(
                    id="reporting-complete",
                    repository="reporting",
                    path="requirement.md",
                    sha256=hashlib.sha256(REQUIREMENT.encode()).hexdigest(),
                    issuer="demo-owner",
                    service="Orders",
                    path_template="/orders",
                    consumer="Reporting",
                    predicate="complete_collection",
                )
            ],
            model=None,
        )
        atomic_json(root / "policy.json", policy)
        return m
