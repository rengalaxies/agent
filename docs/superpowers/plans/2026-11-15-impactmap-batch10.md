# ImpactMap10 Implementation Plan

> Execute with superpowers:executing-plans, inline in existing managed worktree. Same autonomous execution method already selected; one fresh final reviewer.

**Goal:** проверяемый локальный candidate10, операторская диагностика и полные результаты; отдельная запланированная UI/admin пачка.
**Architecture:** существующие queue/API/publisher/release builder; read-only store query, без новой БД или UI.
**Tech Stack:** Python/unittest/SQLite/FastAPI/hash-locked offline release.
**Spec:** docs/superpowers/specs/2026-11-15-impactmap-batch10-design.md

## Global Constraints

- Base8334b69; existing codex worktree; local commits only, no push/merge/prod deployment or remote mutation.
- Core/profile/output/limits/normalization2/scorer/oracles/historical evidence immutable.
- Original10 three cycles per tracker remain; Yandex absent, cannot mark10 fully DONE. A6 is future discussion, not UI implementation.
- Read-only diagnostic under existing operator token; no public result URL or credentials in artifacts.

## Review Focus

- New failed generation must never silently display older successful analysis as current.
- Stale/closed/superseded and unknown resources stay explicit, API cannot traverse paths or return another resource.
- Result queries/listing must not mutate state, invoke connectors or expose HTTP/config secrets; strict authorization and bounded listing.
- PR base must be actual analyzed base, not mislabeled destination tip.
- Build from committed source only; local/Linux/live gates distinguished and old reports unmodified.

### Task 1: CI and version diagnostics

Files: tests/graph_demo/test_graph_cli.py; src/agent_service/publisher.py; tests/service/test_jira_presentation.py; work/batch10 baseline logs.
Interfaces: GraphCLI transport/deadline contract unchanged; _versions(snapshot,kind,generation) plus validated view snapshot metadata.

- [x] Run full baseline; isolate failures and root causes. Record host/dependency constraints.
- [x] Reproduce transport/deadline issue with a deterministic test; isolate parser/error paths from system interpreter latency without weakening cancellation/deadline/core identity.
- [x] Add RED regression for full result version base/head from validated snapshots; implement exact base/fallback labels. Run graph_demo + presentation suites GREEN.
- [x] Commit source with meaningful verification. Expected: relevant suites0 failures.

### Task 2: Read-only result diagnostics

Files: src/agent_service/diagnostics.py (new); src/agent_service/queue.py; src/agent_service/api.py; tests/service/test_diagnostics.py (new).
Interfaces: ServiceStore resource_diagnostics(resource_id) returns one consistent resource/current job/latest stored analysis/delivery projection or None; resource_listing(limit) bounded safe metadata. GET /resources?limit=1..100, GET /result?resource_id=... (max512 chars), existing status-token authorization.

- [x] RED tests: unauthorized/unconfigured token, missing/unknown, limit validation, delivered result, queued newer generation, failed current job, closed and stale, cross-resource query, no writes/secret-bearing fields.
- [x] Implement single read transaction projections and no-store authenticated API; return current result if present, otherwise last available explicitly stale with current failure metadata; no file-path access.
- [x] GREEN relevant service suites; run complete tests after source settles. Expected: all feasible tests pass, exact platform skips disclosed.
- [x] Commit source, freeze before artifact build.

### Task 3: Candidate, evidence and handoff

Files: docs/operations/batch10-2026-11-15/; docs/operations/impactmap-diagnostics.md; docs/product/roadmap-2026-11-14/UI-ADMIN-BATCH.md; roadmap/CHECKPOINT/mirror.
Interfaces: source commits Task1/2 → existing release.py build/verify, new report receipts; operator API feeds later A6 discussion.

- [x] Save GitHub/local/installed-runtime read-only reconciliation. Build Linux release with unchanged lock; verify tree/wheels and source identity. Record unavailable gates instead of inventing PASS.
- [x] Exercise local candidate change/fix/replay/reopen and isolated state backup/restore; Linux recovery if existing safe stand available. No production mutation.
- [x] Write operator/result/candidate installation/recovery instructions and original10 AC matrix; add A6 with discussion scope and measurable AC.
- [x] One fresh whole-batch review and one substantive fix pass if needed, preserve evidence. Verify hashes, CHECKPOINT mirror, local commits; keep worktree. Expected: technical preparation evidenced;10 remains partial where real prerequisites absent.
