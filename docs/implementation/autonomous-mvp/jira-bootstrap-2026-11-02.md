# Existing Jira issues without PRs: bootstrap/recovery discovery

The published `23412df5e385f11b097d9e67d334d262967ca387` archive has a real
Jira-before-diff analyzer, but its initial discovery uses `updated >= -10080m`.
An issue last updated 30 days ago, absent from the local queue, is never queued
by initial reconciliation. Advancing the checkpoint leaves it undiscovered until
an external update or delivery. Known resources are fetched separately and are
not affected by this discovery gap.

The guarded recovery preflight also calls `reconcile_candidates(None)` intending
to obtain a full listing. It can return success while omitting such an issue if
the restored backup does not contain it. This is a completeness defect, not a
guard bypass or a Jira API gateway authentication defect.

`None` now requests all issues in the configured projects; a real checkpoint
retains incremental relative JQL with the existing ten-minute overlap. The
20-page bound still fails closed without advancing the checkpoint. No new
configuration option, state schema, publisher or model behavior is introduced.
Jira's listing remains non-authoritative for deletion; known resources are
still fetched individually.

Regression evidence:

- Against unmodified release234 source: four initial tests failed (old issue
  enqueue, real-core old issue, full-listing JQL, recovery listing); incomplete
  enumeration already failed closed correctly.
- A separate preflight regression returned success but left the old unknown
  resource absent on release234. With the change, preflight queues it without
  running analysis or publishing.
- On the fix, six new tests pass. The real-core test removes every PR and
  supplies no webhook; the old Jira issue produces `preliminary_impact_found`
  with Reporting and `jira_without_diff`.
- 78 targeted service/config/recovery tests passed before the added preflight
  regression; the final six-test module passed after its addition.

Commands (Python 3.12 with the repository's API dependencies):

```bash
PYTHONPATH=src:. python -m unittest tests.service.test_jira_bootstrap -v
PYTHONPATH=src:. python -m unittest tests.service.test_reconcile tests.service.test_m2_regressions tests.service.test_core tools.agent_service.box.tests.test_config tools.agent_service.box.tests.test_recovery -v
```

Local HTTP stands and authored examples establish code behavior, not real Jira
intent quality, target-VM readiness or client benefit. MODEL OFF. No target VM,
deployment pin or published release is changed. This PR does not patch immutable
legacy release14e's connector when a manager runs that older target's code.


## Follow-up validation before merge (PR #89)

Independent agent review identified and the revision fixes:

1. Missing/contradictory completion markers, token cycles and malformed issue
   routing data could silently certify a partial listing. The pager now validates
   each enhanced-search response, including the requested project identity.
2. A second provider reconciliation or Git-ref read could fail after the initial
   preflight listing succeeded. Ordinary reconciliation deliberately catches API
   errors; preflight now checks provider notices and the current graph result
   before its completion checkpoint. Removed-provider notices do not block a
   configured provider, and a repaired graph read clears its stale error notice.
3. VM checker used a path without the provider subdirectory and its original
   hand-authored fixture reproduced that mistake. Tests now use production build,
   queue delivery and DirectorySink, and the checker validates current sink
   receipt plus the standard result contract/request binding.

The added regression matrix covers real HTTP pagination, retry from page one,
ordinary and preflight restart idempotence, HTTP503 during pagination/fetch/a
second read/graph refresh, invalid pages, 20/21-page boundaries, and interruptions
before durable checkpoints. Four cases SIGKILL a fresh interpreter during paging
or after the first durable event/snapshot; a new service on the same SQLite state
completes exactly once. Preflight never runs analysis or publication.

The original 20-page bound is retained and explicit: an oversized project fails
closed instead of silently becoming complete. No new state schema or model is
introduced. Final source/review/CI provenance is recorded on PR #89; no merge,
release publication, deployment pin update or target-VM action is performed.

Final local execution: 104 targeted tests PASS in54.611s, including all final
helper tests. Independent final agent review found no remaining blocking
source finding in scope; details in `jira-bootstrap-2026-11-02/REVIEW.md`.


Further qualification covers old immutable targets: full Jira discovery now
belongs to the manager, rather than assuming that every target's None means
unwindowed search. Target auth/fetch/version semantics are retained. The explicit
`jira_preflight_compatibility.py` subprocess matrix verifies actual downloaded
release14e and234 modules/queues/connectors with two old issues over two pages,
error503/invalid page refusal and repaired retry, and same-token idempotence.
Recovery CI now runs that matrix against published14e and its exact candidate,
in addition to the unchanged real systemd lifecycle acceptance. This changes
neither archive, neither PROFILE nor the standalone old target bootstrap.
