# Bitbucket queue intake — bounded implementation

> Execute inline with executing-plans and test-driven-development; fresh final reviewer. Owner requested Bitbucket PR intake as an additional touchpoint beside Jira.

Goal/design: explicit `bitbucket.mode: queue_only` permits a GET-only polling connector in a separate `publication: dry_run` installation. Reconciliation discovers complete PR listings pinned to configured UUIDs, re-fetches each PR and persists provider=bitbucket/kind=pr snapshots and jobs in the existing durable queue. Metadata includes linked Jira keys; destination tips are not treated as Git merge-bases. The service does not analyze or publish held Bitbucket jobs/intents; status reports the missing Git/core boundary. Jira/GitHub continue through their existing processing in the same test instance. Default probe mode still refuses runtime, and live publication plus queue_only is rejected before state/secrets.

Chosen boundary: queue_only instead of guessing Git/core inputs or enabling live comments. No output-contract/schema-provider expansion for core, Git transport, webhook reception, real service deployment, pin/release changes or paid resources. Existing Bitbucket seed is preserved. A real PR may be created in the pilot via the authorized browser; automatic external intake remains blocked until a dedicated read token and UUID pins are available. Browser observations must not be injected as fake API acceptance.

Base: PR94 head24b93595af3aa523c493e238bdb7ed4cd606b538, separate branch. Seed evidence commit96f3f76 remains separate.

Files/interfaces: new connectors/bitbucket.py (`BitbucketQueueConnector`: fetch, reconcile_candidates, parse_webhook rejection, prepare guard); config.py (`mode`, factory and live guard); envelope.py additive event provider; queue.py optional provider filtering on claim_job/claim_intent; service.py capability-aware claims/notices and PR-kind recognition; actual HTTP tests; report/example/evidence.

Review focus: partial listing/checkpoint, wrong UUID/closed PR/auth revocation, duplicate/reordered revisions/restart, queue-only intents and jobs never consumed or published, held Bitbucket work cannot starve Jira/GitHub, default/live config guards before state/secrets. Future core enablement must reconcile/reopen held jobs rather than assume their intake deadlines remain valid.

- [x] Write HTTP → reconcile → ingest → SQLite tests RED (and existing Jira flow alongside), then minimal implementation GREEN.
- [x] Run targeted queue/fairness/publisher/Jira/GitHub regressions, workflow Ruff and whole Core attempt; retain platform limitations.
- [x] Fresh review and test-first important fixes; create actual pilot PR if browser available; do not claim real API intake without credentials.
- [x] Save evidence/rollback and publish a draft code PR stacked on94; no merge/release/deploy.

Continuation2026-11-04: real token owner handoff complete, actual API sourceprobe and intake/repeat accepted locally; real API pagelen/compactSHA differences and nested404 regression fixed test-first. Final119 targeted PASS and independent42 reader/queue PASS. Linux CI remains separate; no VM deployment.
