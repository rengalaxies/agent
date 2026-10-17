import tempfile
import unittest
from pathlib import Path

from datamesh_release_protocol.distributed import make_event
from datamesh_release_protocol.journal import EventJournal
from datamesh_release_protocol.models import Decision, LocalVerdict


def event(domain: str, decision: str) -> dict:
    verdict = LocalVerdict.model_validate({"domain_id": domain, "decision": decision,
        "consumer_verdicts": [{"consumer_id": domain, "decision": decision, "checks": []}]})
    return make_event("p", "s", verdict)


class JournalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "events.sqlite"

    def open(self, snapshot="s"):
        return EventJournal(self.path, "p", snapshot, frozenset({"a", "b"}))

    def test_replay_duplicate_and_second_coordinator(self):
        with self.open() as first:
            first.append(event("a", "ACCEPT"))
        with self.open() as second:
            self.assertEqual(second.replay().decision, Decision.NEEDS_REVIEW)
            second.append(event("a", "ACCEPT"))
            second.append(event("b", "ACCEPT"))
            self.assertEqual(second.replay().duplicates, 1)
            self.assertEqual(second.finalize(), Decision.ACCEPT)
        with self.open() as third:
            self.assertEqual(third.finalize(), Decision.ACCEPT)
            self.assertFalse(third.append(event("b", "REJECT")))
            self.assertEqual(third.finalize(), Decision.ACCEPT)

    def test_missing_domain_and_late_event_remain_review(self):
        with self.open() as journal:
            journal.append(event("a", "ACCEPT"))
            self.assertEqual(journal.finalize(), Decision.NEEDS_REVIEW)
        with self.open() as restarted:
            self.assertFalse(restarted.append(event("b", "ACCEPT")))
            self.assertEqual(restarted.finalize(), Decision.NEEDS_REVIEW)

    def test_conflict_and_stale_event_fail_safe(self):
        with self.open() as journal:
            journal.append(event("a", "ACCEPT"))
            journal.append(event("a", "REJECT"))
            stale = event("b", "ACCEPT")
            stale["snapshot_id"] = "wrong"
            journal.append(stale)
            journal.append(event("b", "ACCEPT"))
            self.assertEqual(journal.replay().invalid, 1)
            self.assertEqual(journal.replay().conflicts, {"a"})
            self.assertEqual(journal.finalize(), Decision.NEEDS_REVIEW)

    def test_cannot_resume_different_snapshot(self):
        with self.open():
            pass
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            self.open("new")


if __name__ == "__main__":
    unittest.main()
