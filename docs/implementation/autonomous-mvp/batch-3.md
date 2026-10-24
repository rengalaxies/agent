# Пачка 3: постоянный граф кода и наблюдаемых вызовов

Задача: https://github.com/rengalaxies/agent/issues/51. Сессия `mvp-3-runtime`,
ветка `claude/mvp-3-runtime-2a`. Основание: итог 2А `dde1f90`
(`origin/claude/mvp-2a-core-205322`). PR идёт против `claude/mvp-2a-core-205322`.

Ветка подтянута к `dde1f90` слиянием, а не rebase: rebase требовал force-push
опубликованной ветки, а его в этой среде запрещает классификатор. Дерево файлов
совпадает с результатом rebase (проверено `git diff` между ними: пусто).

Первая волна дала модель данных и runtime-адаптер. Вторая волна реализует всю
пачку: хранение, инвалидацию по основаниям, фильтрацию доступа, ownership,
свежесть, обновление по событию и сверку, graph query, просмотр, миграцию.

## Состояние

| Что | Состояние |
|---|---|
| Постоянный граф `src/agent_graph/graph_store.py` (store schema 2) | реализован, проверен офлайн |
| Предложения и исправления по конкретным основаниям (`engine.py`, `store.py`) | реализовано, проверено офлайн |
| Фильтрация доступа, свежесть, конфликты, ownership, graph query (`graph_query.py`) | реализовано, проверено офлайн |
| Обновление по событию и периодическая сверка (`graph_store_sync.py`) | реализовано; расписание сверки задаёт сервис (пачка 4/5А) |
| Просмотр для человека (`graph_view.py`, HTML и WSGI) | реализован, проверен офлайн; хостинг страницы в сервисе не подключён |
| Миграция store v1 → v2 с резервной копией | реализована, проверена на файле v1 |
| Контракт agent-graph-output 2.1 (`output_contracts.py`) | минорная версия, только добавления |
| Адаптер `access-log-jsonl-1` и HTTP-стенд | реализованы, проверены локально |
| Подключение к access logs или трассам клиента | не проверено: нет доступа ни к одному источнику клиента |
| Linux-прогон | не выполнялся здесь; его даст CI на PR |

## Что было до пачки 3

- `contracts.Policy.view_id()` хеширует права чтения. Контексты и предложения
  хранились по view: добавление репозитория давало новый view и прятало всю
  прежнюю память.
- Предложения были привязаны к `basis` всего корпуса. Правка README делала
  все исправления `STALE`.
- ID зависимости в `discovery.consumers` содержит `call_line`.
- Свежесть знала только смену `basis` и `limits.freshness_seconds`.
- Постоянного графа не было: каждый контекст пересчитывался целиком.

## Модель данных

### Область

Каждая сущность и связь принадлежит паре `(installation_id, environment)`, она
входит в каждый ID (`store.scope_id`). Сервис `orders` в `prod` и в `stage` это
разные узлы. Запись лога из чужого окружения адаптер отвергает
(`environment_mismatch`).

### Стабильные ID

`digest` означает `contracts.digest`, SHA-256 от канонического JSON.

| Сущность | ID | Что не входит в ID |
|---|---|---|
| Сервис | `output_contracts.entity_id(ServiceEntity)` | репозиторий, адрес, команда |
| Операция API | `entity_id(OperationEntity)` = `digest([installation, environment, service, METHOD, route])`, как в `discovery.operation_id` | версия кода, файл объявления |
| Место вызова | `graph_store.callsite_id`: `digest([installation, environment, "callsite", consumer, repository, path, operation_id, enclosing_symbol, ordinal])` | номер строки, commit, содержимое |
| Команда | `entity_id(TeamEntity)` | окружение |
| Связь | `digest([kind, source_id, target_id])`, `kind` из `calls`, `declares`, `owns` | основания, окна, статус |
| Основание кода | `digest(["code", relationship, locator, fragment_digest])` | commit, строки |
| Основание runtime | ID наблюдения адаптера (источник, пара, окно, сегменты) | время проверки |
| Основание владения | `digest(["owns", relationship, source])` | версия источника |

