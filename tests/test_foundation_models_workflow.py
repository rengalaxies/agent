"""Security contracts for the workflow that receives the Foundation key.

Runs in core PR regression without model credentials; PyYAML is a project dependency.
"""
from pathlib import Path
import re
import subprocess
import sys
import unittest

import yaml


ROOT = Path(__file__).resolve().parents[1]


class FoundationWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.workflow = yaml.safe_load(
            (ROOT / ".github/workflows/cloudru-foundation-models.yml").read_text())
        self.job = self.workflow["jobs"]["qualify"]

    def test_only_manual_main_event_can_reach_secret(self):
        # PyYAML's YAML 1.1 loader represents the unquoted `on` key as True.
        events = self.workflow.get("on", self.workflow.get(True))
        self.assertEqual(set(events), {"workflow_dispatch"})
        inputs = events["workflow_dispatch"]["inputs"]
        self.assertEqual(set(inputs), {"mode"})
        self.assertEqual(inputs["mode"]["default"], "preflight")
        self.assertEqual(inputs["mode"]["type"], "choice")
        self.assertEqual(set(inputs["mode"]["options"]), {"preflight", "catalog", "generate"})
        self.assertEqual(self.job["if"], "github.ref == 'refs/heads/main'")
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertEqual(set(self.workflow["jobs"]), {"qualify"})
        self.assertNotIn("permissions", self.job)
        self.assertNotIn("environment", self.job)
        self.assertEqual(self.job["runs-on"], "ubuntu-latest")
        self.assertLessEqual(self.job["timeout-minutes"], 3)

    def test_checkout_is_exact_event_sha_without_persisted_token(self):
        uses = [s for s in self.job["steps"] if "uses" in s]
        self.assertEqual(len(uses), 1)  # No upload, reusable or third-party actions.
        self.assertRegex(uses[0]["uses"], r"^actions/checkout@[0-9a-f]{40}$")
        self.assertEqual(uses[0]["with"],
                         {"ref": "${{ github.sha }}", "persist-credentials": False})

    def test_secret_is_scoped_to_probe_and_no_infrastructure_credentials(self):
        serialized = yaml.safe_dump(self.workflow)
        self.assertEqual(re.findall(r"secrets\.([A-Za-z0-9_]+)", serialized),
                         ["CLOUDRU_FOUNDATION_API_KEY"])
        self.assertNotIn("env", self.workflow)
        self.assertNotIn("env", self.job)
        steps = self.job["steps"]
        secret_steps = [s for s in steps if "CLOUDRU_FOUNDATION_API_KEY" in s.get("env", {})]
        self.assertEqual(len(secret_steps), 1)
        step = secret_steps[0]
        self.assertEqual(step["env"], {
            "CLOUDRU_FOUNDATION_API_KEY": "${{ secrets.CLOUDRU_FOUNDATION_API_KEY }}",
            "FM_MODE": "${{ inputs.mode }}",
            "FM_BUDGET_APPROVED": "${{ vars.CLOUDRU_FM_BUDGET_APPROVED }}",
            "FM_GRANT_CONFIRMED": "${{ vars.CLOUDRU_FM_GRANT_CONFIRMED }}",
        })
        for other_step in steps:
            if other_step is not step:
                self.assertNotIn("env", other_step)
        self.assertEqual(step["run"],
                         'python3 infra/cloudru/foundation_models/probe.py --mode "$FM_MODE"')
        self.assertLess(next(i for i, s in enumerate(steps)
                             if "unittest discover" in s.get("run", "")), steps.index(step))

    def test_offline_adapter_suite_is_part_of_pr_regression(self):
        # Core regression already includes tests/** and runs this module on PRs.
        # Thus adapter safety tests run before merge as well as before qualification.
        result = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s",
             "infra/cloudru/foundation_models", "-p", "test_*.py", "-v"],
            cwd=ROOT, capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
