"""Git mirrors: clone once, fetch afterwards, and failures become reason codes instead of git output."""

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from tools.agent_service.box import mirrors
from tools.agent_service.box.config import BoxConfig


def git(*args, cwd=None) -> str:
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
           "GIT_COMMITTER_EMAIL": "t@example.invalid", "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, stdout=subprocess.PIPE,
                          text=True).stdout.strip()


class Sync(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.source = self.tmp / "orders"
        git("init", "-q", "--initial-branch=main", str(self.source))
        (self.source / "api.py").write_text("PAGE_SIZE = 100\n")
        git("add", "api.py", cwd=self.source)
        git("commit", "-qm", "one", cwd=self.source)
        self.first = git("rev-parse", "HEAD", cwd=self.source)

    def config(self, *, clone_url=None, branch="main") -> BoxConfig:
        return BoxConfig.model_validate({
            "installation_id": "acme", "environment": "prod", "testing": {"allow_local_sources": True},
            "github": {"bot_login": "bot", "auth": {"kind": "token"}, "repositories": [
                {"name": "acme/orders", "service": "orders", "watch_prs": True, "branch": branch,
                 "clone_url": str(clone_url or self.source)}]}})

    def test_clone_then_fetch_follows_the_branch_tip(self):
        target = self.tmp / "state" / "mirrors"
        first = mirrors.sync(self.config(), target, {})
        self.assertEqual(first, [{"repository": "acme/orders", "id": "orders", "status": "OK", "action": "cloned",
                                  "tip": self.first}])
        (self.source / "api.py").write_text("PAGE_SIZE = 20\n")
        git("commit", "-qam", "two", cwd=self.source)
        second = mirrors.sync(self.config(), target, {})
        self.assertEqual(second[0]["action"], "fetched")
        self.assertEqual(second[0]["tip"], git("rev-parse", "HEAD", cwd=self.source))

    def test_missing_branch_is_a_reason_code(self):
        result = mirrors.sync(self.config(branch="release"), self.tmp / "m", {})
        self.assertEqual((result[0]["status"], result[0]["code"]), ("FAILED", "git_branch_not_found"))

    def test_unreachable_repository_is_a_reason_code_and_leaves_no_partial_mirror(self):
        result = mirrors.sync(self.config(clone_url=self.tmp / "absent"), self.tmp / "m", {})
        self.assertEqual(result[0]["code"], "git_repository_not_found_or_no_access")
        self.assertEqual([p.name for p in (self.tmp / "m").iterdir() if not p.name.startswith(".sync")], [])

    def test_https_source_without_its_secret_is_reported_before_any_network_call(self):
        cfg = BoxConfig.model_validate({
            "installation_id": "acme", "environment": "prod",
            "github": {"bot_login": "bot", "auth": {"kind": "token"},
                       "repositories": [{"name": "acme/orders", "service": "orders", "watch_prs": True}]}})
        result = mirrors.sync(cfg, self.tmp / "m", {})
        self.assertEqual(result[0]["code"], "github_secret_missing")


class Reasons(unittest.TestCase):
    def test_git_messages_map_to_actionable_codes(self):
        cases = {
            "fatal: Authentication failed for 'https://github.com/acme/orders.git/'": "git_credentials_rejected",
            "remote: Repository not found.\nfatal: repository 'https://github.com/x/y.git/' not found":
                "git_repository_not_found_or_no_access",
            "fatal: unable to access 'https://github.com/': Could not resolve host: github.com": "git_host_unreachable",
            "fatal: detected dubious ownership in repository at '/srv/x'": "git_repository_owner_mismatch",
            "error: something else": "git_fetch_failed",
        }
        for stderr, code in cases.items():
            self.assertEqual(mirrors._reason(stderr), code, stderr)

    def test_credentials_travel_in_the_environment_not_the_command_line(self):
        env = mirrors.git_env(Path(tempfile.mkdtemp()), header=("http.https://github.com/.extraHeader",
                                                                 "Authorization: Basic c2VjcmV0"), allow_local=False)
        values = [env[k] for k in env if k.startswith("GIT_CONFIG_VALUE_")]
        self.assertIn("Authorization: Basic c2VjcmV0", values)
        self.assertIn("never", values)  # protocol.file.allow: no local clones in production


if __name__ == "__main__":
    unittest.main()
