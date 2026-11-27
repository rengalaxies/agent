# ImpactMap A6.2 Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans inline, task-by-task. One final independent review.

**Goal:** Уменьшить типографику по замечанию владельца и реализовать настоящие локальные учётные записи/сессии/роли и fail-closed UI API одной установки.

**Architecture:** Отдельный закрытый SQLite auth store, scrypt, opaque server sessions, login pre-session CSRF и роли reviewer/operator. Same-origin UI routes opt-in через `serve --ui-config`; существующий operator Bearer API остаётся отдельным. Trusted scope receipts записываются перед анализом из построенного request; UI выдаёт только результаты с доказанной текущей областью, не угадывает права старых jobs.

**Tech Stack:** Python3.12+, stdlib sqlite3/hashlib.scrypt/secrets/getpass, существующий FastAPI. Нет новой зависимости для auth. HTML/CSS/JS для входа и проверки сессии. Текущий linked worktree на codex/impactmap-batch-00, baseline11 diagnostics PASS.

**Spec:** [Approved UI design](../specs/2026-11-16-impactmap-ui-admin-design.md); владелец16.11: «Шрифт будто слишком большой … продолжай a6.2». Реализация inline уже разрешена, новый approval не нужен.

## Global Constraints

- Одна организация/одна установка и общий разрешённый corpus scope двух ролей. Multi-tenant/per-project grants не реализуются.
- Служебный AGENT_SERVICE_STATUS_TOKEN не передаётся браузеру, UI не принимает его как пользовательскую сессию.
- UI API read-only, кроме login/logout; реальные worker/ВМ/ключи/аккаунты не изменяются.
- A6.2 — доступ и проекции. Рабочий result screen, connections metadata и LIVE UI gate — A6.3–A6.5.
- Current job/analysis freshness/publication независимы; incompatible результат не раскрывает payload.
- Deployment HTTPS/cookie Secure; явный insecure режим допускается только для origin с loopback127.0.0.1.

## Review Focus

- Нет CSRF или чужой Origin/Host: login/logout запрещены, включая anonymous login CSRF — Task2.
- Истёкшая/отозванная/подставленная cookie, смена password/role/scope: старый доступ прекращается — Task1/2.
- Исторический результат/новое поколение без trusted scope или другой installation/env/view: никакой metadata/код/счётчики не раскрываются — Task3.
- Пароль/ключи/HTTP receipts/произвольный snapshot: отсутствуют в ответах, ошибках и audit — Task1/2/3.
- Перезапуск, параллельные неверные входы, oversized/malformed JSON и SQLite race: bounded login work, durable rate limit, no body echo — Task1/2.

---

### Task1: Durable auth and local operator CLI

**Files:** create `src/agent_service/ui_auth.py`, `src/agent_service/ui_admin.py`; tests `tests/service/test_ui_auth.py`.
**Interfaces:** `UISettings.load(path)`, `AuthStore(path, clock=...)`; `put_user(username,password,role,scope,create=False)`, `disable_user`, `revoke_user`, `challenge`, `consume_challenge`, `login`, `session`, `logout`. `Actor` carries username, role, scope, csrf, absolute expiry. `UIError(code,status)` contains only stable safe code.

- [x] RED: tests for real scrypt/salt verification; unknown/disabled user; challenge one-use/expiry; opaque token only hashed at rest; absolute8h + idle20min; rotation, restart, role/password revocation; throttle5 attempts/15min and per-peer60/min, concurrent KDF bound2; private file0600 and symlink rejection; audit no password/token.
- [x] Run `python -m unittest tests.service.test_ui_auth -q`, observe missing-module failure.
- [x] Implement fixed scrypt N32768/r8/p3, salt16/dk32, maxmem128MiB; password12..1024 UTF-8 bytes. Session random32 bytes, challenge5min, rolling durable rate buckets, retained max10000 audit rows. Credentials entered only getpass CLI, no password argument/default user.
- [x] GREEN same command. CLI create/set-password/set-role/disable/revoke uses existing service config to approve actual scope, never calls connectors.
- [x] Commit focused auth changes with tests once verified.

### Task2: Same-origin HTTP boundary and compact login/session screens

**Files:** create `src/agent_service/ui_api.py`, `src/agent_service/ui_web/{login.html,session.html,ui.css,login.js,session.js}`; modify `api.py`, `__main__.py`, `pyproject.toml`; tests `test_ui_api.py`.
**Interfaces:** `mount_ui(app,service,settings,store)`. `GET /ui/api/csrf` → pre-session token; POST login requires exact Origin, challenge cookie and X-CSRF-Token; GET me → actor+CSRF; POST logout → revoke and clear cookie. `/ui/login` public shell, `/ui/session` authenticated shell; static asset whitelist. JSON401 on missing/expired session, operator routes403 reviewer; HTML redirect to fixed local login, no arbitrary return URL.

