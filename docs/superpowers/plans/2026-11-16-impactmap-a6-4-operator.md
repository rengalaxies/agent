# ImpactMap A6.4 Operator Panel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Connect the approved read-only operator screens to scoped stored jobs/outbox/notices and explicit installation connection/binding metadata.

**Architecture:** A frozen allowlisted metadata object is built from the loaded ServiceConfig, without resolving credentials or probing providers. A6.2 receipts authorize database projections in one read snapshot; pure Python views render escaped HTML consumed by the existing workbench. No dependencies, worker-loop changes, external writes or deployment.

**Tech Stack:** Existing Python/FastAPI/SQLite/native JS/CSS.

**Spec:** `docs/superpowers/specs/2026-11-16-impactmap-ui-admin-design.md`, approved A6.4. Owner requested execution; no scope reconfirmation.

## Global Constraints

- Reviewer403 for all operator JSON/HTML routes; same-origin sessions/no-store/CSRF boundaries preserved.
- No secret values/env references/paths/raw notices/snapshots/comments/HTTP receipts in panel responses.
- Shared corpus scope, latest100 authorized resources, scan budget1000; totals are explicitly this displayed sample, not entire installation.
- No automatic probe/reconcile/retry/restart/publish controls. Worker liveness and tracker/API permissions are NOT_CHECKED unless independently observed.
- Exact known codes and observation times; UNKNOWN/SENDING readback advice, failure separate from stale result. Yandex NOT_CONNECTED preserved.
- Existing variant2 compact14px/28px desktop,23px narrow; role comes from server.

## Review Focus

1. Malicious stored reason/notice/detail/receipt and secret-bearing config must never enter JSON/HTML (Task1).
2. Older/foreign scope rows and notices must not influence totals, IDs, bounds or deep links (Task1).
3. Configured connections or stale inventory timestamps must never imply current access/worker health (Tasks1–2).
4. Bindings before observations, changed Kaiten target and multiple Jira links must remain explicit/unverified/conflicting without exposing forbidden targets (Task1).
5. Direct reviewer routes, page switching and failed logout recovery must clear operator fields and retain a usable session exit (Task2).

### Task 1: Operator read model and configuration metadata

**Files:** create `src/agent_service/ui_operator.py`, `tests/service/test_ui_operator.py`; modify `service.py`, `__main__.py`, `queue.py`.

**Interfaces:** frozen `OperatorMetadata`; `metadata_for_config(config)` extracts publication mode, configured intake providers, repository IDs/provider mapping, tracker IDs/project/board scope and explicit Kaiten bindings. `Service(...,ui_metadata=None)` optional; CLI attaches metadata. `ServiceStore.ui_operator(scope, metadata, section)` returns read-only operations/connections projection within one transaction; absent metadata stays unavailable, never introspects connectors or private config.

- [x] Write real Store/config tests: FAILED+STALE, pending/UNKNOWN outbox including failure intent; known notices without detail; foreign/unstamped records absent; repeated reads same SQL dump; config secrets/paths omitted; Jira/Kaiten/Yandex explicit, no inventory-as-access; valid/conflicting bindings with project/repository filtering.
- [x] Observe RED missing module/method. Implement bounded exact-field projections; reject unknown code text as UNKNOWN; provider/global notices only when attributable to current configured context (resource notices require receipt).
- [x] Run operator+existing scope/views tests, expect green. Commit.

### Task 2: Protected API, operator views and workbench lifecycle

**Files:** create `ui_operator_views.py`; modify `ui_api.py`, `ui_web/workbench.js`, `workbench.html`, `workbench.css`, `session.js`; extend HTTP tests.

**Interfaces:** existing operator GET `/ui/api/operations`, `/ui/api/connections` return safe data plus escaped `{result_html,observed_at}`; only operator. Workbench hides changes sidebar in operator section, renders real metadata and links to scoped result. Auth refresh/manual+opt-in GET-only poll reuse A6.3 logic.

- [x] Write HTTP tests proving real JSON200 for operator, reviewer403/direct route403/POST405/no-store; snapshot and raw notice canaries absent; observation and UNKNOWN recovery advice present. Observe RED against placeholders.
- [x] Implement genuine read-only operation/connection views, sample counters and notices, resource links, separate queue/analysis/publication, exact configured binding states. No guessed current health or future controls.
- [x] Fix carried A6.3 retry-logout UX after failed request+hide/return; browser RED→GREEN, restore only retry exit, never data. Check operator content clears on logout/scope change.
- [x] Run focused UI/API/config/service tests and isolated browser scenarios1440/390 using actual AuthStore/Store/config metadata; inspect focus, unknown delivery, connection errors, missing Yandex, binding conflict, role403 and GET-only DB immutability. Commit.

### Task 3: Review and handoff

**Files:** `docs/operations/a6-4-2026-11-16/`, access guide, approved spec, roadmap, CHECKPOINT.

- [x] Run broader relevant service regression, build wheel and compare shipped UI modules/assets. Known root-project SQL Mac RLIMIT_AS baseline failures remain an explicit global gate; rerun root only if this work adds a plausible regression beyond service/config/UI.
- [x] One fresh whole-source review per executing-plans; fix Important issues RED→GREEN. Save browser/test/build/DB hash evidence and manifest. Stop QA stand/delete temporary credentials.
- [x] Update checkpoint/roadmap: A6.4 source/local delivery, A6.5 Linux/TLS/auth backup/restore and real tracker links/owner acceptance next. Keep managed branch/worktree, no merge/push/deploy.

## Execution record

Base `cee0b49`; managed linked worktree `codex/impactmap-batch-00`, clean. Prior root1342 run49 failures/1error reproduced baseline in unchanged product SQL workers (Mac RLIMIT_AS); not a UI failure. Approved scope reused; no new design gate.


Execution: source e96798d; baseline62 PASS, final focused107 PASS, broad491/4 skips PASS (574.581s). Additive scoped notice observations introduced after review, no legacy backfill.3 Important fixed once with RED→GREEN;2 Minor preserved in report. Diagnostics ruling and self-run browser/build/deployment boundary recorded in report/CHECKPOINT. QA stands/credentials removed; next A6.5.
