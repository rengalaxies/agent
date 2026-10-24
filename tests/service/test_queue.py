"""Queue invariants that a later change could easily break: leases, CAS and supersede."""

from contextlib import closing
from pathlib import Path
import tempfile
import unittest

from agent_service.envelope import EventEnvelope
from agent_service.queue import Limits, ServiceStore

from tests.service.clock import Clock

RID = "github:acme/orders#7"


def body(generation):
    return "{}", "0" * 64, "a" * 16


class QueueTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.clock = Clock()
        self.store = ServiceStore(Path(tmp.name) / "q.sqlite", clock=self.clock,
                                  limits=Limits(lease_seconds=60, max_analysis_attempts=2))

    def open(self, version):
        return self.store.apply_snapshot(resource_id=RID, provider="github", kind="pr", version=version,
                                         snapshot={"v": version}, event_id=f"e-{version}")

    def intent(self):
        return {"kind": "result", "body": "{}", "body_digest": "1" * 64, "marker": "a" * 16}

    def test_active_lease_prevents_a_second_claim_and_expiry_hands_the_job_over(self):
        self.open("v1")
        first = self.store.claim_job("worker-a")
        self.assertIsNotNone(first)
        self.assertIsNone(self.store.claim_job("worker-b"))
        self.clock.advance(61)
        self.store.recover()
        second = self.store.claim_job("worker-b")
        self.assertEqual(second["job_id"], first["job_id"])
        # The old worker wakes up: its result is discarded, the new owner's is kept.
        self.assertIsNone(self.store.complete_job(first, state="ANALYZED", result={"x": 1}, reason=None,
                                                  intent=self.intent()))
        self.assertIsNotNone(self.store.complete_job(second, state="ANALYZED", result={"x": 2}, reason=None,
                                                     intent=self.intent()))
        self.assertEqual(len(self.store.intents(RID)), 1)

    def test_new_version_revokes_running_job_and_pending_intent_of_older_generation(self):
        self.open("v1")
        job = self.store.claim_job("w")
        self.store.complete_job(job, state="ANALYZED", result={}, reason=None, intent=self.intent())
        self.open("v2")
        [old_intent] = self.store.intents(RID)
        self.assertEqual(old_intent["state"], "SUPERSEDED")
        running = self.store.claim_job("w")
        self.assertEqual(running["generation"], 2)
        self.open("v3")
        self.assertFalse(self.store.job_is_current(running))
        self.assertIsNone(self.store.complete_job(running, state="ANALYZED", result={}, reason=None,
                                                  intent=self.intent()))
        self.assertEqual([j["state"] for j in self.store.jobs(RID)], ["SUPERSEDED", "SUPERSEDED", "QUEUED"])

    def test_same_version_coalesces_and_reverted_version_opens_a_new_generation(self):
        self.assertEqual(self.open("v1")["action"], "new_generation")
        self.assertEqual(self.open("v1")["action"], "coalesced")
        self.open("v2")
        self.assertEqual(self.open("v1")["generation"], 3)  # force-push back is a real change

    def test_crash_during_send_of_a_superseded_generation_is_never_resent(self):
        self.open("v1")
        job = self.store.claim_job("w")
        self.store.complete_job(job, state="ANALYZED", result={}, reason=None, intent=self.intent())
        intent = self.store.claim_intent("w")
        self.assertTrue(self.store.mark_sending(intent, operation="create", comment_id=None))
        self.open("v2")
        self.clock.advance(61)
        self.store.recover()
        self.assertEqual(self.store.intent(intent["intent_id"])["state"], "SUPERSEDED")
        self.assertIsNone(self.store.claim_intent("w"))

    def test_mark_sending_refuses_a_revoked_publication_right(self):
        self.open("v1")
        job = self.store.claim_job("w")
        self.store.complete_job(job, state="ANALYZED", result={}, reason=None, intent=self.intent())
        intent = self.store.claim_intent("w")
        self.open("v2")
        self.assertFalse(self.store.mark_sending(intent, operation="update", comment_id="1"))

    def test_analysis_attempts_are_bounded(self):
        self.open("v1")
        for _ in range(2):
            self.clock.advance(1000)
            job = self.store.claim_job("w")
            outcome = self.store.requeue_job(job, "analysis_unavailable", count_attempt=True)
        self.assertEqual(outcome, "FAILED")

    def test_duplicate_delivery_id_is_stored_once(self):
        env = EventEnvelope(provider="github", source="acme/orders", event_id="d1", event_kind="pull_request.opened",
                            resource_id=RID, payload_digest="0" * 64, received_at=self.clock())
        self.assertEqual(self.store.add_event(env), (True, "RECEIVED"))
        self.assertEqual(self.store.add_event(env), (False, "RECEIVED"))
        self.assertEqual(self.store.status()["events"], {"RECEIVED": 1})

    def test_history_is_append_only(self):
        self.open("v1")
        import sqlite3

        with closing(sqlite3.connect(self.store.path)) as c, self.assertRaises(sqlite3.DatabaseError):
            c.execute("DELETE FROM history")


if __name__ == "__main__":
    unittest.main()
