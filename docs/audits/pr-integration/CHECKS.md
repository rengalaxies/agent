# Матрица проверок

Аудит выполнялся на Windows 11 в изолированном clone, Python 3.12.15 с
зависимостями из `infra/agent_graph_demo/requirements.lock` (без Linux-хешей).
Ядро и демо используют `fcntl`, `O_NOFOLLOW` и `dir_fd`, поэтому их unittest
локально не импортируются: прогон `tests/graph_demo` на `main` дал 5 ошибок
импорта `No module named 'fcntl'`. Всё, что требует Linux, Docker или Chromium,
проверяется в GitHub Actions на ветках аудита, ссылки на прогоны ниже.

## Локально, воспроизводимо

| Проверка | Объект | Результат | Как повторить |
|---|---|---|---|
| F1 воспроизводится на ядре main | `a9385c5` | FAIL ожидаемо: `Query`/константа → `deltas=[]` | `python docs/audits/pr-integration/repro_page_default.py .` на `ca6b9cf` |
| F1 исправлен | `5d7ee0f` | PASS: `PAGE_DEFAULT_UNRESOLVED`/`PAGE_DEFAULT_CHANGED` | тот же скрипт на ветке ядра |
| Ruff F401/F811/F841 | `src/agent_graph`, `tests/graph`, `tests/graph_demo` | PASS | `ruff check ... --select F401,F811,F841` |
| `py_compile` изменённых модулей ядра | `5d7ee0f` | PASS | |
| `node --check app.js` | `3e473f8` | PASS | |
| core.lock.json = SHA-256 blob'ов ядра | `84cca17` | PASS, изменились только `__init__.py`, `discovery.py`, `engine.py` | хеши из `git show 5d7ee0f:src/agent_graph/<f>` |
| actionlint без shellcheck | все workflows `ca6b9cf` | PASS | `actionlint -shellcheck= -pyflakes=` |
| actionlint с shellcheck | `cloudru-foundation-models.yml` | FAIL на main (SC2129), PASS на `205bbd7` | |
| Fixtures PR #31 = отчёт PR #31 | 16 файлов, `5b5b955` | 16/16 | sha256 `git show 5b5b955:<prefix>/<path>` |
| #35: `analyze_batch1.py` воспроизводит `analysis.json` | `6d0902a` | PASS (после нормализации CRLF) | `python -I analyze_batch1.py report.json manifest.json final-ledger.json pricing.json --output x.json` |
| #35: `files-sha256.json` | `6d0902a`, `f8cb0e1` | 13/13 | |
| #35: корпус и ядро в manifest = Git `a9385c5` | 20 файлов | 20/20 | |
| #35: цифры | 23 запроса, usage 29593/6674, резерв 76630396 micro | совпадают | |
| #38: `files-sha256.txt`, `SHA256SUMS` | `1c8ec4f`, `71a0626` | 30/30, `image-audit.json` OK | `sha256sum -c` |
| #38: 36 файлов образа = blob'ы `ca6b9cf` | `image-audit.json` | 36/36 | |
| #38: ресурсы из 1340 samples | `analyze_resources.py` | вывод побайтно равен `resources.json` | |
| #38: receipts | 20 + recheck E | A/D/E 250, B Reporting 100 FAIL (ожидаемо), Export 250 во всех E, health control в каждом | |
| Совместное слияние веток | 5 веток на `ca6b9cf` | без конфликтов | ветка `audit/integration-check` |
| #29, #31, #35, #38 против main | `git merge-tree` | без конфликтов | |

## В CI (Linux, Docker, Chromium)

| Проверка | Голова | Прогон | Результат |
|---|---|---|---|
| Регрессии ядра, включая оба `test_r5_*` (в логе `... ok`) | #41 `84cca17` | [Graph evidence references](https://github.com/rengalaxies/agent/actions/runs/39816552153) | success |
| Core research regression | #41 `84cca17` | [39816552131](https://github.com/rengalaxies/agent/actions/runs/39816552131) | success |
| Демо: API, очередь, восстановление, CLI, Docker + Chromium A→B→D→E, пять сессий, новое ядро | #41 `84cca17` | [HTTP graph demo](https://github.com/rengalaxies/agent/actions/runs/39816552183) | success |
| P1 deployment regression | #41 `84cca17` | [39816552109](https://github.com/rengalaxies/agent/actions/runs/39816552109) | success |
| Приёмка с уточнением на B, до исправления F9 | #40 `fddb1c2` | [HTTP graph demo](https://github.com/rengalaxies/agent/actions/runs/39816507144) | **failure**: `TimeoutError` в `browser_acceptance.py:146`, E не завершился (F9) |
| Та же приёмка и `test_correction_on_b_does_not_fail_later_rescan_and_analysis` | #40 `d407ade` | [HTTP graph demo](https://github.com/rengalaxies/agent/actions/runs/39818224651), [core](https://github.com/rengalaxies/agent/actions/runs/39818224669) | success |
| Отчёт пачки 1 с поправкой формулировок | #35 `f8cb0e1` | [offline](https://github.com/rengalaxies/agent/actions/runs/39816013086), [core](https://github.com/rengalaxies/agent/actions/runs/39816013099) | success |
| Lint-фикс | #39 `205bbd7` | [P1 regression](https://github.com/rengalaxies/agent/actions/runs/39816456541) | success; actionlint запускается только на push в main |
| Сочетание #35+#39+#40+#41+аудит: новое ядро вместе с исправленным worker и UI | #42 draft `80cee68` (закрыт после прогона) | [demo](https://github.com/rengalaxies/agent/actions/runs/39819246777), [graph](https://github.com/rengalaxies/agent/actions/runs/39819246776), [core](https://github.com/rengalaxies/agent/actions/runs/39819246927), [P1](https://github.com/rengalaxies/agent/actions/runs/39819246783) | success |

## Что не проверялось

- Установленная ВМ: аудит к ней не подключался и её не обновлял.
- Реальная модель: вызовов не было.
- Клиентский репозиторий: нет.
