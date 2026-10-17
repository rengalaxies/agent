import unittest

from datamesh_release_protocol.distributed import EventCollector, _digest
from datamesh_release_protocol.models import Decision, LocalVerdict


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.collector = EventCollector("p", "s", frozenset({"a", "b"}))

    def event(self, domain, decision):
        verdict = LocalVerdict.model_validate({"domain_id": domain, "decision": decision,
            "consumer_verdicts": [{"consumer_id": domain, "decision": decision, "checks": []}]})
        payload = {"proposal_id": "p", "snapshot_id": "s", "domain_id": domain,
                   "verdict": verdict.model_dump(mode="json")}
        return {**payload, "event_id": _digest(payload)}

    def test_missing_never_accepts(self):
        self.collector.ingest(self.event("a", "ACCEPT"))
        self.assertEqual(self.collector.decision, Decision.NEEDS_REVIEW)

    def test_duplicate_and_reverse(self):
        b = self.event("b", "ACCEPT")
        a = self.event("a", "ACCEPT")
        for event in (b, a, a):
            self.collector.ingest(event)
        self.assertEqual(self.collector.decision, Decision.ACCEPT)
        self.assertEqual(self.collector.duplicates, 1)

    def test_conflict_and_stale_snapshot_fail_safe(self):
        self.collector.ingest(self.event("a", "ACCEPT"))
        stale = self.event("b", "ACCEPT")
        stale["snapshot_id"] = "old"
        self.collector.ingest(stale)
        self.collector.ingest(self.event("b", "ACCEPT"))
        self.collector.ingest(self.event("b", "REJECT"))
        self.assertEqual(self.collector.invalid, 1)
        self.assertEqual(self.collector.decision, Decision.NEEDS_REVIEW)

    def test_rejection_decisive_when_other_domain_missing(self):
        self.collector.ingest(self.event("a", "REJECT"))
        self.assertEqual(self.collector.decision, Decision.REJECT)


if __name__ == "__main__":
    unittest.main()
