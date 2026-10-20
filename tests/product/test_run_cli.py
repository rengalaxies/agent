import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from change_completion.run_cli import main

ROOT = Path(__file__).resolve().parents[2] / "examples/product/execution"


class RunCLITest(unittest.TestCase):
    def call(self, args):
        stream = io.StringIO()
        with contextlib.redirect_stdout(stream):
            code = main(args)
        return code, json.loads(stream.getvalue())

    def args(self, state):
        args = ["run"]
        for key, value in (("repository", ROOT / "repository"), ("transition", ROOT / "transition.json"),
                           ("expectations", ROOT / "expectations.json"), ("fixtures", ROOT / "fixtures"),
                           ("trust", ROOT / "trust.json"), ("state", state), ("actor", "demo-worker"),
                           ("at", "2026-10-16T16:00:00Z")):
            args += ["--"+key, str(value)]
        return args

    def test_real_run_restart_and_history(self):
        with TemporaryDirectory() as state:
            code, first = self.call(self.args(state))
            self.assertEqual(code, 0, first)
            code, second = self.call(self.args(state))
            self.assertEqual(code, 0)
            self.assertTrue(second["reused"])
            code, history = self.call(["history", "--state", state, "--run-id", first["run_id"]])
            self.assertEqual(code, 0)
            self.assertEqual(history["status"], "READY_FOR_REVIEW")
            self.assertEqual([e["kind"] for e in history["events"]], ["CLAIMED", "CONTEXT", "DISCOVERED", "PREPARED", "VERIFIED", "FINISHED"])

    def test_state_inside_checkout_rejected(self):
        code, report = self.call(self.args(ROOT / "repository/private-state"))
        self.assertEqual(code, 2)
        self.assertEqual(report["status"], "STOP")
