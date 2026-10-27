"""provision.sh: the VM runs the 5A installer only from a verified archive and only once inputs exist.

The installer is replaced by a stub ``box`` inside a real tar.gz: the contract under test is the
script's (verify, extract, wait, call install then doctor, map exit codes), not box's. The network
boundary is cut with an unreachable proxy so a download attempt fails fast and deterministically.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
NAME = "agent-service-0.1.0-g0123456789ab-linux-x86_64-cp312"
URL = f"https://github.com/rengalaxies/agent/releases/download/t/{NAME}.tar.gz"
STUB = """#!/bin/bash
echo "$*" >> "$FAKE_BOX_LOG"
if [ "$1" = install ]; then exit "${FAKE_INSTALL_RC:-0}"; fi
exit 0
"""


def find_bash():
    for candidate in (os.environ.get("BOX_TEST_BASH"), r"C:\Program Files\Git\bin\bash.exe", shutil.which("bash")):
        if candidate and Path(candidate).is_file():
            return candidate
    return None


BASH = find_bash()


def archive(top=NAME) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        data = STUB.encode()
        info = tarfile.TarInfo(f"{top}/box")
        info.size, info.mode = len(data), 0o755
        tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


@unittest.skipUnless(BASH, "bash not available")
class Provision(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="box-prov-"))
        self.root = self.tmp / "root"
        (self.root / "etc/agent-service-box-provision").mkdir(parents=True)
        (self.root / "etc/agent-service").mkdir(parents=True)
        self.work = self.root / "var/lib/agent-service-box-provision"
        self.work.mkdir(parents=True)
        self.log = self.tmp / "box-calls.log"

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def pin(self, data: bytes, url=URL):
        sha = hashlib.sha256(data).hexdigest()
        (self.root / "etc/agent-service-box-provision/release.env").write_bytes(
            f"RELEASE_URL={url}\nRELEASE_SHA256={sha}\nRELEASE_NAME={NAME}\n".encode())

    def stage(self, data: bytes):
        (self.work / f"{NAME}.tar.gz").write_bytes(data)

    def inputs(self):
        (self.root / "etc/agent-service/box.yaml").write_bytes(b"installation_id: acme\n")
        (self.root / "etc/agent-service/secrets.env").write_bytes(b"JIRA_API_TOKEN=never-printed\n")

    def run_script(self, **env):
        script = (HERE / "provision.sh").read_bytes().replace(b"\r\n", b"\n")
        (self.tmp / "provision.sh").write_bytes(script)
        full = dict(os.environ, BOX_PROVISION_ROOT="root", FAKE_BOX_LOG="box-calls.log",
                    https_proxy="http://127.0.0.1:9", HTTPS_PROXY="http://127.0.0.1:9", **env)
        p = subprocess.run([BASH, "provision.sh"], cwd=self.tmp, env=full, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, text=True, timeout=120)
        status = json.loads((self.work / "status.json").read_text())
        calls = self.log.read_text().splitlines() if self.log.exists() else []
        return p, status, calls

    def test_verified_archive_waits_for_config_and_secrets_without_calling_box(self):
        data = archive()
        self.pin(data)
        self.stage(data)
        p, status, calls = self.run_script()
        self.assertEqual((p.returncode, status["phase"], calls), (0, "waiting_for_config", []))
        (self.root / "etc/agent-service/box.yaml").write_bytes(b"installation_id: acme\n")
        p, status, calls = self.run_script()
        self.assertEqual((p.returncode, status["phase"], calls), (0, "waiting_for_secrets", []))

    def test_with_inputs_it_runs_install_then_doctor_and_maps_exit_code(self):
        data = archive()
        self.pin(data)
        self.stage(data)
        self.inputs()
        p, status, calls = self.run_script(FAKE_INSTALL_RC="2")
        self.assertEqual(p.returncode, 0)
        self.assertEqual(calls, ["install --config root/etc/agent-service/box.yaml", "doctor"])
        self.assertEqual(status["phase"], "installed_not_ready")
        self.assertNotIn("never-printed", p.stdout)
        p, status, _ = self.run_script(FAKE_INSTALL_RC="1")
        self.assertEqual((p.returncode, status["phase"]), (1, "install_failed"))

    def test_cached_archive_with_wrong_sha_is_discarded_and_box_never_runs(self):
        self.pin(archive())
        self.stage(archive(top=NAME) + b"tampered")
        self.inputs()
        p, status, calls = self.run_script()
        self.assertEqual((p.returncode, status["phase"], calls), (1, "download_failed", []))
        self.assertFalse((self.work / f"{NAME}.tar.gz").exists())

    def test_archive_with_another_top_directory_is_rejected(self):
        data = archive(top="agent-service-evil")
        self.pin(data)
        self.stage(data)
        self.inputs()
        p, status, calls = self.run_script()
        self.assertEqual((p.returncode, status["phase"], calls), (1, "release_rejected", []))

    def test_release_url_outside_github_releases_is_refused_before_any_download(self):
        data = archive()
        self.pin(data, url=f"http://example.com/{NAME}.tar.gz")
        p, status, calls = self.run_script()
        self.assertEqual((p.returncode, status["phase"], calls), (1, "release_env_invalid", []))


if __name__ == "__main__":
    unittest.main()