Правила:

- `route` берётся из объявления или из поля `route` наблюдения и проходит
  `normalize_route`. Сырой путь запроса шаблоном маршрута не становится.
- `enclosing_symbol` вычисляет `graph_store.enclosing_symbols` по AST файла:
  квалифицированное имя самой внутренней функции или класса, `<module>` на
  верхнем уровне. `ordinal` это номер вызова той же операции в этой функции.
  Строка остаётся атрибутом основания. Вставка строк выше вызова переносит
  основание (событие `transferred`), а не закрывает его.
- `CallsiteEntity` контракта содержит `line`, поэтому граф хранит место вызова
  со своим стабильным ID и полями `symbol`, `ordinal`, а `line` показывает как
  атрибут. Менять `CallsiteEntity` в 2.x нельзя: `line` обязателен, это
  ломающее изменение.
- Связь отделена от оснований. Ребро "Reporting вызывает GET /orders в Orders"
  одно, к нему прикреплены основания кода и runtime.

### Классы связей

| Внутреннее имя | `kind` | from → to | Откуда |
|---|---|---|---|
| `DECLARES` | `declares` | сервис → операция | объявление в коде |
| `CALLS_OPERATION` | `calls` | потребитель → операция | место вызова в коде; runtime только с method и route |
| `CALLS_SERVICE` | `calls` | потребитель → сервис | runtime без маршрута |
| `OWNS` | `owns` | команда → сервис | настроенный источник владения |

`CALLS_SERVICE` не порождает `CALLS_OPERATION`. В impact такое ребро
показывается только для пар, где маршрут неизвестен совсем, с пометкой
`runtime_route_not_recorded`.

### Основание

| Поле | Код | Runtime | Владение |
|---|---|---|---|
| что закреплено | repository, commit, blob, sha256 файла, path, строки, digest фрагмента, место вызова, usage | `RuntimeEvidence`, окно, полные агрегаты, `semantic_level` | team, source, source_version |
| за что отвечает синхронизация (`source_id`) | репозиторий | runtime-источник | источник владения |
| `visibility` | `[repository]` | `[source_id]` | `[source]` |

Происхождение, достаточность и свежесть остаются тремя полями. Флага
"достоверно" нет.

### Перенос, закрытие и история

Синхронизация вычисляет ожидаемые основания из прочитанного источника и
сравнивает их с активными:

| Случай | Событие |
|---|---|
| то же основание, данные те же | только `checked_at` |
| то же основание, новые commit или строки | `transferred` |
| основание было закрыто и вернулось (revert) | `reopened` |
| того же отношения, тот же фрагмент в другом месте вызова | старое `closed`, причина `code_moved`, `successor` = новое |
| то же место вызова, другой фрагмент | старое `closed`, `code_changed`, `successor` |
| вызов цели, которую больше никто не объявляет | `closed`, `target_not_declared` |
| место вызова исчезло | `closed`, `code_removed` |
| владелец сменился | `closed`, `ownership_changed` |

Закрыть основание может только синхронизация того источника, который его дал и
который реально прочитан. Недоступный репозиторий (`commit_unavailable`,
`source_unavailable`) или политика без этого репозитория не закрывают ничего.
Основание вызова закрывается, только если прочитаны и репозиторий потребителя,
и репозитории, где объявлена цель. Runtime-основания синхронизация не
закрывает вовсе: окно стареет.

Ничего не удаляется. Закрытое основание хранит версию, причину и преемника;
каждое событие пишется в `graph_events`. Это и есть tombstone: строка без
нового содержимого, отфильтрованная по тем же правам, что и активные. Физическое
удаление (purge по сроку хранения) не реализовано.

### Статус связи

Статус вычисляется при чтении из видимых оснований:

| Статус | Когда |
|---|---|
| `CONFLICT` | есть активные основания и правило конфликта ниже сработало |
| `ACTIVE` | есть активное основание со свежестью `CURRENT` |
| `STALE` | активные основания есть, свежих нет |
| `RETRACTED` | активных оснований нет, есть закрытые |

