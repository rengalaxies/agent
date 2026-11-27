# ImpactMap: AS-IS и выбор рабочей базы

Дата: 14 ноября 2026 года, Москва. Пачка **00**. Статус: **DONE**.
Основание: `/Users/user/Documents/ChatGPT/ВКР/ImpactMap_пачки_и_передача_контекста_2026-11-14.md`, строка пачки 00 и общие ограничения.

## Решение

Рабочая база следующих пачек — `/Users/user/.codex/worktrees/impactmap-batch-00/agent-bitbucket-read`, ветка `codex/impactmap-batch-00`, исходный commit `ed6369f6ff4854ba4f2f3461eaf8b37a828754d9`. Это отдельный managed worktree, созданный штатным `create_worktree` из `agent-bitbucket-read`; он прикреплён к текущему чату. Разработку продолжать здесь. Не архивировать его, пока он служит рабочей базой.

GitHub `main` прочитан через GitHub connector; затем `git fetch origin main` подтвердил тот же SHA. [Исходный commit](https://github.com/rengalaxies/agent/commit/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9), [ветка GitHub](https://github.com/rengalaxies/agent/tree/main). Сверка относится к моменту проверки, а не ко всем будущим состояниям ветки.

Оба исходных checkout и найденный дополнительный worktree заняты незавершённой работой. Их HEAD, файлы и staged/unstaged изменения оставлены на месте. Они не подходят для продолжения через слепой pull, checkout или перенос всех локальных файлов поверх main. Новая база уже содержит опубликованные изменения Bitbucket/Jira/Confluence и актуальные документы.

## Версии source, runtime и docs

| Слой | Проверенное состояние |
|---|---|
| GitHub main / fetched origin/main | `ed6369f6ff4854ba4f2f3461eaf8b37a828754d9`, merge PR104, 11.11.2026 |
| Выбранный исходный source SHA | `ed6369f6ff4854ba4f2f3461eaf8b37a828754d9` |
| Установленный и загруженный worker | `a02ffa7854dcc38cecc7fe5c5317466059926cd9` |
| Сравнение установленного SHA с main | 83 изменённых файла; все под `docs/`; `src`, `tests`, `tools`, `infra`, `pyproject.toml` без diff |
| Байтовая проверка установленного Python source | Все 50 поставленных `.py` под `app/src` совпадают по SHA256 с файлами новой базы |
| Ядро | profile `http-requests-6`, schema `agent-graph-1`, output `2.2`, digest `76f495463a158f62bcb7644750e073d6e7f53bd736c407f8329627d7841ab49c` |

Digest ядра из локальной команды `python -m agent_graph core_identity` совпал с `loaded.json` процесса. Сверка файлов не проверяет память процесса, зависимости или непоставленные файлы репозитория. Версия runtime остаётся a02ffa7: новый SHA документов не означает установку нового релиза. Переустановка для пачки 00 не требуется.

Доказательства: [версии и diff](evidence/git-source-runtime-docs.json), [полный список отличий](evidence/installed-to-main.diff-names.txt), [сравнение 50 файлов](evidence/runtime-source-comparison.json).

## Локальные состояния и незавершённая работа

| Checkout | HEAD / ветка | Изменения Git | WIP относительно выбранного main |
|---|---|---|---|
| `/Users/user/Documents/ChatGPT/ВКР/agent` | `5ee21dc2582c0ab26d1d44c6dff1f8d7257af5cc`, `m3/dm-p1-ui-install` | 0 tracked, 13 untracked файлов; прежнее ahead 6 было относительно старого tracking ref | 13 файлов отсутствуют на main; исторические deployment-evidence и два промпта |
| `/Users/user/Documents/ChatGPT/ВКР/agent-bitbucket-read` | `9a69a72bd388ca647f87983082f0f79a930c01b5`, `codex/bitbucket-local-worker` | 14 tracked, 83 untracked файла | 88 совпадают с main; 7 отличаются; 2 отсутствуют |
| `/Users/user/.codex/worktrees/jira-comment-summary/agent-bitbucket-read` | `c4053c6d4a959ff4d0e159c3cb1913fae87f25fb`, detached | 8 tracked, 28 untracked файлов | 33 совпадают с main; 3 отсутствуют |

Число коммитов, достижимых только из локального HEAD / только из main: `agent` — 8/133; `agent-bitbucket-read` — 3/29; дополнительный worktree — 0/14. Это различие истории, а не число потерянных функций: изменения могли попасть через другие SHA. Старые origin/main до fetch: `5974c1fa277b9eed861ca4b2c95b8be879c4ea9c` и `c4053c6d4a959ff4d0e159c3cb1913fae87f25fb` соответственно. Fetch обновил tracking ref второго репозитория и его worktrees, HEAD не менял.

Семь отличающихся WIP-файлов второго checkout: `READINESS.md`, `STATUS.md`, `2026-10-28-mvp-delivery-ownership.md` и `src/agent_service/{config.py,confluence.py,connectors/jira.py,service.py}`. Проверка четырёх source diff показывает, что в локальной версии ещё нет уже опубликованного русского Jira summary. Эти файлы не переносить поверх main. Два отсутствующих файла: `bitbucket-worker-2026-11-04/NEXT-ITERATION.md` и `post-guard-live.json` внутри `docs/implementation/autonomous-mvp/`. Их содержание сохранено для отдельного разбора, а не объявлено ненужным.

Три отсутствующих файла дополнительного worktree: два `artifacts/Паспорт проекта *.docx` и `jira-presentation-2026-11-08/ip-change-runtime.json`. Они также сохранены. Полный перечень каждого tracked/untracked пути и его сравнение находится в [local-checkouts.json](evidence/local-checkouts.json).

## Сохранность и восстановление

Локальная резервная копия: `/Users/user/Documents/ChatGPT/ВКР/.private/impactmap-batch00-20261114`. Она находится за пределами Git-деревьев исходников. Копии включают Git bundle всех refs и HEAD, index, binary staged/unstaged patches, архив рабочей копии всех tracked и неигнорируемых untracked файлов, SHA256 manifest и исходный status. Скопированы 1778, 2025 и 1990 путей соответственно. Секреты, окружения и прочее ignored-состояние оставлены на месте и не входят в архивы; это резервная копия Git-видимой работы, а не полный backup компьютера или production.

`git bundle verify` прошёл для всех трёх bundles. Все файловые SHA256 внутри архивов проверены. Дополнительно каждый bundle клонирован в отдельный временный каталог: восстановлены исходный HEAD, архив и index; binary diff staged/unstaged и список untracked совпали с оригиналом. Временные каталоги удалены. Повторная сверка оригиналов подтвердила неизменность HEAD, файлов, mode и binary patches. Не выполнять восстановление поверх действующего checkout: сначала использовать новый временный каталог.

Состав копий и хеши: [backup-summary.json](evidence/backup-summary.json). Свежая проверка оригиналов: [preservation-verification.json](evidence/preservation-verification.json). Пробное восстановление: [scratch-restore-verification.json](evidence/scratch-restore-verification.json). Оригинальные копии содержат историю и локальные материалы: не публиковать архивы целиком.

## Стенд: свежая проверка 14 ноября

Read-only SSH-проверка в **12:51:52 МСК** (09:51:52 UTC), через существующий профиль с pinned host key. `agent-bitbucket`, `agent-service`, Nginx и Docker — active/running, enabled. Worker PID 60331 совпадает с PID в loaded.json. Current symlink указывает на release a02ffa7; Python на стенде 3.12.3, Linux x86_64, 2 CPU, RAM 4 009 868 KiB.

`/healthz` и авторизованный `/status` вернули HTTP 200. Конфигурация: publication `live`, Bitbucket mode `jira_delivery`, refresh mirrors `true`, polling 60 секунд, Jira format `summary_ru`. Модель не настроена, model qualification отсутствует. Policy содержит `bb.orders` и `bb.reporting`.

Status: INGESTED 17; jobs ANALYZED 1 / DONE 19 / SUPERSEDED 2; intents DELIVERED 33 / FAILED 2; notices пуст. Историческая приёмка объясняет FAILED intents негативным PR3 без единственной Jira-связи; текущая пачка не повторяла этот сценарий и не проверяла заново его причину через внешний API.

Внешние Jira/Bitbucket/Confluence API отдельно не перепроверялись и новый change/fix цикл не запускался. Не выполнялись reconcile, публикация комментариев, изменение задач/документов, restart, reboot, установка или восстановление ВМ. Успешный health/status не означает новую сквозную приёмку или проверку качества анализа.

Доказательство: [runtime-readonly.json](evidence/runtime-readonly.json). Сценарий сбора: [runtime_readonly.py](evidence/runtime_readonly.py); токен статуса читается только внутри процесса на ВМ и не выводится. Воспроизводимая команда из корня ВКР:

```sh
ssh -F .private/m3-ssh-20261101/config dm-p1-ui 'sudo -n /usr/bin/python3 -' < /Users/user/.codex/worktrees/impactmap-batch-00/agent-bitbucket-read/docs/product/roadmap-2026-11-14/evidence/runtime_readonly.py
```

## Существующие модули и проверки для переиспользования

| Назначение | Модули | Существующие тесты |
|---|---|---|
| Источники, Git pins, сбор контекста | `src/agent_graph/{sources.py,git_sources.py,engine.py}` | `tests/graph/test_git_sources.py`, `test_graph.py`, `test_discovery_regressions.py` |
| Извлечение Python HTTP/API | `src/agent_graph/discovery.py`, `contracts.py` | `tests/graph/test_transport_regressions.py`, `test_discovery_regressions.py`, `test_coverage_noise.py` |
| Персистентный граф, синхронизация и query | `src/agent_graph/{store.py,graph_store.py,graph_store_sync.py,graph_query.py}` | `tests/graph/test_graph_store.py`, в том числе `RecomputeTests.test_full_and_incremental_builds_match_on_change_rename_and_deletion` |
| Контракт адаптера, Jira, Bitbucket | `src/agent_service/connectors/{base.py,jira.py,bitbucket_read.py,bitbucket_analysis.py,bitbucket_jira.py}` | `tests/service/test_bitbucket_*.py`, `test_delivery.py`, `test_errors.py` |
| Связь анализа с сервисом | **`src/agent_service/core_analyzer.py`**; файла `core.py` нет | `tests/service/test_core.py`, `test_graph_memory.py`, `test_impact_regressions.py` |
| Очередь, публикация, версии и перезапуск | `src/agent_service/{queue.py,publisher.py,service.py,config.py}` | `tests/service/test_queue.py`, `test_races.py`, `test_restart.py`, `test_result_transitions.py` |
| Явная Confluence-ссылка, русский summary | `src/agent_service/confluence.py`, `jira_presentation.py` | `tests/service/test_confluence.py`, `test_jira_presentation.py` |
| Поставка | `tools/agent_service/box/` | `tools/agent_service/box/tests/` |

[path-map.json](evidence/path-map.json) фиксирует наличие основных путей. `tools/benchmark_impactmap.py`, `tests/performance/`, `experiments/impactmap_scale/`, `research/` пока отсутствуют; это предлагаемые места будущей работы. Не создавать параллельные дубли существующих модулей. Исторический `docs/audits/architecture/bench/profile_extract.py` существует, но подменяет import path через локальный `bench/core/src` и `bench_shim`: его старые цифры не являются baseline актуального ядра.

## Профиль и ограничения

Текущий детерминированный профиль — Python HTTP/API: явно поддержанные FastAPI-декораторы, OpenAPI JSON и ограниченная AST-грамматика `requests`, сопоставление адресов сервисов из policy и версии Git. Динамические/неподдержанные вызовы, неоднозначные адреса и неполный доступ должны оставаться gaps/unknowns; отсутствие находок не доказывает совместимость. Не расширять языки в одной серии с увеличением корпуса.

Хранилище текущего сервиса/графа — SQLite. Целевой PostgreSQL сохраняется в плане, текущая миграция не выполнена. Модельный слой выбран в плане как Qwen3-4B Apache 2.0; действующий стенд работает без модели. Наличие старых модельных workflows не является реализацией или квалификацией этого нового выбора.

В `agent_graph.contracts.Limits` defaults: max_files 256, max_file_bytes 65 536, max_corpus_bytes 2 000 000, scan_seconds 15; верхние границы валидации 10 000 / 262 144 / 20 000 000 / 120. Это ограничения конфигурации, не доказанная ёмкость. До прогонов 03–05 нельзя объявлять поддержку 5/50k или 10/100k. CPU, память, SLOC и время стадий в этой пачке не benchmark-измерялись.

## Команды и выполненная проверка базы

Локально использовано существующее venv: `/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python`, Python 3.13.9; pydantic 2.14.2, PyYAML 6.0.3, FastAPI 0.162.0, httpx 0.28.1. Это отличается от установленного Linux/Python 3.12.3 и не заменяет CI/target-проверки закреплённых зависимостей. Пакеты не переустанавливались.

Все следующие команды выполнять из выбранного worktree с `PYTHONPATH=src:.` и `PYTHONDONTWRITEBYTECODE=1`:

```sh
/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python -m unittest tests.graph.test_graph_store tests.graph.test_git_sources -v
/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python -m unittest discover -s tests/service -t . -v
/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python -m agent_graph core_identity
/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python -m agent_graph --help
/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python -m agent_service --help
```

Результат графа: **28 тестов за 26.149 с; OK**. Результат сервиса: **343 тестов за 374.219 с; OK (skipped=4)**. Четыре service-теста `ProcessInterruptionTest` пропущены на macOS с причиной `Linux SIGKILL recovery path`; фактически 339 прошли, 4 skipped. Логи: [graph](evidence/tests-graph.log), [service](evidence/tests-service.log). CLI `core_identity` выполнен; `--help` — доступные read-only команды. Конфигурационные CLI `serve/reconcile/status/doctor/bitbucket-probe` существуют; `reconcile` изменяет очередь/публикации и не выполнялся на ВМ в пачке 00.

Дополнительные существующие команды, **не запускались в 00**: `python -m unittest discover -s tests/graph -t . -v` (весь граф), `python -m unittest discover -s tools/agent_service/box/tests -t . -v` (поставка), `python -m agent_service smoke` (локальный стенд). Не выдавать их за уже пройденные проверки. Новых тестов или изменений поведения для текстового аудита не создавалось.

## Открытые проверки и следующий шаг

Сохраняются незакрытые пункты `docs/implementation/autonomous-mvp/demo-acceptance-2026-11-09/README.md`: репетиция владельца/запись; независимый проект и полезность/время/FP/FN; исходный GitHub App/webhook/HTTPS LIVE gate; reboot, production restore и downgrade именно a02ffa7; реальный отзыв доступа, широкие outage и неоднозначный create; произвольная семантика и runtime compatibility вне показанного профиля. Старые c405-проверки не переносятся на a02ffa7.

По новому плану остаются 01–13: интервью реальных участников, методика и 40 новых кейсов с двумя экспертами, scale-профили, оба новых трекера **Kaiten и Яндекс Трекер**, независимые покупатели и синхронизация материалов. Ни одна из этих пачек не запускалась в рамках 00.

Следующая техническая пачка — **02**, методика оценки: единица TP/FP/FN, coverage/abstention, независимая разметка, контрольные кейсы, baseline поиска, предлагаемые пороги 90%/85%/10% и отрицательный результат. После неё — 03 с измерением стадий на выбранной базе. Альтернативная разрешённая последовательность интеграций: 07 → 08 → 09 → 10. Подготовку 01 и поиск внешних участников начинать календарно сразу, фактические интервью проводит человек.

Продуктовый вывод 00: установлена воспроизводимая техническая точка старта ограниченного авторского demo-контура. Независимое качество, масштаб, спрос, цена и экономия времени из этой сверки не следуют.

## Решения о границах выполнения

- Пачка 00 — аудит и документация. Не применять шаги реализации функций/TDD к текстовым артефактам; проверить доказательства и существующие тесты. Цена ошибочного решения — отсутствие новой функциональности, которая и не входит в 00.
- Создать отдельный managed worktree, поскольку все три найденные базы заняты WIP; полномочие следует из самой пачки 00. Цена — дополнительная локальная рабочая копия.
- Не переносить локальные WIP целиком: main уже содержит опубликованные варианты; сохранить все оригиналы и доказательства. Цена — исторические локальные материалы остаются вне новой ветки до отдельной необходимости.
- Финальная проверка документов выполняется по AC, ссылкам, JSON, хешам и diff; новый code review поведения не требуется, source не менялся. Изменений ВМ и GitHub не делалось.
