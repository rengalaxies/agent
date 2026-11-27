# ImpactMap08 — cloud Bitbucket→Kaiten acceptance

> Execute inline with executing-plans/TDD and one fresh final review; reuse current managed worktree/branch. No release installation or shared-queue changes.

**Goal:** close remaining08 evidence with real Bitbucket PR/source and real Kaiten, Linux process recovery, replay and target lifecycle checks.
**Architecture:** a tracked acceptance worker/control helper run in an isolated Linux directory with a byte-hashed candidate source bundle, own policy/mirrors/SQLite and explicit binding. Existing installed release remains active. SCM changes use a dedicated branch/PR and deterministic change/fix, never main or PR4.
**Tech:** existing Python/HttpClient/CoreAnalyzer/Service, SSH pinned host, existing Linux venv; no dependency installation.
**Spec:** original batch08 AC and docs/product/roadmap-2026-11-14/REMAINING-2026-11-14.md, ADR001.

## Global constraints

- Source state e22413a contains08 implementation c44a3c6; installed runtime currently a02ffa7, MODEL OFF.
- Real cloud source/pins, actual provider receipts; no local stand labelled as cloud.
- Own isolated mirrors/state/processes; never read/write production SQLite via a new worker.
- Credentials remain memory/private0600; SSH stdin only for token transfer, no argv/log/source artifact secrets.
- Dedicated PR branch, no merge/force push/shared branch modification. Existing PR4 stays untouched.
- Writes only to explicitly prepared Kaiten test cards and service-owned marker comments; unknown writes reconciled, no reset/blind recreate.

## Review focus

- Wrong source/ref/target or production state path must fail before any external write.
- Process interruption can leave UNKNOWN; restarted process must reuse stable installation/resource/queue and marker.
- Source changes/fixes produce verified pins and same native result comment, no generation selection hiding failure.
- Relink/delete/archive/off-board never updates another target or kills worker; documented live versus injected faults.
- Returned artifacts contain only necessary receipts/hashes/metrics, never token/config/Git/source export from VM.

### Task1: preflight, controlled SCM target and worker harness

- [x] Verify clean local checkout and existing runtime read-only, configured scope and read API.
- [x] Prepare dedicated cloud branch/PR with one supported API change; verify main/PR4 unchanged.
- [x] Write acceptance worker/report assertions tests RED, implement safe one-shot/durable fault hooks GREEN.
- [x] Bundle approved local src/tests/constitutions/tools into isolated Linux root, verify source hashes/import roots; copy existing mirrors locally on VM and fetch cloud into copies.

### Task2: actual cycle/process and negative checks

- [x] Real cloud change→USEFUL targeted finding; readback current marker/native ID, full source pins.
- [x] SIGKILL at controlled publication point, restart real child interpreter on same state; one result survives, repeat idle.
- [x] Cloud corrective commit→expected no-supported-delta or resolved finding; same native result ID; replay idle.
- [x] Live own target relink, comment disappearance, unavailable/archive card; restore primary binding safely. Auth401 actual if useful,429/5xx injected/local when forcing real provider failure is inappropriate.
- [x] Execute previously skipped Linux SIGKILL tests on this candidate.

### Task3: verify/review/handoff

- [x] Appropriate tests and fresh review of helper/new fixes, one substantive RED→GREEN pass.
- [x] Verify installed worker/release unaffected, main/PR4 unchanged, all own artifacts/remaining boundaries explicit.
- [x] Update08 acceptance/CHECKPOINT/remaining map, preserve private state, local commit only.

## Ledger / rulings

Preflight: read-only Bitbucket credentials work, configured private orders/reporting pilot repos verified. Linux installed worker a02ffa7 active; no installed config/state touched. Kaiten credential already authorized and stored locally; no new token needed.
Ruling: dedicated branch/PR instead of reusing PR4 — preserve the prior Jira demo; the existing polling Jira worker may ingest the new unlinked test PR and record its established no-linked-Jira refusal. No linked Jira task/comment will be changed deliberately. Record any such production observation separately.
Ruling: run candidate in isolated Linux state using existing venv rather than install it — tests actual process semantics without replacing the current deployment; cost: this closes acceptance evidence, not a production release.
User delegates routine setup; no repeated design approval needed. Browser used only where read-only API credentials cannot create the SCM test change.

## Final ledger15.11

All original08 AC met in isolated cloud candidate scope; no production release installed. Actual evidence: docs/integrations/batch08/cloud-2026-11-15/README.md and acceptance.json. One fresh reviewer and one fix pass; helper12 local tests, full157 Linux tests including4 SIGKILL with zero skips.

Change/fix and both replay PASS on the same native93817019. Verified SIGKILL→lease expiry→new process/sameDB→DELIVERED/wrote=false. Target relink/comment deletion/recreation/archive/restore PASS. Delete-card controller stopped on follow-up403 instead of404; original failure preserved, no DELETE retry. Real Service probe proved visible safe refusal/unchanged queue/no writes; UI reported unavailable. Returned primary successfully, same93817019, notices cleared. This is not proof of condition3/server erasure, and403 remains ambiguous. No production behavior was changed to convert403 into a silent deletion.

Explicit owner approvals: token creation/use; transfer of existing token to dm-p1-ui for this isolated run and removal afterwards; later, full disposable74807549 lifecycle including own result/card deletion. Auto review initially rejected transfer and destructive lifecycle until the corresponding explicit approvals arrived. Operations resumed within those scopes. Temporary remote secrets.json was removed under lock; production secrets untouched.

Installed worker remained active a02ffa7/PID60331/same config hash. Both main refs and PR4 unchanged. PR5 left OPEN without merge. Full outbox URL/diagnostics and compact base display deferred to10; independent06/01/11 and Яндекс remain open.