### Конфликт кода и наблюдений

| Код | Runtime | Результат |
|---|---|---|
| вызов `GET /orders` | та же операция | два основания одной связи, `ACTIVE` |
| вызов `GET /orders` | только ребро сервиса той же пары | ребро сервиса не подтверждает операцию |
| вызов `GET /orders` | ноль трафика, разрыв окна, sampling, источник недоступен | кодовая связь не меняется; runtime-сторона называет причину |
| вызов `GET /orders` | та же пара ходит только на другой маршрут | `CONFLICT`, `route_conflict` |
| вызов удалён | трафик в окне после версии удаления | `CONFLICT`, `runtime_after_removal` |
| нет | вызов или ребро сервиса | связь с `origins=[runtime]` |

### Свежесть по типам источников

`graph_query.FreshnessConfig`, значения по умолчанию:

| Тип | Срок | Что стареет |
|---|---|---|
| Git, закреплённый commit | не по времени | основание устаревает, если репозиторий не прочитан (`source_unavailable`) |
| Git, рабочая копия | `worktree_max_age_seconds` = 3600 | всегда с причиной `worktree_not_reproducible` |
| runtime | `runtime_max_age_seconds` = 86400 от конца окна | `age_exceeded`; `window_gap`, `sampled_source` из окна; `source_unavailable` |
| ownership | `ownership_max_age_seconds` = 604800 от последнего успешного чтения | `age_exceeded`, `source_unavailable` |

Отсутствие трафика, sampling, разрыв окна и недоступность источника дают
разные причины. Ни одна не закрывает кодовую связь и не доказывает отсутствие
потребителя.

### Владение

Один настроенный источник: `installation_mapping` (файл вида
`examples/orders_reporting/ownership.json`, модель
`graph_store.OwnershipMapping`). Значение сервиса это команда или список команд.

- Нет записи: `Owner.status=UNKNOWN`; просмотр пишет "команда не определена".
- Список из нескольких команд: `CONFLICT`, видны все, адресат не выбирается.
- Смена команды закрывает старое основание; `GraphQuery.owner_history` показывает
  обе версии.
- Файл не читается: последние владельцы остаются, источник `STALE` с
  `source_unavailable`.
- `codeowners` и `service_catalog` предусмотрены моделью, но не реализованы.

## Хранение (store schema 2)

Один файл `graph.sqlite3`, как и раньше. Таблицы v1 (`heads`, `artifacts`,
`proposals`, `reservations`) не меняются. Новые таблицы:

| Таблица | Содержимое |
|---|---|
| `meta` | `store_schema`, отметка импорта контекстов |
| `proposal_bases` | для каждого предложения: scope, visibility (процитированные репозитории), процитированные файлы с sha256 |
| `graph_entities`, `graph_relationships` | сущности и связи со стабильными ID |
| `graph_bases` | основания: origin, source, visibility, data, версия открытия и закрытия, причина, преемник |
| `graph_events` | история: `opened`, `transferred`, `reopened`, `closed` по версиям |
| `graph_versions` | версия графа: время, trigger (`event`, `reconcile`, `migration`), источник, сводка |
| `graph_sources` | состояние источника: статус, последняя проверка, последний успех, версия |

`graph_version` для `AnalysisRequest`/`AnalysisResult` равен `graph-<номер>`.

## Предложения и исправления

`Graph.proposals(context)` больше не сравнивает `basis` корпуса. Предложение
держится (`holds`), пока у каждого процитированного файла в этом контексте тот
же sha256. Иначе `STALE` с `proposal_basis_differs`. Правка README не задевает
исправление, которое на README не ссылается.

Предложения хранятся по scope и видны любому view того же окружения, которому
выданы все процитированные репозитории. Добавление репозитория память не
теряет; сужение прячет предложения с отозванными репозиториями. Лимит
`max_proposals` считает активные (держащиеся, не заменённые) предложения.

## Доступ

`GraphQuery(graph_store, installation, environment, grants)` или
`GraphQuery.for_policy(graph_store, policy, runtime_sources=..., ownership_sources=...)`.
`grants` это id репозиториев, runtime-источников и источников владения.

