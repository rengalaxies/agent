import contextlib
import io
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from change_completion.verify_cli import main

ROOT = Path(__file__).resolve().parents[2] / "examples" / "product" / "verification"


class VerificationReplayTest(unittest.TestCase):
    def replay(self, **overrides):
        args = []
        for name, filename in (("transition", "transition.json"), ("candidate", "candidate.txt"),
                               ("expectations", "expectations.json"), ("observations", "observations.json"),
                               ("trust", "trust.json")):
            args += ["--" + name, str(overrides.get(name, ROOT / filename))]
        args += ["--actor", "fixture-worker", "--at", overrides.get("at", "2026-10-16T14:00:00Z")]
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = main(args)
        return code, json.loads(output.getvalue())

    def test_fixed_replay_passes_without_effects(self):
        code, report = self.replay()
        self.assertEqual(code, 0)
        self.assertEqual(report["status"], "PASS")
        self.assertEqual(report["scope"], "provided_observations_only")
        self.assertFalse(report["effects_authorized"])

    def test_changed_candidate_cannot_reuse_observations(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate.txt"
            path.write_text("different candidate")
            code, report = self.replay(candidate=path)
        self.assertEqual(code, 2)
        self.assertIn("ARTIFACT_BINDING_MISMATCH", report["reason_codes"])

    def test_changed_expected_file_needs_new_approval(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "expected.json"
            path.write_bytes((ROOT / "expectations.json").read_bytes() + b" ")
            code, report = self.replay(expectations=path)
        self.assertEqual(code, 2)
        self.assertIn("UNAPPROVED_EXPECTATIONS", report["reason_codes"])

    def test_observed_bad_value_fails(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "actual.json"
            data = json.loads((ROOT / "observations.json").read_text())
            data["cases"][1]["actual"]["rows"] = [[100]]
            path.write_text(json.dumps(data))
            code, report = self.replay(observations=path)
        self.assertEqual(code, 1)
        self.assertEqual(report["status"], "FAIL")

    def test_expiry_without_new_observation_stops(self):
        code, report = self.replay(at="2026-10-17T12:00:00Z")
        self.assertEqual(code, 2)
        self.assertIn("STALE_OR_NONINDEPENDENT_EXPECTATIONS", report["reason_codes"])

    def test_invalid_and_oversized_inputs_stop(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.json"
            for contents in (b'{"cases":NaN}', b" " * 1_000_001):
                path.write_bytes(contents)
                code, report = self.replay(observations=path)
                self.assertEqual(code, 2)
                self.assertEqual(report["status"], "STOP")
