# Пачка 2А: воспроизводимое ядро и исполняемая конституция

Задача [#50](https://github.com/rengalaxies/agent/issues/50), первая часть.
Ветка `claude/mvp-2a-core-205322`, сравнение с main:
https://github.com/rengalaxies/agent/compare/main...claude/mvp-2a-core-205322

2А принимается без модели; #50 не закрывается до 2Б. Все проверки ниже
выполнены офлайн на Windows 11, Python 3.14.5, Git 2.55. Linux-прогон, Linux-время
и память не измерены: на машине нет Linux, Docker и WSL. PR из этой сессии
открыть нельзя (нет `gh`, браузер не вошёл в GitHub), поэтому Linux CI по PR
ещё не запускался.

## Коммиты

Порядок интеграции — порядок в ветке, всё поверх `9d7480d`.

| Коммит | Что |
|---|---|
| `d8dd64a` | контракты `agent-graph-output 2.0` и JSON Schema |
| `71ef0b5` | STATUS и DECISIONS, сверка пачки 1 |
| `61f862f` | ядро запускается на Windows (`portable.py`) |
| `9d5797a` | Git-стенд Orders/Reporting |
| `f75149b` | анализ закреплённых Git-коммитов |
| `4de6e2a` | `UNCLASSIFIED_OPERATION_CHANGE` |
| `01ff849` | шум и покрытие по файлам |
| `a8394d3` | конституция, `actions-v3`, послойная диагностика, исполнитель |
| `2b09ad0` | `evidence_batch` и `core_identity` |
| `2e6db86` | демо запускается на Windows |
| `1509163` | демо на поставляемом ядре, один процесс проверки цитат на задание |
| `54e8ceb` | сборка `AnalysisResult` из выдачи ядра |
| `741daea` | тест hooks: исполняемый hook |
| `47c22e4` | тест схемы сравнивает структуру, а не заголовки |
| `2a982dd` | этот отчёт, STATUS, DECISIONS D3–D8 |
| `c850731` | CI: PyYAML, демо без внешнего ядра, тесты 2Б в core-tests |
| `8fbe2e3` | CI: Linux-замер задания с многими цитатами |
| `b8ee515` | контекст остаётся текущим, если репозиторий был недоступен с момента prepare (баг от 2Б) |
| `d155048` | тест подмены объекта читаем на Linux |
| `336b92f`, `4f0f9f1`, `5bc270e` | CI: упавшие тесты и код отказа приёмки как annotations |
| `bcb502a` | CI: итог замера как notice |
| `8ac841d` | образ демо содержит ядро и конституцию |
| `4d10897` | браузерная приёмка ждёт полное покрытие сценария A |

## Контракты

`src/agent_graph/output_contracts.py`, схема `schemas/agent-graph-output-2.json`.
Решения и причины — D1 в [DECISIONS.md](DECISIONS.md).

- `AnalysisRequest`: installation/environment, `request_id`, `trigger_kind`
  (`jira|pr|replay`), `source_event {event_id, resource_version}`, Jira или PR,
  `repository_revisions` (закреплённая карта всех читаемых репозиториев),
  `graph_version`, `constitution_version`, `model_configuration_id`,
  `deadline`, `access_scope`. Голова PR обязана совпадать с картой, карта —
  входить в область доступа.
- `AnalysisResult`: версии схемы, профиля, кода и конституции; request, event,
  resource version, correlation ID; снимки с ролями base/head/consumer;
  `status` из `USEFUL|PARTIAL|ABSTAINED|FAILED|SUPERSEDED` и `reason_code`,
  допустимый только для своего статуса; summary, затронутые сервисы с
  владельцем, пути влияния, проверки для команд, утверждения `fact|hypothesis`
  с основаниями, областью применимости, неопределённостью и unknowns; delta,
  findings, gaps, свежесть по источникам, модель, затраты (`null` = неизвестно),
  timings.
- Evidence: `code | runtime | model_hypothesis | correction | external_report`;
  provenance, достаточность и свежесть — отдельные поля. Код несёт
  repository, commit, blob, SHA-256 содержимого, путь и строки.
- `GraphRelationship`: стабильные сущности service/operation/callsite/team с
  installation и environment, origins, evidence refs, статус, свежесть,
  происхождение изменения и видимость.
- Неизвестная major, более новая minor и любой неизвестный код дают
  `ContractError`; `display_verdict` показывает такой документ как
  `INCOMPATIBLE`, не зелёным.

Примеры документов стенда: `tests/graph/fixtures/output-2/pr-7-{request,result}.json`
(PR `main → pr-7`) и `ord-12-{request,result}.json` (Jira до diff). Тест
проверяет, что они проходят контракт.

## Что сделано по разделу 7

| Пункт | Реализация | Тесты |
|---|---|---|
| Контракты выдачи | `output_contracts.py`, `results.py` (`change_result`, `preliminary_result`, `failed_result`), `check_core_codes` для выдачи ядра в приложении | `test_output_contracts.py`, `test_results.py`, `tests/graph_demo/test_core_integration.py` |
| Git-снимки | `git_sources.py`, `Repository.snapshot: git`, `allowed_refs`, `prepare_context/analyze_change(revisions=...)`, CLI `--revision repo=sha` | `test_git_sources.py` |
| Безопасное чтение Git | только `rev-parse`, `for-each-ref --contains`, один `cat-file --batch-command`; без global/system config, lazy fetch, fsmonitor, hooks; перехеширование commit/tree/blob | `test_git_sources.py::SafeReadTests` |
| Неизвестное изменение | `tracked_basis` операции, delta `UNCLASSIFIED_OPERATION_CHANGE`, finding `UNCLASSIFIED_CHANGE_RECHECK` | `test_git_sources.py::ChangeTests` |
| Шум и покрытие | декораторы маршрутов и `dict.get` больше не пробелы; `file_coverage` по каждому файлу | `test_coverage_noise.py`, `tests/graph_demo/test_graph_cli.py` |
| `invalid_model_action` по слоям | `actions.py`: transport, json, schema, combination, tool, evidence | `test_action_diagnostics.py::LayerTests` |
| Совпадение шаблона, схемы и исполнителя | схема, системный шаблон и исполнитель строятся из одних моделей | `test_action_diagnostics.py::AgreementTests` |
| Безопасная диагностика | allowlist полей, SHA-256 и длина ответа вместо текста, JSON-строки в логгер `agent_graph.diagnostics` | `test_secret_in_replies_never_reaches_report_logs_or_store` |
| Конституция | `constitutions/agent-service-v1.yaml`, `constitution.py`, `executor.py` | `AgreementTests::test_constitution_cannot_drop_rules_or_add_tools`, `ExecutorTests` |
| Полезные инструменты | `list_sources`, литеральный `search`, `list_symbols`, `read_source` с receipt, `graph_query`, `propose_dependency`, `propose_hypothesis`, `finish` | `ExecutorTests` |
| Вне грамматики | `propose_hypothesis`: подлинность ссылок проверяется, достаточность `NOT_ASSESSED`, повышение только вручную вне модели | `test_hypothesis_outside_the_grammar_stays_unverified` |
| Без fan-out по цитатам | `Graph.evidence_batch`, CLI `evidence_batch`, worker демо — один процесс на пакет | `test_evidence_batch.py`, `test_core_processes_per_job_do_not_grow_with_citations` |
| Новое ядро в приложении | `GraphCLI` запускает поставляемый пакет и сверяет `core_identity` подпроцесса с ядром приложения | `tests/graph_demo/test_core_integration.py::ShippedCoreTests` |

Выбор по fan-out: один ограниченный процесс CLI на пакет цитат, а не вызов в
том же процессе. Причина: процесс по-прежнему убивается по deadline и отмене
независимо от того, кооперирует ли код ядра. In-process вызов этого не даёт и
процессной изоляцией не считается.

Разбор 22.10: точные поля отклонённых действий не сохранены, так что
причину нельзя доказать задним числом. В старом протоколе одно плоское
действие требовало `null` в неиспользуемых полях, а схема разрешала
`human_correction`, который исполнитель запрещает модели. Обе ловушки в
`actions-v3` невозможны по построению. Это гипотеза о причине провала, а не
воспроизведение.

## Приёмка раздела 7

| Требование | Проверено офлайн | Тест |
|---|---|---|
| Одинаковые commit map и профиль дают одинаковые канонические факты; run_id, время и latency не сравниваются | да | `test_same_commit_map_gives_same_facts_in_separate_stands_and_stores`, `test_same_commit_map_gives_the_same_result_facts` |
| Правка рабочего дерева не влияет на закреплённые SHA; отсутствующий или чужой commit не подменяется веткой | да | `test_worktree_edit_does_not_change_a_pinned_snapshot`, `test_missing_or_foreign_commit_is_a_gap_not_the_current_branch`, `test_commit_must_be_reachable_from_an_allowed_ref`, `test_unavailable_pr_commit_fails_instead_of_using_another_commit` |
| Изменение операции вне трёх известных delta даёт неизвестный тип | да | `test_tracked_operation_change_outside_known_deltas_is_unclassified`, `test_unclassified_change_is_partial_not_green` |
| OpenAPI `$ref` и нечитаемый provider не дают ложного удаления; доказанное удаление верно | да, регрессии #45 сохранены | `test_discovery_regressions.py::test_r6_*`, `test_readme_edit_has_no_delta_and_removal_is_reported` |
| Удаление операции подписано как удаление (#46) | да: метка `OPERATION_REMOVED` сохранена, неизвестный код больше не падает в «повторную проверку» | `test_every_contract_finding_code_has_a_ui_label_and_unknown_is_not_recheck`; браузерная приёмка не запускалась (нет Playwright/Docker) |
| Придуманный source_id/evidence_ref, изменённая цитата, receipt другой сессии отвергаются | да | `test_invented_or_foreign_receipts_are_evidence_rejections`; изменённая цитата — существующие `test_evidence_refs.py` (в `actions-v3` модель цитаты не пишет вообще) |
| Цитата одноимённого API другого сервиса не подтверждает связь | да | `test_quote_from_same_route_of_another_service_does_not_support_the_claim`, `test_pr_default_change_finds_reporting_and_not_lookalikes` |
| Невалидный action даёт полезную безопасную диагностику; контрольный секрет не попадает в отчёт и логи | да | `LayerTests`, `test_secret_in_replies_never_reaches_report_logs_or_store`, `test_rejected_action_gets_safe_feedback_and_the_run_can_continue` |
| Timeout, cancel и step limit останавливают работу и закрывают резервирование; нет фонового продолжения | да, на скриптовой модели и локальном HTTP | `StopTests`, `HttpTransportTests` |
| Неизвестные код и версия схемы не становятся зелёными в UI/API | да | `test_unknown_major_is_incompatible_and_not_green`, `test_unknown_core_finding_code_fails_the_job_instead_of_showing_a_result`, `test_every_contract_finding_code_has_a_ui_label_and_unknown_is_not_recheck` |
| Число процессов не растёт линейно с цитатами | да | `test_core_processes_per_job_do_not_grow_with_citations` |
| Linux-время и память на корпусе с многими цитатами | **не проверено**: нет Linux | — |

## Замеры

Только Windows 11, информационно. Linux-цифры не получены, экстраполяция не
делается. Задание демо `analyze_change` A→E на сценарии демо, 12 уникальных
цитат:

| Способ | Процессы ядра на задание | Время |
|---|---|---|
| сейчас: один `evidence_batch` | 3 | 1,4 с на всё задание |
| прежний способ, отдельно | 2 + 12 | 12 процессов `evidence` заняли 4,3 с (0,36 с на процесс) |

Скрипт замера не входит в репозиторий; повторить можно тестом
`test_core_processes_per_job_do_not_grow_with_citations` и таймером вокруг
`run_job`.

## Прогоны

Команды раздела 14, venv внутри worktree, Windows. Перед прогоном фикстуры
выписаны с LF (см. D2 в DECISIONS).

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[api,test-api,distributed,postgres]'
PYTHONPATH=".;src" .venv/Scripts/python -m unittest discover -s tests/graph -t .
PYTHONPATH="src;." .venv/Scripts/python -m unittest discover -s tests/graph_demo -t .
PYTHONPATH=".;src;tests;tools" .venv/Scripts/python -m unittest discover -s tests
python examples/orders_reporting/stand.py /tmp/orders-stand
```

### Итоговые числа (Windows, ветка после `741daea`)

| Набор | Прогнано | Не прошло | Причина непрошедших |
|---|---:|---:|---|
| `tests/graph` | 189 | 2 | среда: создание symlink требует привилегии (`WinError 1314`); Windows держит открытый SQLite при очистке temp (`WinError 32`) |
| `tests/graph_demo` | 38 | 7 | среда: 6 тестов `test_runner` вызывают `os.geteuid` из `tools/agent_graph_demo`; 1 тест запускает shebang-скрипт вместо `python` |
| `tests` целиком | 550 | 124 | см. сравнение с базой ниже |
| `ruff --select F401,F811,F841` по путям core-tests | — | 0 | — |
| `node --check src/agent_graph_demo/web/app.js` | — | 0 | — |

Сравнение с базой `9d7480d` тем же venv на той же машине: на базе прогнано
344 теста и 129 не прошли, потому что модули ядра, демо и других пакетов не
импортировались на Windows. На ветке прогнано 550, не прошли 124. Ни один
тест, который на базе запускался и проходил, на ветке не падает. Восемь тестов
не проходят только на ветке: на базе их модули не импортировались вовсе, а
теперь они запускаются и упираются в ту же среду (symlink, `os.geteuid`,
shebang). Остальные непрошедшие — `tests/product`, `test_distributed_policy`,
`test_expert_packet` и модули, импорт которых на Windows падает и на базе;
пачка 2А их не трогала.

Linux-прогон этих наборов не выполнен.

## Ограничения

- Профиль `http-requests-4` прежний: Python requests → FastAPI/OpenAPI. httpx,
  Session, обёртки видны как пробелы, но не извлекаются.
- Неклассифицированное изменение отслеживает только объявление операции.
  Вспомогательные функции, которые она вызывает, не отслеживаются.
- Свежесть закреплённого снимка — это проверка, что коммит по-прежнему
  достижим и даёт то же дерево. Является ли он текущей головой PR, решает
  сервис (`SUPERSEDED`, пачка 4).
- `allowed_refs` по умолчанию: `refs/heads/*`, `refs/tags/*`, `refs/pull/*/head`.
  Получение зеркал и fetch не входят в 2А.
- Git ≥ 2.36 обязателен; частичный clone требует Git ≥ 2.44
  (`GIT_NO_LAZY_FETCH`), иначе отказ.
- Windows-ветки `portable.py`, `locks.py` и транспорта демо уже POSIX-пути
  и не являются границей безопасности.
- Конституция читается из `constitutions/` рядом с исходниками; путь для
  колеса и образа решается в 5А.
- `USEFUL` у результата — предварительная классификация сервиса, а не
  подтверждённая польза.
- Контракт 2.0 полностью типизирует запрос и результат анализа. Внутренние
  документы ядра (context, dependencies, evidence, investigation) остаются в
  формате `agent-graph-1` / `graph-investigation-2`: у них проверяются коды
  (`check_core_codes`), а целиком они попадают наружу только через
  `AnalysisResult`. Отдельные pydantic-модели для них не написаны.
- Модельный цикл `actions-v3` проверен только скриптовой моделью и локальным
  HTTP-стабом. Настоящая модель — 2Б.

## CI после волны 2

Волна 2 передала этой сессии `core-tests.yml`, `graph-evidence-refs.yml` и
`agent-graph-demo.yml`. Изменения: `c850731`, `8fbe2e3`. actionlint 1.7.7 без
замечаний; на раннере не запускались, потому что PR ещё нет.

| Было | Стало |
|---|---|
| `graph-evidence-refs.yml` ставит только pydantic; `agent_graph.constitution` не импортируется | ставит PyYAML; срабатывает и на изменения конституции и стенда |
| `agent-graph-demo.yml` выписывает ядро `18e8b71` рядом с PR и гоняет регрессию ядра на нём | регрессия ядра на checkout PR; workflow срабатывает и на `src/agent_graph/**`; `DEMO_CORE_ROOT` указывает на сам checkout, пока `accept.py` и compose требуют корень ядра |
| тесты runner 2Б (`tools/autonomous_mvp/tests`) в PR CI не запускаются | `core-tests.yml` запускает их, если каталог есть на ветке |
| Linux-время и память задания с многими цитатами не измерены | job `citation-measurement`: `tests/graph/bench_citations.py` на 200 файлах-потребителях, оба режима (один `evidence_batch` и процесс на цитату), время шагов и пиковая RSS каждого процесса через `os.wait4`, artifact `citation-measurement-<sha>` |

Известное падение до правки 5А: Docker-шаг `agent-graph-demo.yml`. Образ
`infra/agent_graph_demo/Dockerfile` не содержит `src/agent_graph`, а приложение
теперь импортирует ядро, поэтому `check_packaging.py` внутри образа упадёт с
`ModuleNotFoundError`. Dockerfile, compose, `core.lock.json` и
`tools/agent_graph_demo` принадлежат mvp-5a-box; точная правка записана для
неё в общей папке заметок сессий (`mvp-2a-core-to-mvp-5a-box.md`). Там же
`os.geteuid` в `tools/agent_graph_demo`: на Windows из-за него падают 6 тестов
`tests/graph_demo/test_runner.py`, на Linux они не затронуты.

## Linux CI на PR #56

PR [#56](https://github.com/rengalaxies/agent/pull/56) открыт владельцем 25.10.2026.
Первый прогон (голова `4185450`) упал в трёх заданиях, все на прогоне
`tests/graph`. Логи без входа недоступны, поэтому сначала добавлен вывод
упавших тестов в публичные annotations (`tests/graph/ci_unittest.py`, `336b92f`).

| Прогон | Core research regression | Graph evidence references | HTTP graph demo | P1 |
|---|---|---|---|---|
| `4185450` | упал | упал | упал на регрессии ядра | прошёл |
| `336b92f`…`5bc270e` | прошёл | прошёл | регрессия ядра прошла; Docker-приёмка упала | прошёл |
| `4d10897` | прошёл ([40176067532](https://github.com/rengalaxies/agent/actions/runs/40176067532)) | прошёл ([40176067529](https://github.com/rengalaxies/agent/actions/runs/40176067529)) | прошёл, включая Docker и браузерную приёмку ([40176067595](https://github.com/rengalaxies/agent/actions/runs/40176067595)) | прошёл ([40176067534](https://github.com/rengalaxies/agent/actions/runs/40176067534)) |

Причина первых падений — один тест во всех трёх заданиях (по логам
координатора: core 654 теста, failures=1; offline 191 тест, failures=1):
`test_git_sources.SafeReadTests.test_object_whose_content_does_not_match_its_id_is_rejected`,
`AssertionError: GraphError not raised`. Тест портил свою подмену:
`os.chmod(path, stat.S_IWRITE)` на Windows снимает только флаг «только чтение»,
а на Linux ставит режим `0o200`. Git не мог открыть файл объекта, сообщал его
как отсутствующий, и ядро записывало пробел `object_unavailable` вместо отказа.
Проверка хеша в `git_sources` при этом не обходилась: она просто не
вызывалась для объекта, который git не отдал. С режимом `0o644` подмена
читается, и тест получает `object_hash_mismatch` (`d155048`, задание offline
зелёное с `336b92f`). Остальные падения, которые на Windows списаны на среду
(symlink, SQLite в temp, `os.geteuid`, shebang), на Linux не воспроизвелись.
Числа «2 failures и 28 errors» в сообщениях — это Windows-прогон пачки 3 с
CRLF-выпиской, не 2А.

Демо-приёмка («Real Docker and browser»):

1. `5bc270e`: `{"status": "FAIL", "code": "docker_operation_failed"}`. Образ
   `infra/agent_graph_demo/Dockerfile` не содержал `src/agent_graph`, а
   приложение демо с 2А импортирует ядро; `check_packaging.py` внутри образа
   падал на импорте. Ленивый импорт не применён намеренно: приёмка позеленела
   бы, а веб-приложение в поставляемом образе не запустилось бы. По
   разрешению координатора `8ac841d` кладёт в образ `src/agent_graph` и
   `constitutions/agent-service-v1.yaml` и допускает их в `.dockerignore`
   (без этого COPY не находит файлы). `core.lock.json` и монтирование `/core`
   остаются до 5А.
2. `8ac841d`: Docker-шаг прошёл, приёмка дала `acceptance_failed`. Браузерная
   проверка `tests/graph_demo/browser_acceptance.py` ждала текст покрытия
   «Неполные данные»; он появлялся только из-за шумового пробела на
   декораторах маршрутов. Сценарий A теперь полон в рамках профиля, проверка
   ждёт «Обследован разрешённый корпус» и оговорку о недоказанной семантике
   (`4d10897`).

Linux-замер задания с многими цитатами (прогон
[40174700283](https://github.com/rengalaxies/agent/actions/runs/40174700283),
job `citation-measurement`, коммит `bcb502a`, публичная annotation): Linux 6.17 (Azure), Python 3.12.15, 4 CPU; 200 файлов-
потребителей, 402 уникальные цитаты.

| Режим | Процессы ядра | Время | Пиковая RSS процесса |
|---|---:|---:|---:|
| один `evidence_batch` (prepare, analyze, dependencies, batch) | 4 | 0,88 с | 37–39 МиБ |
| процесс на цитату (3 + 402) | 405 | 54,5 с | до 37 МиБ на процесс |

Шаги пакетного режима: prepare_context 0,36 с, analyze_change 0,24 с,
dependencies 0,14 с, evidence_batch 0,14 с. Это один прогон на одном раннере,
без повторов; разброс не измерен.

## Тексты PR для владельца

Из сессий PR не открыть: нет `gh`, браузер не вошёл в GitHub. Стек на
24.10.2026, поздний вечер:

| PR | Ветка | База | Сливать |
|---|---|---|---|
| 2А | `claude/mvp-2a-core-205322` | `main` | первым |
| 3 | `claude/mvp-3-runtime-2a` | `claude/mvp-2a-core-205322` | после 2А |
| 4 | `claude/mvp-4-service-2a` | `claude/mvp-3-runtime-2a` | после 3, когда ветка 4 вольёт ветку 3 |
| 2Б | `claude/mvp-2b-prep-9d9655` | `claude/mvp-2a-core-205322` | после 2А; после слияния 3 пересобрать manifest 2Б |

После слияния нижнего PR GitHub перенацелит верхний на новую базу
автоматически, если ветка базы удалена, или его нужно перенацелить вручную.

### PR 2А

https://github.com/rengalaxies/agent/compare/main...claude/mvp-2a-core-205322

Заголовок: `feat(graph): batch 2A pinned Git core, output contracts and executable constitution`

```markdown
Часть [#50](https://github.com/rengalaxies/agent/issues/50): пачка 2А. #50 не закрывает: квалификация модели — пачка 2Б.

Нижний PR стека: 3 и 2Б идут против этой ветки, 4 — против 3.

## Что меняется

- Контракты `agent-graph-output 2.0` (`src/agent_graph/output_contracts.py`, `schemas/agent-graph-output-2.json`): `AnalysisRequest`, `AnalysisResult`, Evidence, GraphRelationship, статусы `USEFUL|PARTIAL|ABSTAINED|FAILED|SUPERSEDED`, причины по статусам. Неизвестная major, более новая minor и неизвестный код дают несовместимость и никогда не показываются зелёным.
- Анализ закреплённых Git-коммитов (`git_sources.py`): коммит должен быть достижим из разрешённых ref этого репозитория, каждый объект перехешируется, недоступный или чужой коммит — пробел, а не текущая ветка. Hooks, фильтры и fsmonitor репозитория не исполняются.
- Воспроизводимый стенд Orders/Reporting (`examples/orders_reporting/`) с одинаковыми SHA на любой машине и отрицательными вариантами.
- `UNCLASSIFIED_OPERATION_CHANGE` для изменения операции вне известных классификаторов; шум (декораторы маршрутов, `dict.get`) больше не пробел; статус покрытия у каждого файла.
- Конституция `constitutions/agent-service-v1.yaml`, протокол `actions-v3`, диагностика `invalid_model_action` по слоям без текста ответа модели, ограниченные инструменты, гипотезы вне грамматики без автоматического повышения.
- Демо исполняет поставляемое ядро и сверяет `core_identity`; цитаты проверяются одним процессом на задание вместо процесса на цитату.
- `results.py` собирает валидный `AnalysisResult` из выдачи ядра для PR и для Jira до diff.
- CI: PyYAML в `graph-evidence-refs.yml`, демо без внешнего ядра `18e8b71`, тесты runner 2Б в `core-tests.yml`, Linux-замер задания с многими цитатами (artifact `citation-measurement-<sha>`).

## Проверки

Офлайн на Windows: `tests/graph` 191 (2 падения среды), `tests/graph_demo` 38 (7 падений среды), полный `tests` 550 без новых падений против `9d7480d`. Подробно и с разделением «реализовано / проверено офлайн / не проверено»: `docs/implementation/autonomous-mvp/batch-2a.md`, сводка всех пачек: `STATUS.md`.

Не проверено: Linux CI (первый прогон — этот PR), настоящая модель, браузерная приёмка демо. Docker-шаг `agent-graph-demo.yml` упадёт, пока пачка 5А не положит `src/agent_graph` в образ демо.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### PR 3

https://github.com/rengalaxies/agent/compare/claude/mvp-2a-core-205322...claude/mvp-3-runtime-2a

Заголовок: `feat(graph): batch 3 persistent code and runtime graph`

```markdown
Часть [#51](https://github.com/rengalaxies/agent/issues/51). Стек: база — ветка 2А, сливать после PR 2А. PR 4 идёт против этой ветки.

## Что меняется

- Постоянный граф (`src/agent_graph/graph_store.py`, store schema 2): сущности, связи и основания по `(installation, environment)`, стабильный ID места вызова без номера строки, история и tombstone.
- Предложения и исправления оцениваются по процитированным файлам, а не по basis всего корпуса: несвязанная правка их не обесценивает, изменение процитированного файла делает статус явным.
- Фильтрация доступа (cache, счётчики, история, старые ID), свежесть по типам источников, конфликт кода и наблюдений, ownership из installation mapping, обновление по событию и периодическая сверка, ограниченный graph query, просмотр для человека (`graph_view.py`).
- Миграция store v1 → v2 с резервной копией; старые контексты и исправления читаются.
- Адаптер `access-log-jsonl-1` и стенд с настоящими HTTP-вызовами.
- Контракт `agent-graph-output` 2.1: только добавления — runtime-коды и `Claim.subject`.
- Инструменты модели `graph_find`, `graph_neighbors`, `graph_impact`, `graph_relationship`, `graph_owner` в конституции `agent-service-v1` и исполнителе; результаты ограничены scope и правами политики.

## Проверки

Офлайн на Windows: тесты `test_graph_store`, `test_graph_query`, `test_graph_view`, `test_runtime_observations`, `test_output_contracts` OK; полный `tests/graph` без новых падений против базы. Приёмка раздела 9 по тестам — в `docs/implementation/autonomous-mvp/batch-3.md`.

Не проверено: Linux (первый прогон — этот PR), подключение к runtime-источнику клиента (нет доступа). Предложение устаревает и при смене процитированного файла, и при смене карты адресов или требований процитированных репозиториев.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### PR 4

https://github.com/rengalaxies/agent/compare/claude/mvp-3-runtime-2a...claude/mvp-4-service-2a

Заголовок: `feat(service): batch 4 Jira and PR service on the 2A core`

```markdown
Часть [#52](https://github.com/rengalaxies/agent/issues/52). Стек: база — ветка 3, сливать после PR 3.

## Что меняется

- `src/agent_service/`: `EventEnvelope`, `PublicationIntent`, SQLite-очередь одной установки с дедупликацией, lease, ограниченными повторами и восстановлением после рестарта.
- Коннекторы GitHub и Jira Cloud: события, получение ресурса, один обновляемый комментарий приложения на ресурс, поиск уже созданного комментария перед повторным create, сверка пропущенных событий.
- Анализ ядром 2А (`CoreAnalyzer`): PR — `analyze_change` на закреплённых base/head и `change_result`; Jira — `preliminary_result` до diff. Статусы задаёт сборщик 2А.
- Модель вызывается через исполнитель конституции только при `core.model_qualified: true`; без квалификации вызовов нет.
- Сквозной офлайн smoke: `python -m agent_service smoke`.

## Проверки

Офлайн на Windows: `tests/service` 65 тестов OK на локальных HTTP-стендах и Git-стенде Orders/Reporting; полный набор без новых падений против базы.

Не проверено: живые GitHub App и Jira (нет приложения, тестового репозитория, проекта Jira и права публикации), Linux.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

### PR 2Б

https://github.com/rengalaxies/agent/compare/claude/mvp-2a-core-205322...claude/mvp-2b-prep-9d9655

Заголовок: `feat(experiment): batch 2B open-model qualification program on the 2A executor`

```markdown
Часть [#50](https://github.com/rengalaxies/agent/issues/50): пачка 2Б, офлайн-часть. Стек: база — ветка 2А, сливать после PR 2А. Серия 22.10 не тронута.

## Что меняется

- Программа `experiments/autonomous_mvp/programs/2b-r1`: корпус transport + 20 development + 40 evaluation случаев, эталон только для оценщика, manifest с объёмом и стоимостью, пороги до прогона.
- `tools/autonomous_mvp/`: транспорт Cloud.ru, связка с исполнителем 2А (`actions-v3`, `run_investigation`), runner, ledger, scorer, dry-run всей программы.
- Workflow `.github/workflows/autonomous-mvp-model.yml` для запуска с `main`.

## Проверки

Офлайн на Windows: 70 тестов OK без пропусков; dry-run всей программы через тот же код, что в live: 143 case-runs, QUALIFIED. Сценарий знает эталон, так что это проверка трубопровода и scorer, не качества модели.

Не проверено: ни одного запроса к модели. Живой прогон — после слияния стека в `main`, в окружении с секретом `CLOUDRU_FOUNDATION_API_KEY`. Если перед этим слит PR 3, manifest нужно пересобрать: он хеширует файлы ядра и конституции.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

## Интерфейсы для следующих пачек

- Пачка 3: `RuntimeEvidence`, `GraphRelationship`, `Owner`, `entity_id`;
  стенд `examples/orders_reporting/` с `ownership.json`.
- Пачка 4: `AnalysisRequest` на входе, `change_result` /
  `preliminary_result` / `failed_result` на выходе, `display_verdict` для
  показа; `Graph.prepare_context(revisions=...)` и `analyze_change(revisions=...)`.
- Пачка 2Б: протокол `actions-v3` (`action_schema()`, `system_prompt()`),
  `run_investigation`, модель реализует `complete_raw`; диагностика отчёта
  `graph-investigation-2` разделяет слои отказа.

## Следующий шаг

Владелец открывает PR 2А по тексту выше. Первый прогон даёт Linux CI и
artifact `citation-measurement`; цифры из него вносятся в этот отчёт. Затем
запросы к контракту 2.1 из STATUS.md.