- Основание видно, если все его `visibility` выданы.
- Связи, сущности, поиск, impact, счётчики `summary()`, история и просмотр
  строятся только из видимых оснований.
- Старый ID связи или основания без прав даёт `not_found`.
- Старый `context_id` чужого view даёт `not_found` в `Graph.context` и
  `Graph.get_evidence` (view входит в ключ артефакта).
- Объект `GraphQuery` это снимок для одного набора прав и единственный cache.
  WSGI-просмотр отдаёт `Cache-Control: no-store`.
- Расширение прав возвращает прежнюю память: ничего не удалялось.

## Обновление и сверка

`graph_store_sync.GraphMaintainer(graph, graph_store, runtime_sources=..., ownership_path=...)`:

- `on_code_event(revisions)` готовит контекст по закреплённым commit и
  применяет его (`GraphStore.sync_code`);
- `on_runtime_window(source, start, end)` читает окно access logs и применяет
  его (`sync_runtime`);
- `on_ownership_change()` перечитывает файл владения (`sync_ownership`);
- `reconcile(revisions, now)` вызывает всё это с trigger `reconcile`. Сбой
  одного источника не останавливает остальные; пропущенное событие
  подхватывается следующей сверкой.

Полный пересчёт против частичного. Извлечение из кода по-прежнему один полный
проход ядра на контекст. Частичная часть это применение разницы к сохранённому
графу (перенос, закрытие, переоткрытие). `GraphStore.canonical_facts` убирает
время и версии; тест сравнивает граф, построенный с нуля по последнему
контексту, с графом после цепочки синхронизаций. Отдельной оптимизации
извлечения по замерам не делал: замеров на Linux здесь нет.

## Graph query для агента и сервиса

Интерфейс для mvp-4-service (Jira-before-diff) и для модельного инструмента:

```python
from agent_graph.graph_store import GraphStore
from agent_graph.graph_query import GraphQuery, dispatch

query = GraphQuery.for_policy(GraphStore(store), policy, runtime_sources=["access"])
query.find(text, kind=None | "service" | "operation", limit=20) -> [{id, entity, label}]
query.neighbors(entity_id, direction="in" | "out" | "both", limit=50) -> [relationship view]
query.impact(entity_id, depth=2, limit=50) -> {graph_version, target, paths, affected,
                                              relationships, evidence, unknowns, sources}
query.relationship(relationship_id) -> view с bases, history, conflicts, contract
query.owner(service) -> Owner (agent-graph-output)
query.owner_history(service) -> [{team, source, source_version, opened_version, closed_version, closed_reason}]
query.source_freshness() -> [SourceFreshness + status, source_version, last_success_at]
query.summary() -> счётчики по видимым данным
dispatch(query, {"tool": "graph_find" | "graph_neighbors" | "graph_impact"
                 | "graph_relationship" | "graph_owner", ...}) -> результат одного вызова
```

Пределы: `limit` до 100, `depth` до 3, текст до 200 символов, ID только
64-hex. `GraphQueryRequest` строгий: лишние поля и неизвестный инструмент
отвергаются, свободного языка запросов нет.

`impact()` отдаёт части `AnalysisResult` в готовом виде: `affected` (сервис,
`Owner`, ссылки на связи), `paths` (`relationship_refs`, `summary`),
`relationships[*]["contract"]` (`GraphRelationship`), `evidence` (`CodeEvidence`
и `RuntimeEvidence`), `sources` (`SourceFreshness`), `unknowns`
(`owner_unknown`, `owner_conflict`, `runtime_route_not_recorded`). Тест
`test_impact_feeds_a_valid_analysis_result` собирает из них документ и
проверяет его `parse_document`.

## Просмотр для человека

`graph_view.render_html(query, environments=[...], source_links={repo: template})`
даёт одну HTML-страницу без скриптов и внешних ресурсов:

