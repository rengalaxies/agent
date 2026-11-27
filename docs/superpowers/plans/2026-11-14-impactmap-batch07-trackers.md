# ImpactMap batch 07 — tracker API contract

> Execute inline with superpowers:executing-plans and TDD; one fresh final reviewer. Preserve the current managed checkout and local branch.

**Goal:** documented, executable minimum contract for Kaiten/Yandex Tracker result publication, preserving Jira.
**Architecture:** additive shared identity/protocol helpers; standalone diagnostic API probe, not runtime provider registration. Keep Publisher, Bitbucket/Jira facade and analyzer unchanged. Production adapters belong to08/09.
**Tech Stack:** existing Python3.13, stdlib, existing HttpClient, unittest/local HTTP server.
**Spec:** batch07 of `/Users/user/Documents/ChatGPT/ВКР/ImpactMap_пачки_и_передача_контекста_2026-11-14.md`.

## Global Constraints

- Bitbucket remains source; exactly one explicit configured tracker target; no cross-task edits.
- Provider/tenant/native immutable identity; display aliases are not storage keys.
- Stable marker plus bot author, complete listing or fail, no blind retry after unknown create.
- Semantic version excludes comment metadata; remote revision is separate from analysis generation.
- No invented live success or new tracker credentials. No VM deployment, push, merge or core rewrite.

## Review Focus

- Concurrent or interrupted probe: no automatic duplicate create.
- Foreign-host/path/cursor pagination: no credential forwarding or incomplete success.
- Same native IDs across tenants and target relinking: no cross-target comment update.
- Malformed/oversized/deleted/mismatched provider responses: no false PASS or destructive recovery.
- Own comment changes and mutable aliases: no accidental analysis version churn.

### Task 1: identities and minimum publication protocol

**Files:** new connectors/tracker_contract.py; additive Protocol in connectors/base.py; tests/service/test_tracker_contract.py; docs/adr/001-tracker-publication.md.
**Interfaces:** TaskIdentity(provider,tenant,native_id), CommentIdentity(task,native_id) with canonical encode/decode and expected-target guard; semantic_version(task, explicit semantic_fields, closed); PublicationBackend structural Protocol matching existing Publisher use.
- [x] Write tests for tenant/provider separation, string IDs, delimiter-safe identity, target mismatch, semantic comment-noise exclusion and full-content version change; run RED.
- [x] Implement helpers and protocol; write ADR and operation map; run GREEN.
**Expected:** identity cannot collide across scopes, existing Jira facade remains compatible.

### Task 2: reproducible create/update API probe

**Files:** tools/agent_service/tracker_api_probe.py; tests/service/test_tracker_api_probe.py; docs/integrations/batch07/README.md and evidence.
**Interfaces:** non-secret JSON config/provider/instance/task/scope/bot/token_env; dedicated local output journal; read-only default, explicit --write, journal resume. Actual HttpClient requests with scoped paths. Kaiten offset/applied-limit; Yandex verified Link cursor, never use arbitrary returned URLs. Read task, enumerate, create once, read back, PATCH same comment, read back, repeat list => one owned marker. Unknown create stays unresolved if absent; never re-POST.
- [x] Write local HTTP tests for both wire formats, pagination, read-only behavior, wrong scope/author, timeout-after-create resume, incomplete/hostile listing; run RED.
- [x] Implement probe, safe receipts and CLI. No token/body logging. Persist pending-write before request; exclusive lock/atomic state. Run GREEN.
- [x] Discover configured access without revealing secrets; run live only on explicitly supplied dedicated targets. If unavailable, record LIVE_NOT_RUN, exact missing inputs, local proof separately.
**Expected:** local protocol proof for both providers; live capability honestly separated.

### Task 3: regression, review and handoff

- [x] Run new tests plus existing Jira, linked backend, delivery/errors/races/restart/connection suites; expected all PASS.
- [x] One fresh review of07 diff; reproduce important findings RED→GREEN in one fix pass and run appropriate final suite.
- [x] Record operation sources, AC status/evidence and missing live prerequisites; update both CHECKPOINT copies; commit locally.
**Expected:** no runtime provider added, Jira regression verified;07 only fully DONE if real API update probe succeeds for both trackers.

## Ledger / decisions

Ruling: user's «пока всё делай ты» delegates routine design; proceed with additive contract and diagnostic probe, no repeated design approval. Cost if wrong: local reversible tools/docs only.
Ruling: no target/account may be invented; absent credentials mean partial07 with explicit LIVE_NOT_RUN, not a mock presented as a real API. Cost: live AC stays open until dedicated targets exist.
Pre-flight: task2 consumes task1 identities/marker rules; task3 reads journals and tests. No shared-interface conflict found. Existing Jira IDs stay legacy to avoid persistence migration in07.

Task1 complete: RED missing Protocol/helpers → GREEN8 identity/Jira facade tests. Task2 local implementation complete: RED missing module → GREEN7 wire tests; extended12 found stale error on successful resume (root cause: prior error remained in journal), RED→GREEN by clearing only top-level current error on PASS, historical failed events preserved. Live access unavailable in bounded discovery; LIVE_NOT_RUN. Sandbox disallows loopback bind by default; local-only tests run with approved escalation.

Final review: all9 substantive findings accepted/fixed in one pass; detailed matrix docs/integrations/batch07/review.md. RED logs in /tmp/impactmap07-review-red*.log; final suite115 tests81.653s,111 passed/4 skipped Linux-only SIGKILL paths. Final extra deep-JSON test initially assumed a runtime recursion bound; full suite can parse that depth, correctly rejected nested shape instead. Made input syntactically invalid independent of recursion configuration; final rerun green. Final local wire receipts regenerated against corrected code; earlier ignored journals preserved, public receipts supersede initial local proof.
Owner explicitly confirms no accounts/access; Yandex access deferred, requests continuing technical development. Live07 stays NOT_RUN; next08 local Kaiten work. Keep branch/worktree, commit locally per prior authorization.
