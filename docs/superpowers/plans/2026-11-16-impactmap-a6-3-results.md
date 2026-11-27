# ImpactMap A6.3 Working Results Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Replace the fixture-only results surface with a compact, authenticated workbench showing saved service results and pinned evidence coordinates.

**Architecture:** Keep FastAPI and the A6.2 scope receipts. A read-only view endpoint renders escaped HTML fragments from one consistent SQLite snapshot; a small same-origin browser controller loads those fragments, verifies sessions, handles navigation and optional read-only refresh. The existing JSON endpoints stay available. No new runtime dependency or arbitrary source-reader endpoint.

**Tech Stack:** Python, SQLite, FastAPI, native browser JS/CSS/HTML.

**Spec:** `docs/superpowers/specs/2026-11-16-impactmap-ui-admin-design.md` (approved, variant2, compact typography). User explicitly requested execution of next batch; continue inline without a second approval.

## Global Constraints

- One installation/shared corpus scope, reviewer and operator, same-origin session authentication; no browser service token.
- Read-only first UI; refresh must not analyze, reconcile or publish. No VM/runtime deployment or real tracker writes.
- Latest100 scoped resources; explain legacy unstamped exclusions and lack of full history.
- Analysis, freshness and publication are independent; unknown/incompatible/partial never become general success.
- Preserve evidence repository/path/commit/blob/hash/lines. Missing quote is explicit; never read a current branch or arbitrary path.
- Desktop1440/mobile390, body14px/h1 desktop28px/mobile23px, visible keyboard focus,44px controls.

## Review Focus

1. Forged stored HTML/path/URL must remain inert text; no arbitrary href or file read (Task1).
2. Current failure with a saved prior result must show both failure and STALE; CLOSED and UNKNOWN stay distinct (Task1).
3. Scope changes, absent receipts and direct IDs must disclose neither fragments nor hidden counts (Tasks1–2).
4. Expiry, logout, pagehide, background visibility and out-of-order navigation must clear private content and stop refresh (Task2 browser scenarios).
5. Empty/filtered/bounded lists must not imply absence of impact; read refresh must leave service DB identical (Tasks1–3).

### Task 1: Consistent read model and escaped result views

**Files:** modify `src/agent_service/ui_scope.py`, `queue.py`; create `ui_views.py`, `tests/service/test_ui_views.py`.

**Interfaces:** `ui_workspace(connection, scope, resource_id=None)` and `ServiceStore.ui_workspace(scope, resource_id=None)` return listing plus optional selected detail in one read transaction. `workspace_view(data)` returns `{list_html, result_html}`; renderer consumes only the A6.2 projection, never raw snapshots/publisher documents.

- [x] Write tests using real ServiceStore receipts for current, stale+failed, closed, partial, no result, incompatible and unknown job/publication codes; assert independent badges, evidence pins, escaped malicious text and absence of arbitrary links/private payload.
- [x] Run `python -m unittest tests.service.test_ui_views -q` with existing project PYTHONPATH/venv; expect failing missing workspace method before implementation.
- [x] Implement consistent snapshot and pure HTML rendering, bounded scoped search in browser, safe fixed internal links, explicit source quote unavailability. No history comparison or source fetch.
- [x] Run views+scope+diagnostics tests; expect green and unchanged SQLite dump after repeated reads. Commit Task1.

### Task 2: Protected workbench and session lifecycle

**Files:** modify `ui_api.py`, `ui_web/login.js`, `session.html`; create `ui_web/workbench.html`, `workbench.js`, `workbench.css`; extend `tests/service/test_ui_api.py`.

**Interfaces:** authenticated `GET /ui/changes`, `/ui/result?resource_id=...` serve shell; `GET /ui/api/view[?resource_id=...]` returns Task1 fragments and observation time, unknown/ungranted ID404. `/ui` and login lead to changes; session page retained. Whitelist assets only.

- [x] Write HTTP tests proving anonymous redirect/401, valid result view200, missing/direct foreign ID404, invalid ID400, safe no-store headers and POST405. Observe RED on missing routes.
- [x] Implement compact variant2 shell; account role comes from `/me`. Operator destinations show honest pending-A6.4 state, with reviewer gate on server. No fake role or generation controls.
- [x] Controller clears private DOM before revalidation and on pagehide/hidden/logout/expiry, uses monotonic relative TTL, ignores superseded responses, restores direct result after login via session-memory non-secret path, provides manual refresh and opt-in30s visible-only GET refresh. Unconfirmed logout remains an error; no hidden polling.
- [x] Run all UI+diagnostics tests; expect green. Browser first observe old `/ui/changes` absent, then verify actual temporary-account login/list/result/evidence/stale/partial/unknown/notfound/logout+expiry and mobile no overflow. Capture author-only evidence with labels, no password/token payloads. Commit Task2.

### Task 3: Verification, review and handoff

**Files:** create `docs/operations/a6-3-2026-11-16/` report/reproducer/manifest; update access guide, spec, roadmap and CHECKPOINT.

- [x] Run project command `python -m unittest discover -s tests -q` with project PYTHONPATH/venv; inspect all errors/skips, record environmental limits separately. Build wheel and verify packaged workbench assets byte-identical.
- [x] Execute browser read-refresh trace and compare service SQLite dump before/after; no analyze/publish/connector calls. Review whole A6.3 diff with a fresh reviewer as required by executing-plans; fix important findings with RED→GREEN.
- [x] Stop/delete temporary credential stand; preserve original fixture prototype. Commit tested source and report, mirror CHECKPOINT, keep managed worktree/branch. Next A6.4 operator panel; Linux/TLS/tracker-linked owner acceptance remains A6.5.

## Execution record

Base `b0c4104`; existing linked worktree on `codex/impactmap-batch-00`, clean. Approved UI scope unchanged. Evidence coordinates are the first-version evidence surface; source quotes and external links require a separate pinned-reader design and are deliberately not invented.


Execution complete source/local5d3502d: focused62 PASS; full project1342/49fails/1error/4skips with preserved inventory. Product SQL-worker fails equally on baseline and current due Mac RLIMIT_AS; no protection bypass or unrelated source change. Source ready only within stated A6.3 local scope, global green/merge/deploy gate remains open. Browser native anchor/broadcast/poll/expiry verified, both service DB hashes unchanged, temporary credentials/stands removed; prototype retained. Minor retry logout tracked in report; rulings preserved there and CHECKPOINT.