- источники с состоянием, версией и свежестью;
- для каждой операции: владелец провайдера, объявление с историей, таблица
  путей влияния глубиной до 2 со статусом, свежестью, командой потребителя и
  основаниями (код: `repo/path:строка (функция) @commit`, runtime: источник,
  маршрут, окно, число запросов), закрытые основания с причиной;
- ребра без маршрута отдельным списком с пометкой, что это не зависимость от
  операции.

Ссылка на исходник ставится, только если для репозитория задан http(s)-шаблон.
Все значения экранируются. `make_app(query_for, environments)` отдаёт страницу
по WSGI: только GET, фильтр `?environment=`, неизвестное окружение 404,
`Cache-Control: no-store`, CSP `default-src 'none'`. Хостинг страницы в
сервисе делает пачка 4/5А.

## Миграция

`Store()` при открытии файла v1 с данными:

1. снимает копию `graph.v1-backup.sqlite3` (SQLite backup API, права 0600) до
   любых изменений;
2. одной транзакцией добавляет таблицы schema 2 и пишет `store_schema=2`;
3. вычисляет `proposal_bases` для старых предложений из их контекстов. Если
   контекст не найден, предложение остаётся в истории, никогда не `CURRENT` и
   никому не видно.

Таблицы v1 не меняются (никаких `ALTER TABLE`). Откатившийся бинарник v1
продолжает читать и дописывать `proposals` тремя колонками; v2 вычисляет для
таких строк основания при чтении и при следующем открытии. Файл новее schema 2
отвергается (`store_schema_newer`), соединение при этом закрывается.

`GraphStore.import_contexts()` один раз проигрывает все сохранённые контексты
от старых к новым как синхронизации кода с trigger `migration`. Старые
контексты остаются артефактами и читаются как раньше. Проверка: тест берёт
файл, записанный схемой v1, открывает его, сверяет контекст байт в байт,
статус предложения, импорт и повторный импорт.

Возврат: откат образа без отката схемы безопасен (таблицы только добавлены).
Полный возврат состояния это восстановление `graph.v1-backup.sqlite3`; события,
пришедшие после миграции, при этом теряются, их вернёт сверка.

## Контракт agent-graph-output 2.1

Минорная версия, только добавления. Читатель 2.1 принимает документы 2.0;
читатель 2.0 отвергает 2.1 как `newer_schema_minor`, это поведение 2А.

| Что | Добавлено |
|---|---|
| `FreshnessReason` | `not_instrumented`, `route_not_recorded`, `route_conflict` |
| `UnknownCode` | `runtime_not_instrumented`, `runtime_route_not_recorded`, `runtime_route_conflict` |
| `GapCode` | `runtime_window_gap` |
| `Claim.subject` | необязательная сущность. Факт с `subject` операции требует основания кода или runtime с тем же сервисом, методом и маршрутом; иначе `fact_without_operation_evidence` |

`schemas/agent-graph-output-2.json` перегенерирован. В
`tests/graph/test_output_contracts.py` пример "более новой минорной версии"
сменён с `2.1` на `2.9`. Не сделано из списка первой волны: интервал в `Gap`
и расширенные `RuntimeAggregates` (наблюдение держит их само);
`CallsiteEntity.line` (см. выше).

## Runtime-коннектор `access-log-jsonl-1`

Без изменений по сравнению с первой волной, кроме кодов 2.1 в `assess`.

Источник это каталог закрытых сегментов: `NAME.jsonl` и `NAME.coverage.json`
(`schema`, `file`, `emitter`, `environment`, `start`, `end`, `sample_rate`,
`sha256`). Запись пишет вызываемый сервис: `ts` со смещением, `service`, `env`,
`client`, `method`, `route`, `status`, `duration_ms`. `path` не читается.

| Ситуация | Поведение |
|---|---|
| каталог недоступен | `UNAVAILABLE`, наблюдений нет |
| сегмент без `coverage.json` | не читается (`open_segment_ignored`) |
| SHA-256 сегмента не совпал | сегмент пропущен, интервал в `gaps` |
| битая или отвергнутая запись, кроме чужого окружения | запись пропущена, интервал в `gaps` как `corrupt_records` |
| неизвестный `client` | `unattributed`, псевдоним только как digest |
| маршрут невалиден или с `..` | считается отсутствующим, остаётся ребро сервиса |

