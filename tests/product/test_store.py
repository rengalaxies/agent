from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import tempfile
import unittest

from change_completion.store import RunStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.tmp_path = Path(self.directory.name)

    def test_claim_and_restart_do_not_repeat_running_work(self):
        path = self.tmp_path / "state" / "runs.sqlite"
        first = RunStore(path).claim("transition", "request-digest")
        restarted = RunStore(path)
        assert first["claimed"] is True
        assert restarted.claim("transition", "request-digest") == {
            "run_id": first["run_id"], "claimed": False, "status": "RUNNING"
        }
        assert len(restarted.get(first["run_id"])["events"]) == 1


    def test_parallel_claim_has_one_owner(self):
        store = RunStore(self.tmp_path / "runs.sqlite")
        with ThreadPoolExecutor(max_workers=8) as executor:
            claims = list(executor.map(lambda _: store.claim("t", "digest"), range(24)))
        assert sum(claim["claimed"] for claim in claims) == 1
        assert len({claim["run_id"] for claim in claims}) == 1


    def test_new_context_gets_a_separate_run(self):
        store = RunStore(self.tmp_path / "runs.sqlite")
        assert store.claim("t", "old")["run_id"] != store.claim("t", "new")["run_id"]


    def test_finish_is_durable_idempotent_and_events_ordered(self):
        path = self.tmp_path / "runs.sqlite"
        store = RunStore(path)
        run_id = store.claim("t", "digest")["run_id"]
        store.append(run_id, "VERIFIED", {"accepted": True})
        store.finish(run_id, "READY_FOR_REVIEW", {"patch": "diff"})
        store.finish(run_id, "READY_FOR_REVIEW", {"patch": "diff"})
        record = RunStore(path).get(run_id)
        assert record["result"] == {"patch": "diff"}
        assert [event["kind"] for event in record["events"]] == ["CLAIMED", "VERIFIED", "FINISHED"]
        assert all(event["timestamp"].endswith("+00:00") for event in record["events"])
        assert store.claim("t", "digest")["claimed"] is False
        assert store.claim("t", "digest")["status"] == "READY_FOR_REVIEW"
        with self.assertRaisesRegex(ValueError, "cannot be changed"):
            store.finish(run_id, "FAIL", {})
        with self.assertRaisesRegex(ValueError, "completed"):
            store.append(run_id, "LATE", {})


    def test_stop_and_failure_are_terminal(self):
        store = RunStore(self.tmp_path / "runs.sqlite")
        for status in ("STOP", "FAIL"):
            run_id = store.claim("t", status)["run_id"]
            store.finish(run_id, status, {"reason": "incomplete"})
            assert store.get(run_id)["status"] == status
            assert store.claim("t", status)["claimed"] is False


    def test_reject_invalid_payload_and_status(self):
        store = RunStore(self.tmp_path / "runs.sqlite")
        run_id = store.claim("t", "digest")["run_id"]
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            store.append(run_id, "DATA", {"data": "a" * (1024 * 1024)})
        with self.assertRaises(ValueError):
            store.append(run_id, "DATA", {"number": float("nan")})
        with self.assertRaisesRegex(ValueError, "reserved"):
            store.append(run_id, "FINISHED", {})
        with self.assertRaisesRegex(ValueError, "terminal"):
            store.finish(run_id, "DEPLOYED", {})
        assert store.get(run_id)["status"] == "RUNNING"


    def test_unknown_run_cannot_be_changed(self):
        store = RunStore(self.tmp_path / "runs.sqlite")
        with self.assertRaises(KeyError):
            store.get("missing")
        with self.assertRaises(KeyError):
            store.append("missing", "CHECK", {})
        with self.assertRaises(KeyError):
            store.finish("missing", "STOP", {})


    def test_private_creation_does_not_chmod_existing_parent(self):
        original_mode = self.tmp_path.stat().st_mode & 0o777
        path = self.tmp_path / "runs.sqlite"
        RunStore(path)
        assert path.stat().st_mode & 0o777 == 0o600
        assert self.tmp_path.stat().st_mode & 0o777 == original_mode
        private = self.tmp_path / "private" / "runs.sqlite"
        RunStore(private)
        assert private.parent.stat().st_mode & 0o777 == 0o700
