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

## Что нужно поменять вне путей этой сессии

Эти файлы принадлежат другим строкам WAVES.md или общей инфраструктуре; без
правок CI по PR покажет известные падения.

1. `.github/workflows/graph-evidence-refs.yml`: ставит только pydantic, а
   `agent_graph.constitution` импортирует PyYAML (зависимость пакета уже в
   `pyproject.toml`). Нужно `pip install 'pydantic>=2.10,<3' 'PyYAML>=6.0,<7' ruff==0.17.1`.
2. `.github/workflows/agent-graph-demo.yml`: убрать `git worktree add ...
   18e8b71...` и `DEMO_CORE_ROOT`; шаг «Accepted core regression» запускать
   на checkout PR. С внешним старым ядром `GraphCLI` теперь честно падает с
   `core_pin_mismatch`.
3. `infra/agent_graph_demo/` (Dockerfile, `core.lock.json`) и
   `tools/agent_graph_demo/{accept,configure}.py`: перестать монтировать
   отдельный checkout ядра; `--core-root` можно не передавать. Это упаковка 5А.
4. Тесты `tests/graph_demo/test_runner.py` вызывают `os.geteuid` из
   `tools/agent_graph_demo`; на Windows они падают, на Linux не затронуты.

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

Открыть PR из ветки, прогнать Linux CI с правками workflow из списка выше и
снять Linux-время и память задания с многими цитатами на CI-раннере.