| Оценка `assess` | `FreshnessReason` | `UnknownCode` |
|---|---|---|
| `OBSERVED` | нет | нет |
| `NO_TRAFFIC_OBSERVED` | `no_traffic_in_window` | `runtime_not_observed` |
| `SAMPLED_NOT_OBSERVED` | `sampled_source` | `runtime_not_observed` |
| `WINDOW_GAP` | `window_gap` | `runtime_window_gap` |
| `SOURCE_UNAVAILABLE` | `source_unavailable` | `runtime_not_observed` |
| `CALLEE_NOT_INSTRUMENTED` | `not_instrumented` | `runtime_not_instrumented` |
| `ROUTE_NOT_RECORDED` | `route_not_recorded` | `runtime_route_not_recorded` |
| `OTHER_ROUTE_OBSERVED` | `route_conflict` | `runtime_route_conflict` |

`proves_absence` всегда `false`.

## Стенды

- `examples/orders_reporting/stand.py` (2А): пять Git-репозиториев с
  фиксированными SHA. Тесты пачки 3 добавляют в него две ветки reporting той
  же plumbing-техникой: `shifted` (строки вставлены выше вызова) и `renamed`
  (`client.py` перенесён в `exports/client.py`).
- `tools/agent_service/runtime_stand/stand.py`: настоящие HTTP-вызовы на
  loopback, Reporting → Orders и Health → Inventory (тот же `GET /orders`).
  `run_stand(out, installation=..., environment=...)` позволяет писать логи в
  scope Git-стенда (`acme`/`prod`).

```bash
python tools/agent_service/runtime_stand/stand.py --out /tmp/runtime-stand
```

Проверен стенд. Подключение к источнику клиента не проверено.

## Приёмка раздела 9

| Требование | Тест |
|---|---|
| полный и частичный пересчёт совпадают на изменении, переименовании, удалении | `test_graph_store.RecomputeTests.test_full_and_incremental_builds_match_on_change_rename_and_deletion` |
| сдвиг строк не меняет место вызова | `RecomputeTests.test_line_shift_above_a_call_keeps_the_callsite_and_its_basis` |
| удалённый код снимается с историей, revert переоткрывает | `RecomputeTests.test_deleted_code_is_retracted_with_history_not_erased` |
| несвязанная правка не теряет исправления, изменение основания делает статус явным | `KnowledgeTests.test_unrelated_edit_keeps_corrections_and_a_cited_change_makes_them_stale` |
| добавление репозитория не теряет исправления | `KnowledgeTests.test_adding_an_allowed_repository_keeps_earlier_knowledge` |
| отказ коннектора: последний снимок устаревает, сверка возобновляет и ловит пропущенное событие | `RecoveryTests.test_unavailable_repository_keeps_last_snapshot_stale_and_reconcile_resumes` |
| после отзыва доступа недоступны cache, счётчики, история, старые ссылки; у оставшихся история цела | `AccessTests.test_revoked_repository_disappears_from_graph_cache_counters_history_and_old_ids`, `test_graph_query...test_runtime_source_without_grant_is_invisible`, `test_graph_view...test_revoked_repository_is_not_on_the_page` |
| смена ownership с историей, неизвестный и конфликтующий владелец не называются | `OwnershipTests.test_owner_change_keeps_history_and_unknown_or_conflicting_owner_is_never_named`, `...test_unreadable_ownership_source_keeps_last_owner_and_turns_stale` |
| миграция с проверкой старых контекстов и исправлений | `MigrationTests.test_v1_state_migrates_with_backup_and_keeps_contexts_and_corrections`, `...test_newer_store_schema_is_refused` |
| ноль трафика не удаляет кодовую связь; runtime без route не приписывает маршрут | `test_graph_query.RuntimeNextToCodeTests.test_zero_traffic_keeps_the_code_dependency_and_a_routeless_edge_stays_service_level` |
| два сервиса с одним path не сливаются | `RuntimeNextToCodeTests.test_same_path_of_another_service_is_a_separate_operation`, `test_runtime_observations...test_two_services_with_the_same_path_stay_two_operations` |
| конфликт кода и наблюдений виден как конфликт | `RuntimeNextToCodeTests.test_runtime_on_another_route_of_the_pair_is_a_visible_conflict`, `...test_traffic_after_code_removal_is_a_conflict_not_a_silent_choice` |
| недоступный или старый runtime меняет только свежесть | `RuntimeNextToCodeTests.test_unavailable_or_old_runtime_changes_freshness_only` |
| реальный HTTP-стенд → наблюдение → ребро в графе рядом с кодом | `test_graph_query.HttpStandTests.test_real_http_calls_become_a_directed_runtime_edge_next_to_code` |
| ограниченный graph query | `QueryToolTests.test_tool_calls_are_validated_and_bounded`, `...test_impact_feeds_a_valid_analysis_result` |
| человек видит путь, происхождение, свежесть без CLI | `test_graph_view.ViewTests` (4 теста) |

