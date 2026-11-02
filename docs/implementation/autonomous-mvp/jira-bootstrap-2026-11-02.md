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
