"""Release verification: a release that differs from its manifest must never be staged or run."""

import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
import zipfile

from tools.agent_service.box import release as rel

LOCK = "infra/agent_service/requirements.lock"


def _wheel(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, data in files.items():
            z.writestr(name, data)
    return buf.getvalue()


class ReleaseTree(unittest.TestCase):
    """A minimal release directory built the way release.build lays it out."""

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: __import__("shutil").rmtree(self.root, ignore_errors=True))
        wheel = _wheel({"demo/__init__.py": b"VALUE = 1\n"})
        self.wheel_sha = hashlib.sha256(wheel).hexdigest()
        files = {
            "app/src/agent_service/__init__.py": b"",
            "app/tools/agent_service/box/bootstrap.py": b"# bootstrap\n",
            f"app/{LOCK}": f"demo==1.0 \\\n    --hash=sha256:{self.wheel_sha}\n".encode(),
        }
        for path, data in files.items():
            (self.root / path).parent.mkdir(parents=True, exist_ok=True)
            (self.root / path).write_bytes(data)
        (self.root / "box").write_bytes(files["app/tools/agent_service/box/bootstrap.py"])
        (self.root / "wheels").mkdir()
        (self.root / "wheels" / "demo-1.0-py3-none-any.whl").write_bytes(wheel)
        self.manifest = {
            "format": rel.FORMAT, "name": "agent-service-test", "release_id": "0.0.0+gtest",
            "code": {"commit": "a" * 40},
            "files": {p: hashlib.sha256(d).hexdigest() for p, d in files.items()},
            "dependencies": {"lock": LOCK, "wheels": {"demo-1.0-py3-none-any.whl": self.wheel_sha}},
        }
        self.write_manifest()

    def write_manifest(self):
        (self.root / "manifest.json").write_bytes(rel.canonical_json(self.manifest))

    def rejected(self, code):
        with self.assertRaises(rel.ReleaseError) as ctx:
            rel.verify_tree(self.root)
        self.assertEqual(ctx.exception.code, code)

    def test_intact_release_is_verified_with_its_manifest_digest(self):
        manifest, digest = rel.verify_tree(self.root)
        self.assertEqual(manifest["name"], "agent-service-test")
        self.assertEqual(digest, hashlib.sha256((self.root / "manifest.json").read_bytes()).hexdigest())

    def test_modified_source_file_is_rejected(self):
        (self.root / "app/src/agent_service/__init__.py").write_bytes(b"import os\n")
        self.rejected("release_file_modified")

    def test_file_not_in_manifest_is_rejected(self):
        (self.root / "app/src/agent_service/extra.py").write_bytes(b"")
        self.rejected("unexpected_release_file")

    def test_missing_file_is_rejected(self):
        (self.root / "app/src/agent_service/__init__.py").unlink()
        self.rejected("missing_release_file")

    def test_replaced_installer_entry_is_rejected(self):
        (self.root / "box").write_bytes(b"# something else\n")
        self.rejected("release_file_modified")

    def test_wheel_outside_the_lock_is_rejected_even_if_the_manifest_lists_it(self):
        other = _wheel({"demo/__init__.py": b"VALUE = 2\n"})
        (self.root / "wheels" / "demo-1.0-py3-none-any.whl").write_bytes(other)
        self.manifest["dependencies"]["wheels"]["demo-1.0-py3-none-any.whl"] = hashlib.sha256(other).hexdigest()
        self.write_manifest()
        self.rejected("wheel_not_in_lock")

    def test_unknown_manifest_format_is_rejected(self):
        self.manifest["format"] = "agent-service-release-9"
        self.write_manifest()
        self.rejected("unknown_release_format")

    @unittest.skipIf(os.name == "nt", "symlinks need privileges on Windows")
    def test_symlink_in_app_is_rejected(self):
        (self.root / "app/src/link.py").symlink_to(self.root / "app/src/agent_service/__init__.py")
        self.rejected("unexpected_file_type")

    def test_bytecode_caches_are_ignored(self):
        cache = self.root / "app/src/agent_service/__pycache__"
        cache.mkdir()
        (cache / "x.cpython-312.pyc").write_bytes(b"\0")
        rel.verify_tree(self.root)


class Lock(unittest.TestCase):
    def test_requirement_without_hash_is_rejected(self):
        with self.assertRaises(rel.ReleaseError) as ctx:
            rel.lock_hashes("demo==1.0\nother==2.0 --hash=sha256:" + "b" * 64 + "\n")
        self.assertEqual(ctx.exception.code, "lock_malformed")

    def test_several_platform_hashes_per_requirement(self):
        pins = rel.lock_hashes("demo==1.0 \\\n    --hash=sha256:" + "a" * 64 + " \\\n    --hash=sha256:" + "b" * 64 + "\n")
        self.assertEqual(pins, {"demo": ("1.0", {"a" * 64, "b" * 64})})


class Wheels(unittest.TestCase):
    def test_wheel_member_escaping_site_packages_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-1.0-py3-none-any.whl"
            path.write_bytes(_wheel({"../evil.py": b""}))
            with self.assertRaises(rel.ReleaseError) as ctx:
                rel.install_wheels([path], Path(tmp) / "site")
            self.assertEqual(ctx.exception.code, "unsafe_wheel_member")
            self.assertFalse((Path(tmp) / "evil.py").exists())

    def test_data_purelib_goes_to_site_packages_and_scripts_are_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "pkg-1.0-py3-none-any.whl"
            path.write_bytes(_wheel({"pkg-1.0.data/purelib/pkg/mod.py": b"X = 1\n",
                                     "pkg-1.0.data/scripts/pkg-cli": b"#!/bin/sh\n", "pkg/__init__.py": b""}))
            site = Path(tmp) / "site"
            rel.install_wheels([path], site)
            self.assertEqual((site / "pkg" / "mod.py").read_bytes(), b"X = 1\n")
            self.assertFalse(any(p.name == "pkg-cli" for p in site.rglob("*")))


if __name__ == "__main__":
    unittest.main()
