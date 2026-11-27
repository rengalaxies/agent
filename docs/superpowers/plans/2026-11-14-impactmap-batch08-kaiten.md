# ImpactMap batch08 — Kaiten adapter

> Execute inline using executing-plans/TDD, one fresh final review. Reuse existing managed checkout.

**Goal:** working Kaiten publication pipeline for explicitly bound Bitbucket PRs; real tenant acceptance only when login/access are available.
**Architecture:** a Kaiten HTTP client/renderer plus a wrapper around the existing Bitbucket analysis connector and a scoped publication backend. Reuse existing core/queue/Publisher, add opt-in kaiten_delivery configuration. Polling only; do not invent a webhook signature.
**Tech:** existing Python/Pydantic/HttpClient, unittest and local HTTP stand; no dependencies.
**Spec:** batch08 in handoff, ADR001, user requests continued technical development; tenant rengalaxies.kaiten.ru supplied while work starts.

## Global constraints

Exactly one explicit binding per PR, allowed board IDs, current bot identity verified through /api/v1/users/current; immutable scoped IDs; full semantic version before presentation truncation. One updatable comment with stable marker, ≤4096 chars including marker. No blind retry of uncertain writes. Preserve Jira, MODEL OFF, no deployment/push.

## Review focus

- Wrong bot/token, moved/archived/deleted card, partial pagination: no wrong-target write.
- Relink/source change during prepare or publish: generation superseded, old target never updated.
- Lost write response/restart: existing Publisher reconciliation finds owned marker.
- Long result/untrusted marker text: marker preserved once, reduction explicit, full result stays in outbox.
- Config uses pinned host, credentials env only; modes isolated from Jira and GitHub.

### Task1: Kaiten read/comment/renderer

Files: connectors/kaiten.py, tests/service/test_kaiten.py.
- [x] RED read scope/semantics/comment noise, paginated read, ownership and marker truncation tests.
- [x] Implement scoped reads, identity preflight, complete lists, POST/PATCH with unknown malformed-write outcome; local request limiter ≤10rps; GREEN.

### Task2: Bitbucket binding/runtime

Files: connectors/bitbucket_kaiten.py, config.py, tests/service/test_kaiten_delivery.py.
- [x] RED wrapper full semantic version/context, target guard, config opt-in and queue/restart tests.
- [x] Implement explicit configured binding, recheck before/after prepare, scoped comment IDs and owned update; config isolated kaiten_delivery and dry-run; GREEN.

### Task3: verify/real acceptance/handoff

- [x] Focused Jira/Bitbucket/Publisher regressions, local HTTP cycle and error/restart cases.
- [x] Fresh review; one substantive fix pass RED→GREEN.
- [x] Real tenant setup/API create/update verified with owner-authorized key; hybrid source explicitly local. Cloud Bitbucket/process-restart AC remains open.
- [x] Evidence, CHECKPOINT copies, local commit. Full08 DONE requires real e2e; local completion alone is partial.

## Ledger

User initially confirmed no accounts, then created Kaiten and supplied rengalaxies.kaiten.ru. Browser opened login and handed off; no password/token requested in chat. Yandex access postponed by owner.
Ruling: explicit installation bindings rather than guessing card IDs from PR prose — deterministic scope and relink safety; cost if wrong: operator must configure each pilot PR.
Pre-flight: task2 depends on task1 scoped task+comment interface; wrappers retain Bitbucket provider/kind, no core schema changes. Native Kaiten connector is publication/context only, not a standalone Service task trigger.

Task1/2 complete locally: RED missing modules →5 unit tests and binding/runtime tests GREEN. Worker fixture nested object and card archived field corrected from actual contracts; no production relaxation. Source-version tests use full Publisher marker line, not marker ID.
Fresh review: all8 P1/P2 findings accepted, RED→GREEN in one pass; docs/integrations/batch08/review.md maps tests. Opt-in expected_intent keyword is the smallest additive Publisher extension; legacy backends receive no extra args. No second reviewer.
Final checks:145 tests118.795s OK,4 skipped Linux-only SIGKILL. Race test advances the existing create settle window rather than removing it. Lost applied POST plus reconstructed store verified; final whole suite green.
Live setup: owner signed in and explicitly approved API-key creation/use. UI-created board1982649, API-created dedicated card74759475. Key file0600 in ignored work/batch08/private; not printed/staged. Existing certifi CA bundle selected per-process to fix missing default CA path; no TLS weakening or environment installation.
REAL_API probe PASS (POST/PATCH/readback same comment93785697). Actual CoreAnalyzer + queue + real Kaiten hybrid PASS: authored local Bitbucket HTTP/Git only, USEFUL/POSSIBLE_TRUNCATION→ABSTAINED/no_supported_delta, same result-comment93785713, owned marker count1, repeat and reconstructed service idle. Initial hybrid harness assertion expected ANALYZED after delivery, but queue correctly says DONE; resumed same durable state without resetting source/marker. No real cloud Bitbucket source or OS process restart claimed.
Ruling: accounts now exist for Kaiten, so execute authorized live API proof immediately; keep true cloud Bitbucket E2E pending instead of relabelling authored source. Cost if wrong: additional isolated diagnostic comments on explicitly prepared board only.
Keep existing branch/worktree; commit locally, no deployment/push/merge/archive. Full AC08 and all-trackers10 stay open.
