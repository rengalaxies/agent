# Common scoped Jira/Kaiten UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement task-by-task.

**Goal:** Одновременный UI Jira/Kaiten с отдельными grants и точным opt-in PR allowlist.
**Architecture:** Сохраняем независимые Service/Store/Auth для каждой области. Явные scoped URL; legacy /ui закреплён за Kaiten. Не объединять grants/raw/DB и не менять worker a02ffa. UI gateway маршрутизирует только UI к заранее заданным областям, не произвольным upstream. Каждый backend сохраняет собственную auth/CSRF/origin проверку. Выбор области явно ведёт к её входу.
**Tech Stack:** Python/FastAPI, существующие JS UI/SQLite/systemd/nginx.

Design approved пользователем22.11: docs/operations/a6-5-jira-2026-11-22/DESIGN-DECISION.md, вариант2. Worktree codex/impactmap-batch-00, база885b6df. Не создавать новый worktree. Новые security choices внутри выбранного объёма фиксировать, не пересогласовывать routine implementation.

- [ ] Task1: BitbucketConfig pull_request_ids optional mapping slug→nonempty unique strict positive integer list; omission сохраняет defaults, unknown slug/empty mappings invalid. Connector fetch rejects чужой RID до API, reconcile не включает чужие PR; backend prepare/publication обязаны проходить тот же fence. RED→GREEN config/intake/backend tests. Файлы config.py/connectors/bitbucket*.py, focused tests. Независим от UI.
- [ ] Task2: Scoped UI paths и fixed registry областей. Ссылки/assets/API/login-return/logout/CSRF/cookies соблюдают область. Legacy Kaiten links preserved. Реализовать через существующие UISettings/mount_ui + gateway только при необходимости, без rewriting произвольных HTML/network destinations. RED→GREEN tests: same RID different stores, wrong-scope token403, anonymous local return, unknown area404, operator403, traversal/encoded prefixes reject, legacy remains Kaiten. Packaging/CLI operational config. Все новые paths явно в trusted config.
- [ ] Task3: Один review каждой части + итоговый bounded review; fix one pass; focused/full Linux/package gates appropriate to source changes. Новые product behavior требуют актуального Linux release,29ed только rollback.
- [ ] Task4: Два scoped live backend на ВМ, fixed registry/public routes, сохраняющийся Kaiten marker и отдельная Jira test installation/PR4 fence. До новых записей проверить auth и цели GET. Jira fixed publication→readback→protected UI, затем restart/replay; existing Jira worker/main/PR4 source не менять. Не считать fixed-only цикл тремя change/fix10. Секреты не экспортировать; owner password VM-only reuse.
- [ ] Task5: browser оба результата/выбор области/вход-возврат; закрытые реальные gates и остаток owner/Яндекс/06 записать честно. CHECKPOINT/report, local commits no push/merge.

Interfaces: Task1 обеспечивает single-resource operational fence Task4; Task2 URL/registry обеспечивает доверенную ссылку из renderer Task4 и cookie separation. До обоих source gates runtime не менять.