- [x] RED API tests: disabled-by-default404, no-token401 before validation, wrong host421, cross-origin403, secure cookie attributes/rotation, malformed/oversized body400/413 without input echo, logout/revoke/expiry, no Bearer bypass, no CORS and no-store even404/405.
- [x] Run `python -m unittest tests.service.test_ui_api -q`, confirm failing imports/expectations.
- [x] Implement middleware/limits/CSRF and authenticated sample session screen without demo-role selector or fake backend data. Change prototype fonts to ~14px body,26px main headings/compact spacing; touch controls remain usable.
- [x] GREEN API tests + existing diagnostics. Check stylesheet in browser; preserve existing service APIs and keep installed worker unchanged.
- [x] Commit HTTP/CLI integration and screens with verified tests.

### Task3: Scope-bound UI projections

**Files:** create `src/agent_service/ui_scope.py`; modify queue.py/service.py for new `ui_scope_receipts` table and trusted stamp immediately after valid build_request, before analyzer; add queue read-only `ui_listing`/`ui_result`; tests `test_ui_scope.py`.
**Interfaces:** `scope_for_service(service)` returns installation/env/view/repositories/runtime sources + authority digest tied to service DB. `stamp_ui_scope(job,request)` is lease/current-generation checked. `ui_listing(scope,limit)` and `ui_result(scope,rid)` read a consistent transaction; require both current and selected analysis generation receipts matching current scope. Missing/mismatched scope404, not admin-wide fallback. Projection whitelist excludes stored publisher document/config/receipts/model payload; scope-mismatched structured output is denied wholly, not partially redacted.

- [x] RED: legacy/no receipt not visible; cross-install/env/view/direct ID404; old broader scope hidden after new generation and user reapproval; no snapshot/title/credential data leaks; new FAILED job leaves old raw STALE only when both scopes match; incompatible hides raw; read leaves service database unchanged; safe metadata listing bound100.
- [x] Run `python -m unittest tests.service.test_ui_scope -q`, observe missing methods.
- [x] Implement receipt and scoped reads; always label fixed visibility boundary `STAMPED_SCOPE_ONLY`, never advertise hidden resources as «нет влияния». Operator endpoint role-gated; actual operation/connection features deferred to A6.4.
- [x] GREEN auth/API/scope/diagnostics, service integration tests and existing queue/core regression checks. No automatic historical backfill based on current permissions.
- [x] One fresh security/correctness review; fix important findings with failing tests first, then relevant suite once.

### Task4: Browser check, docs and checkpoint

**Files:** create `docs/operations/impactmap-ui-access.md`, `docs/operations/a6-2-2026-11-16/` verification and screenshots; update roadmap/checkpoint and prototype font QA provenance.

- [x] Launch an isolated local service fixture with ephemeral auth users and real session boundary; no production secrets/data. Verify login→me→operator403 for reviewer→logout→no stale protected screen. Capture smaller-font prototype1440/390 and login/session screens. No model/connector writes.
- [x] Run selected backend suite and Python packaging check; record exact counts/environment and all unrun Linux/release/LIVE checks. Verify hashes for changed prototype artifacts; no old QA receipt falsely applied to new CSS.
- [x] Update CHECKPOINT and mirror; local commit, leave checkout intact. New deployment artifact/VM acceptance remains a separate release gate.

## Self-review / decisions

Scope receipts are necessary because pre-A6.2 queue results do not persist trusted access_scope; raw output alone cannot establish historic grants. Legacy API remains operator-only and unchanged. New UI intentionally cannot see historical/early-failed/queued generations with no trusted receipt; A6.3 must explain this limitation, and future ingestion scope extension requires its own evidence. Review Focus covered by Tasks1–3 tests. No automatic production accounts, permissive migration, external publish or deployment is authorised by this plan.

Standards checked16.11: [OWASP password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html), [sessions](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html), [CSRF/login pre-sessions](https://cheatsheetseries.owasp.org/cheatsheets/Cross-Site_Request_Forgery_Prevention_Cheat_Sheet.html). These inform implementation; no certification/compliance claim.

## Execution / verified scope

Implementation source commit f3c38e6. Task3 was implemented before Task2 because scope helpers are a security dependency; interfaces preserved. Auth/HTTP/scope tests observed RED→GREEN, frontend expiry reproduced RED in real short-TTL browser profile and GREEN after fix. Fresh reviewer2 P2 fixed: effective expiry/visibility clearing and403 logout with one CSRF refresh/retry. Real two-tab trace403→200→200→401 saved. Operator CLI uses no connector calls. Smaller fonts checked1440/390. Broad service456/4skips PASS before final UI-only fixes; final focused log and wheel receipts in operation report. Box78 had3 Mac platform errors (Python3.12/Linux guard), recorded rather than hidden; Linux qualification NOT_RUN. Combined source commit used for this coherent scope/auth dependency instead of partially enabled intermediate auth commits. No push/merge/deploy/accounts in a real installation. Next A6.3, not a new scope approval.
