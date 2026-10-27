"""State recovery is proposed by plan and written only by an approved apply.

Review of PR #62: the workflow ran ``terraform untaint`` for operation=plan, a
write to the real state before anyone approved an apply. Now plan computes its
digest on a local copy with the recovery applied, and the digest covers the
recovery list itself.
"""

import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

import boxctl
import ownership as own
from fixtures import box_state, fresh_plan

KEY = bytes(range(32))
SHA = "a" * 40
WORKFLOW = Path(__file__).resolve().parents[3] / ".github/workflows/cloudru-box.yml"
STATE_WRITES = re.compile(r"terraform\s+(-chdir=\S+\s+)?(untaint|import|apply|force-unlock|state\s+(rm|mv|push))\b"
                          r"|boxctl\.py\s+ledger-put")


def projection(recovery=()):
    return own.plan_projection(fresh_plan(), key=KEY, commit=SHA, box_id="pilot1", mode="apply", recovery=recovery)


class ReviewedRecovery(unittest.TestCase):
    def test_the_digest_covers_the_proposed_recovery(self):
        nic = ["cloudru_evolution_compute_interface.nic"]
        self.assertNotEqual(own.digest(projection()), own.digest(projection(nic)))
        self.assertEqual(projection(nic)["recovery"], nic)

    def test_recovery_copy_refuses_an_address_that_is_not_an_untaint_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "state.json").write_text(json.dumps(box_state(tainted=("vm",))), encoding="utf-8")
            (tmp / "recovery.txt").write_text("cloudru_evolution_compute_instance.vm\n", encoding="utf-8")
            (tmp / "cfg").mkdir()
            code = boxctl.main(["recovery-copy", "--box-id", "pilot1", "--dir", str(tmp / "cfg"),
                                "--state", str(tmp / "state.json"), "--recovery", str(tmp / "recovery.txt"),
                                "--out", str(tmp / "copy")])
            self.assertEqual(code, 1)
            self.assertFalse((tmp / "copy").exists())


def steps(text):
    """(name, if expression or None, body) of every step of the single job."""
    out = []
    for block in re.split(r"\n      - (?=name:|uses:)", text.split("\n    steps:\n", 1)[1]):
        name = re.search(r"name: (.+)", block)
        cond = re.search(r"\n        if: (.+)", block)
        out.append((name.group(1) if name else block.split("\n")[0], cond.group(1) if cond else None, block))
    return out


def runs_for(expression, operation):
    """Evaluate the workflow's if: expressions used in this file for one operation; step outcomes are skipped."""
    if expression is None:
        return True
    py = re.sub(r"contains\(fromJSON\('(\[[^']*\])'\), inputs\.operation\)", r"(OP in \1)", expression)
    py = py.replace("inputs.operation", "OP").replace("&&", " and ").replace("||", " or ").replace("always()", "True")
    py = re.sub(r"steps\.\w+\.outcome", "'skipped'", py)
    return eval(py, {"__builtins__": {}}, {"OP": operation})  # expressions of our own workflow file only


class WorkflowNeverWritesStateOnPlan(unittest.TestCase):
    def test_no_step_that_runs_for_plan_or_destroy_plan_writes_state(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        for operation in ("plan", "destroy-plan", "status"):
            for name, cond, body in steps(text):
                if runs_for(cond, operation):
                    self.assertIsNone(STATE_WRITES.search(body), f"{operation}: {name}")

    def test_the_recovery_write_runs_only_for_apply(self):
        text = WORKFLOW.read_text(encoding="utf-8")
        writers = [(name, cond) for name, cond, body in steps(text) if re.search(r"terraform untaint", body)]
        self.assertTrue(writers)
        for name, cond in writers:
            self.assertEqual([op for op in ("plan", "apply", "status", "destroy-plan", "destroy", "lock-test")
                              if runs_for(cond, op)], ["apply"], name)


@unittest.skipUnless(shutil.which("terraform"), "terraform is not installed (the CI box workflow has it)")
class RecoveryCopyWithTerraform(unittest.TestCase):
    """A tainted resource in a local state: the copy plans no replacement, the original stays as it was."""

    CONFIG = 'terraform {\n  backend "s3" {}\n}\nresource "terraform_data" "nic" {\n  input = "x"\n}\n'

    def test_copy_untaints_only_the_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            seed = tmp / "seed"
            seed.mkdir()
            (seed / "main.tf").write_text('resource "terraform_data" "nic" {\n  input = "x"\n}\n', encoding="utf-8")
            for args in (["init", "-input=false"], ["apply", "-auto-approve", "-input=false"],
                         ["taint", "terraform_data.nic"]):
                subprocess.run(["terraform", *args], cwd=seed, check=True, capture_output=True)
            original = (seed / "terraform.tfstate").read_bytes()
            config = tmp / "config"
            config.mkdir()
            (config / "main.tf").write_text(self.CONFIG, encoding="utf-8")
            (tmp / "recovery.txt").write_text("terraform_data.nic\n", encoding="utf-8")
            # The box guards (resource types, names, project) have their own tests; here only the
            # Terraform mechanics of the copy are under test, on a builtin resource.
            saved = own.state_records, own.untaint_candidates
            own.state_records = lambda state: []
            own.untaint_candidates = lambda records, box_id, project=None: ["terraform_data.nic"]
            try:
                code = boxctl.main(["recovery-copy", "--box-id", "pilot1", "--dir", str(config),
                                    "--state", str(seed / "terraform.tfstate"),
                                    "--recovery", str(tmp / "recovery.txt"), "--out", str(tmp / "copy")])
            finally:
                own.state_records, own.untaint_candidates = saved
            self.assertEqual(code, 0)
            plan = subprocess.run(["terraform", "plan", "-input=false", "-lock=false", "-detailed-exitcode"],
                                  cwd=tmp / "copy", capture_output=True, text=True)
            self.assertEqual(plan.returncode, 0, plan.stdout[-2000:])  # nothing to replace after recovery
            self.assertEqual((seed / "terraform.tfstate").read_bytes(), original)
            self.assertFalse((config / "recovery_override.tf").exists())


if __name__ == "__main__":
    unittest.main()
