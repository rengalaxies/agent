# Матрица проверок

Аудит выполнялся на Windows 11 в изолированном clone, Python 3.12.15 с
зависимостями из `infra/agent_graph_demo/requirements.lock` (без Linux-хешей).
Ядро и демо используют `fcntl`, `O_NOFOLLOW` и `dir_fd`, поэтому их unittest
локально не импортируются: прогон `tests/graph_demo` на `main` дал 5 ошибок
импорта `No module named 'fcntl'`. Всё, что требует Linux, Docker или Chromium,
проверяется в GitHub Actions на ветках аудита. Строки со статусом "CI" ниже
заполняются ссылкой на прогон.

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

| Проверка | Workflow | Ветка | Результат |
|---|---|---|---|
| 116+ регрессий ядра, включая `test_r5_*` | Graph evidence references / Core research regression | `fix/graph-unresolved-page-default` | CI |
| Демо: API, очередь, восстановление, CLI против нового ядра | HTTP graph demo | `fix/graph-unresolved-page-default` | CI |
| Docker + Chromium A→B→D→E, пять сессий | HTTP graph demo | `fix/graph-unresolved-page-default` | CI |
| Демо UI, browser acceptance с уточнением на B | HTTP graph demo | `fix/demo-evidence-labels` | CI |
| Workflow lint | Workflow security and syntax check (после merge в main) | `main` | CI |

## Что не проверялось

- Установленная ВМ: аудит к ней не подключался и её не обновлял.
- Реальная модель: вызовов не было.
- Клиентский репозиторий: нет.
