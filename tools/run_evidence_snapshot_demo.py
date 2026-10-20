"""Synthetic diagnostic using public TEST ONLY keys from unittest fixtures.

Not a production approval ceremony or evidence of a real consumer incident.
Run with PYTHONPATH=src:tests.
"""
import json
from test_evidence_snapshot import EvidenceSnapshotTests
from datamesh_release_protocol.evidence_snapshot import evidence_links

case = EvidenceSnapshotTests()
case.setUp()
unconfirmed = case.build()
case.approve()
confirmed = case.build()
before = case.fence(confirmed)
case.registry.append(case.confirmation('consumer', version=2, status='revoked', valid_from=case.now))
after = case.fence(confirmed)
print(json.dumps(dict(kind='synthetic-evidence-lifecycle-not-business-validation',
                     unconfirmed=unconfirmed, confirmed=confirmed,
                     graph=evidence_links(confirmed), before_revocation=before,
                     after_revocation=after), ensure_ascii=False, indent=2))
