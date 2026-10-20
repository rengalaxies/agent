"""End-to-end execution, provenance and restart tests on the internal profile."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import unittest

from change_completion.adapters import read_repository_file
from change_completion.models import Action, TransitionSpec
from change_completion.runtime import encode, run_transition
from change_completion.store import RunStore
from change_completion.verification import TrustPolicy, context_digest, digest_bytes
from change_completion.verify_cli import TrustConfig

ROOT = Path(__file__).resolve().parents[2] / "examples/product/execution"
NOW = datetime(2026, 10, 16, 16, tzinfo=timezone.utc)


class BadProvider:
    identity = "test-bad-provider/1"
    def propose(self, source, **kwargs):
        return {"status": "prepared", "candidate": "SELECT 999 AS total;"}


class RuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.repo = self.base / "repo"
        self.fixtures = self.base / "fixtures"
        shutil.copytree(ROOT / "repository", self.repo)
        shutil.copytree(ROOT / "fixtures", self.fixtures)
        self.spec = TransitionSpec.model_validate_json((ROOT / "transition.json").read_bytes())
        self.suite = (ROOT / "expectations.json").read_bytes()
        config = TrustConfig.model_validate_json((ROOT / "trust.json").read_bytes())
        self.policy = TrustPolicy(**{k: getattr(config, k) for k in TrustConfig.model_fields})
        self.db = self.base / "state/runs.sqlite3"
        self.store = RunStore(self.db)

    def run_case(self, **kwargs):
        return run_transition(self.repo, self.spec, self.suite,
                              lambda uri: read_repository_file(self.fixtures, uri),
                              kwargs.pop("policy_loader", lambda: self.policy),
                              kwargs.pop("store", self.store), actor="demo-worker",
                              clock=kwargs.pop("clock", lambda: NOW), **kwargs)

    def test_real_patch_and_results_preserve_other_consumer(self):
        original = (self.repo / "analytics.sql").read_bytes()
        result = self.run_case()
        self.assertEqual(result["status"], "READY_FOR_REVIEW", result)
        self.assertIn("age_days < 90", result["patches"]["analytics"]["candidate"])
        self.assertIn("age_days < 30", result["patches"]["audit"]["candidate"])
        self.assertTrue(result["patches"]["analytics"]["diff"])
        self.assertFalse(result["patches"]["audit"]["diff"])
        self.assertEqual((self.repo / "analytics.sql").read_bytes(), original)
        self.assertEqual(len(result["receipts"]), 4)
        self.assertEqual([c["actual"]["rows"] for c in result["observations"]["cases"]], [[[160]], [[31]], [[100]], [[7]]])
        self.assertFalse(result["effects_authorized"])

    def test_restart_reuses_same_result_and_history(self):
        first = self.run_case()
        count = len(self.store.get(first["run_id"])["events"])
        second = self.run_case(store=RunStore(self.db))
        self.assertEqual(second["status"], "READY_FOR_REVIEW")
        self.assertTrue(second["reused"])
        self.assertEqual(first["run_id"], second["run_id"])
        self.assertEqual(len(self.store.get(first["run_id"])["events"]), count)

    def test_bad_candidate_not_exported_or_marked_ready(self):
        result = self.run_case(provider=BadProvider())
        self.assertEqual(result["status"], "FAIL")
        self.assertNotIn("patches", result)
        self.assertNotIn("observations", result)

    def test_fixture_bytes_are_checked_before_execution(self):
        (self.fixtures / "normal.json").write_text('{}')
        result = self.run_case()
        self.assertEqual(result["status"], "STOP")
        self.assertIn("fixture_digest_mismatch", result["reason_codes"])

    def test_repository_digest_and_unlisted_consumer_are_checked(self):
        (self.repo / "analytics.sql").write_text("SELECT 1;")
        self.assertEqual(self.run_case()["status"], "STOP")
        shutil.copy2(ROOT / "repository/analytics.sql", self.repo / "analytics.sql")
        (self.repo / "hidden.sql").write_text("SELECT amount FROM events;")
        self.assertIn("unregistered_sql_consumer", self.run_case()["reason_codes"])

    def test_symlink_fixture_is_not_read(self):
        (self.fixtures / "normal.json").unlink()
        (self.fixtures / "normal.json").symlink_to(ROOT / "fixtures/normal.json")
        self.assertEqual(self.run_case()["status"], "STOP")

    def test_cache_cannot_bypass_expiry_or_revoke(self):
        self.assertEqual(self.run_case()["status"], "READY_FOR_REVIEW")
        expired = self.run_case(clock=lambda: datetime(2027, 10, 16, 10, tzinfo=timezone.utc))
        self.assertEqual(expired["status"], "STOP")
        revoked = TrustPolicy(self.policy.approved_suite_digests, self.policy.approved_owners,
                              self.policy.grants, frozenset({"demo-execution-grant"}))
        result = self.run_case(policy_loader=lambda: revoked)
        self.assertEqual(result["status"], "STOP")
        self.assertNotIn("patches", result)

    def test_export_revoke_during_proposal_returns_no_candidate_body(self):
        state = {"revoke": False}
        policy = self.policy
        class RevokingProvider:
            identity = "revoke-during-proposal/1"
            def propose(inner, source, **kwargs):
                from change_completion.adapters import prepare_window_patch
                state["revoke"] = True
                return prepare_window_patch(source, **kwargs)
        def loader():
            if not state["revoke"]:
                return policy
            grants = tuple(g.model_copy(update={"actions": tuple(a for a in g.actions if a != Action.EXPORT)}) for g in policy.grants)
            return TrustPolicy(policy.approved_suite_digests, policy.approved_owners, grants)
        result = self.run_case(provider=RevokingProvider(), policy_loader=loader)
        self.assertEqual(result["status"], "STOP")
        self.assertNotIn("patches", result)
        self.assertNotIn("observations", result)

    def test_interrupted_running_job_is_not_reexecuted(self):
        class CrashProvider:
            identity = "crash-profile/1"
            def propose(inner, source, **kwargs):
                raise KeyboardInterrupt("simulated process interruption")
        with self.assertRaises(KeyboardInterrupt):
            self.run_case(provider=CrashProvider())
        result = self.run_case(provider=CrashProvider(), store=RunStore(self.db))
        self.assertEqual(result["status"], "STOP")
        self.assertEqual(result["reason_codes"], ["RUN_ALREADY_RUNNING_REQUIRES_REVIEW"])

    def test_cached_patch_tamper_is_not_released(self):
        first = self.run_case()
        # Installation administrator tamper is detectable by stored digest checks;
        # this does not claim resistance to an administrator forging all hashes.
        import sqlite3
        altered = copy.deepcopy(first)
        altered["patches"]["analytics"]["candidate"] = "SELECT 999 AS total;"
        with sqlite3.connect(self.db) as db:
            db.execute("UPDATE runs SET result=? WHERE run_id=?", (json.dumps(altered), first["run_id"]))
        result = self.run_case()
        self.assertEqual(result["status"], "STOP")
        self.assertNotIn("patches", result)

    def test_suite_approval_cannot_be_replaced_by_candidate(self):
        suite = json.loads(self.suite)
        suite["cases"][0]["expected"]["rows"] = [[999]]
        self.suite = encode(suite)
        self.assertIn("unapproved_expectations", self.run_case()["reason_codes"])

    def test_cached_export_revoke_is_redacted(self):
        self.assertEqual(self.run_case()["status"], "READY_FOR_REVIEW")
        calls = {"n": 0}
        def loader():
            calls["n"] += 1
            if calls["n"] < 3:
                return self.policy
            grants = tuple(g.model_copy(update={"actions": tuple(a for a in g.actions if a != Action.EXPORT)}) for g in self.policy.grants)
            return TrustPolicy(self.policy.approved_suite_digests, self.policy.approved_owners, grants)
        result = self.run_case(policy_loader=loader)
        self.assertEqual(result["status"], "STOP")
        self.assertNotIn("patches", result)
        self.assertNotIn("observations", result)

    def test_unsupported_requested_capability_stops_before_work(self):
        data = self.spec.model_dump(mode="json")
        data["needs"][0]["capability"]["action"] = "deploy"
        self.spec = TransitionSpec.model_validate(data)
        result = self.run_case()
        self.assertEqual(result["status"], "STOP")
        self.assertIn("unsupported_requested_capability", result["reason_codes"])