Раздел 9 называет также `tests/service/`. Эта папка принадлежит mvp-4-service;
регрессии вызова graph query из сервиса появятся там вместе с интеграцией.

## Прогоны

2026-10-24, Windows 11 Pro 10.0.26200, Python 3.14.0, venv в worktree.

- `PYTHONPATH="src;." python -m unittest tests.graph.test_graph_store tests.graph.test_graph_query tests.graph.test_graph_view tests.graph.test_runtime_observations tests.graph.test_output_contracts`:
  все OK, в том числе с `-W error::ResourceWarning`.
- Мутационная проверка: восемь поломок по очереди, каждую ловят от 1 до 3
  тестов. Предложение держится только при совпадении корпуса: 3. Синхронизация
  закрывает основания непрочитанных репозиториев: 1. Нет фильтра доступа: 3.
  Нет распознавания переноса: 1. Ребро сервиса дублирует ребро операции: 1.
  Конфликт маршрута игнорируется: 1. Нестабильный ID места вызова: 3.
  Предложения без учёта прав: 1.
- Полный `tests/graph`: 226 тестов, failures=2, errors=28. База до пачки на
  том же Windows (`dde1f90`): 202 теста, failures=2, errors=28, те же самые
  тесты. Все 30 падений вызваны Windows: 27 `fixture_digest_mismatch` (CRLF в
  checkout), права на symlink, CRLF в сравнении текста. 24 новых теста
  пачки 3 проходят.
- `tests/graph_demo`: 38 тестов, 7 ошибок, все из-за Windows (`os.geteuid`,
  WinError 193), failures нет. Одно утверждение в `test_graph_cli.py` закрепляло старое
  правило "любая правка обесценивает все предложения"; оно заменено на новое
  (заметка на неизменённом файле потребителя остаётся `CURRENT`).
- `ruff check src services tools stand lab/app lab/product lab/runtime --select F401,F811,F841`: чисто.

- Промежуточные коммиты проверены в отдельном временном worktree: после
  `c6e5b53` проходят `test_knowledge_regressions`, `test_graph`, `test_results`,
  `test_graph_cli` (кроме двух известных ошибок Windows), после `0fae0d4`
  проходят `test_output_contracts`, `test_runtime_observations`, `test_results`.

## Что осталось

- Linux-прогон и замеры времени и памяти синхронизации: CI на PR.
- Источники владения `codeowners` и `service_catalog`.
- Purge по сроку хранения (физическое удаление с журналом).
- Расписание сверки, хостинг просмотра и вызов graph query из сервиса:
  mvp-4-service и mvp-5a-box.
- Подключение graph query к модельному executor (`actions-v3`): инструменты
  `graph_*` есть в `dispatch`, но не добавлены в allowlist конституции; это
  область 2А/2Б.
- Частичное извлечение по изменённым файлам, если замеры покажут, что полный
  проход ядра дорог.
- Живое подключение runtime-источника клиента: нужен доступ на чтение к его
  access logs или Tempo/OTel и описание идентичности вызывающего.
