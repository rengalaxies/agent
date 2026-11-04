# Bitbucket PR queue intake — 2026-11-02

Status: **actual Bitbucket API → local durable queue accepted on 2026-11-04; repeat intake has no duplicate**. Implementation began2026-11-02. No VM/release/pin change.

## Behavior delivered

Set `bitbucket.mode: queue_only` explicitly in a separate `publication: dry_run` installation. Existing probe mode remains the default and still refuses runtime construction. Queue-only with live publication refuses before state/credential access. No write API, webhook acceptance, Git clone/fetch or core PR request is enabled.

The connector uses configured workspace/repository UUIDs and graph-ID scope, rechecks private metadata, lists all open PRs with the existing bounded fail-closed reader and refetches before ingestion. `EventEnvelope.provider` now admits `bitbucket`; snapshots use `kind=pr`, stable UUID resource identity and semantic versions. They retain source/destination refs, title/description/draft and explicitly named `destination_tip_sha` (not a computed merge-base). Linked Jira keys are extracted only from configured Jira project keys when a Jira connector is configured.

Jobs remain `QUEUED`, attempts0, with the status notice `analysis_not_connected / bitbucket / queue_only:git_core_not_connected`. Jobs and publication intents from held providers are excluded at claim time. Configured Jira/GitHub providers continue normally. Removing a provider holds its durable events/jobs/intents rather than crashing a remaining Jira/GitHub worker; no rows are deleted. Polling is supported; unsigned Bitbucket webhooks return404.

The ordinary service commands can be used with this explicit queue-only configuration. The existing `bitbucket-probe` command remains read-only and never opens queue state. Use a dedicated installation/database; do not edit the working Cloud.ru installation for this draft feature.

## Actual external touchpoint

[Bitbucket Orders PR #1](https://bitbucket.org/rengalaxies/agent-pilot-orders/pull-requests/1): **OPEN**, source `KAN-4-pilot-page-limit`, destination `main`.

- Head commit: `cff5845d729cb97acb913938a1c67000c6fc662a`.
- Destination main observed at creation: `61ed1494ce9849d7fa7865b30447326e9c3f8e4e`.
- Diff: only `api.py` line8, page_size100→20. No merge occurred; main was not changed.
- Title/commit reference KAN-4; the saved PR description renders an actual Jira card: `KAN-4: orders: уменьшить page_size по умолчанию у GET /orders со 100 до 20`, status To Do.
- This proves the UI PR/Jira reference, not automatic agent analysis or Jira Development panel acceptance. No service comment was posted and no Pipeline was started. The PR description explicitly says intake/analysis is not yet qualified.

## Actual API acceptance — 2026-11-04

The owner created a Bitbucket-only token with `read:repository:bitbucket` and `read:pullrequest:bitbucket`, expiring2026-11-11. The token was saved only under the private local directory with0600; no value was printed, committed, sent to Jira or transferred to Cloud.ru. The earlier lost token was not changed. [Atlassian token permissions](https://support.atlassian.com/bitbucket-cloud/docs/api-token-permissions/).

Both private repository identities were verified through real API GETs:

- Workspace: `e0b65402-98d3-432d-9ba0-8e92884d8bfb`.
- Orders: `ce63c558-64b3-462f-9ab9-1b954c14f5d9`.
- Reporting: `0056f8cf-dd82-4021-838f-6e984ba96e53`.

The real probe returned Orders openPR1, Reporting openPR0. First reconciliation in dedicated installation `bitbucket-intake-local-20261104` produced one INGESTED event and one QUEUED job. A new service instance on the same local database repeated actual API reconciliation: enqueued0, generation1, attempts0, intents0. Full head/destination tip match the UI commits above. No browser observation was injected as a fake API event.

This isolated intake configuration has no Jira connector, so its scoped `linked_jira_keys` list is empty; the real PR title/description still reference KAN-4 and render its Jira card. Combined Jira/GitHub/Bitbucket processing and scoped key extraction are covered separately by HTTP tests. Do not claim cross-provider runtime correlation or a new service comment from this isolated run.

See [actual probe](evidence/actual-probe.json), [first intake](evidence/actual-intake-first.json), [repeat](evidence/actual-intake-repeat.json), and [persisted resource verification](evidence/actual-resource.json). **Actual API → local queue: PASS; API → Cloud.ru queue: NOT_RUN.**

Real API acceptance exposed two differences absent from the initial fixtures: PR listing rejects pagelen100 (`Invalid pagelen`) while50 succeeds; PR source/destination hashes are12-character abbreviations. HTTP RED→GREEN regressions now enforce a conservative50 and resolve abbreviated hashes through `/commit/{prefix}` within the same pinned repository, requiring a full40-character hash with matching prefix. Compact fork hashes explicitly fail without expanding repository scope. Review additionally found commit404 must not masquerade as missing PR404; the corrected error preserves an open queued PR. No Git merge-base is computed by this intake.

The local Python installation had no default CA bundle. The private helpers use installed certifi for TLS verification; certificate validation was never disabled. Production HTTP code was not changed to bypass trust.

Private helpers remain under `/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-intake-20261102/`: hidden-input `enter-credentials.py` and one-shot `run-intake.py`. The first was superseded by owner token handoff plus safe private capture; the second performed both real intake passes. Never source credentials as shell arguments or copy their values into chat/repository.

## Verification

- RED: all13 initial missing-mode/intake tests failed; implemented polling/factory/provider/filter behavior.
- Final targeted **119/119 PASS** on2026-11-04: queue intake15 and reader27, existing reader/probe/queue/fairness/connection/reconciliation/delivery/error regressions. Existing Jira/GitHub jobs complete while Bitbucket remains queued.
- Independent review found a P2 on provider removal: unrestricted claims and due-event lookup could consume orphan Bitbucket rows and crash. Regression reproduced KeyError before the fix; configured-provider event filtering and always-eligible job/intent filtering fixed it. Reviewer reran all15 intake +27 reader tests: PASS, no remaining important findings.
- Workflow Ruff F401/F811/F841: PASS. Whole local Core discovery completed1015 cases with44 failures/40 errors/4 skips; it started before the final fixture/real API fixes and is NOT PASS. It includes the then-unfixed tuple fixture assertion plus product-specific `symlink_output_parent`/verifier startup failures on this Mac. Exact failing test names are retained in evidence/core-local-summary.txt. Final source requires its own Linux CI; no full local PASS is claimed.
- This branch Linux CI is a separate gate. Base PR94 had four workflows PASS before this change.

## State and rollback limits

The durable event provider extension does not change table layout or core output contracts. It nevertheless introduces rows older binaries do not understand. **Do not downgrade an older worker onto a database containing Bitbucket rows.** Use a matching pre-intake state backup and old configuration for binary rollback. Removing Bitbucket from the new binary's configuration safely holds its rows; this is not proof of old-binary rollback compatibility. Future release qualification must cover the new provider/legacy recovery boundary before deployment.

Held jobs have ordinary intake deadlines; a later implementation enabling analysis must reconcile/reopen or otherwise migrate them explicitly, rather than claiming an expired backlog was analysed. Git fetching, a validated Bitbucket core trigger, multi-provider graph pinning, publication writes, real external race/error acceptance and deployment remain unfinished.

To undo the external pilot setup, decline PR1 and retain the test branch (or delete it only after confirming no later work). This iteration did not merge into main. No VM restore is needed. Code changes remain on a separate draft branch stacked on PR94; seed evidence is separately committed on `codex/bitbucket-pilot-seed-evidence`.
