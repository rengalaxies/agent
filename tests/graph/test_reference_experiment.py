"""Clock/ledger rehearsal ONLY. No model traffic or model quality measurement."""
import copy
from pathlib import Path
import tempfile
import unittest

from agent_graph.contracts import GraphError
from tools.prepare_evidence_refs_experiment import RehearsalLedger, manifest


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.packet = manifest()
        self.path = Path(self.tmp.name) / "rehearsal.sqlite3"
        self.ledger = RehearsalLedger(self.path, self.packet, now=1000)
        self.model = self.packet["plan"]["models"][0]
        self.case = "reporting-http"

    def tearDown(self):
        self.ledger.close()
        self.tmp.cleanup()

    def assert_code(self, code, fn):
        with self.assertRaises(GraphError) as e:
            fn()
        self.assertEqual(e.exception.code, code)

    def test_manifest_fixed_and_history_including_timeout_preserved(self):
        self.assertEqual(self.packet, manifest())
        self.assertFalse(self.packet["live_enabled"])
        rows = self.packet["historical_requests"]
        self.assertEqual(len(rows), 21)
        self.assertEqual(sum(r["http_status"] is None for r in rows), 1)
        self.assertNotIn("required", self.packet["system"])
        self.assertNotIn("oracle", self.packet["system"])
        self.assertEqual(self.ledger.simulate_attempt(self.model, self.case, now=1001)["id"], 22)

    def test_case_deadline_persists_after_restart_no_active_time_subtraction(self):
        first = self.ledger.simulate_attempt(self.model, self.case, now=1010)
        self.ledger.close()
        self.ledger = RehearsalLedger(self.path, self.packet, now=9999)
        near = self.ledger.simulate_attempt(self.model, self.case, now=1309)
        self.assertEqual(first["deadline"], near["deadline"])
        self.assertEqual(near["timeout_seconds"], 1)
        self.assert_code("case_deadline", lambda: self.ledger.simulate_attempt(self.model, self.case, now=1310))

    def test_series_deadline_is_shared_by_both_models_and_all_cases(self):
        other = self.packet["plan"]["models"][1]
        result = self.ledger.simulate_attempt(other, "status-decoy", now=3099)
        self.assertEqual(result["deadline"], 3100)
        self.assertEqual(result["timeout_seconds"], 1)
        self.assert_code("series_deadline", lambda: self.ledger.simulate_attempt(self.model, self.case, now=3100))

    def test_all_attempts_charged_no_refund_on_unknown_or_restart(self):
        for i in range(5):
            self.ledger.simulate_attempt(self.model, self.case, now=1000+i)
        self.ledger.close()
        self.ledger = RehearsalLedger(self.path, self.packet, now=1010)
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 26)
        self.assert_code("case_request_limit", lambda: self.ledger.simulate_attempt(self.model, self.case, now=1010))

    def test_shared_total_cap_and_registered_cases(self):
        for case in self.packet["plan"]["case_order"]:
            for model in self.packet["plan"]["models"]:
                for _ in range(5):
                    self.ledger.simulate_attempt(model, case, now=1000)
        self.assertEqual(self.ledger.db.execute("SELECT count(*) FROM attempts").fetchone()[0], 51)
        self.assert_code("series_request_limit", lambda: self.ledger.simulate_attempt(self.model, self.case, now=1001))
        self.assert_code("unregistered_case", lambda: self.ledger.simulate_attempt("unregistered", self.case, now=1001))

    def test_manifest_change_or_clock_rollback_is_blocked(self):
        changed = copy.deepcopy(self.packet)
        changed["manifest_digest"] = "other"
        self.assert_code("experiment_manifest_changed", lambda: RehearsalLedger(self.path, changed, now=1001))
        self.ledger.simulate_attempt(self.model, self.case, now=1010)
        self.assert_code("clock_moved_backwards", lambda: self.ledger.simulate_attempt(self.model, self.case, now=1009))
