# Пачка 3, часть 1: модель данных графа и runtime-адаптер

Задача: https://github.com/rengalaxies/agent/issues/51. Сессия `mvp-3-runtime`,
ветка `claude/mvp-3-runtime-1b13b3`, основание: коммит контрактов 2А
`d8dd64a` (ветка `claude/mvp-2a-core-205322`) поверх `main` 9d7480d.

Эта часть фиксирует модель данных постоянного графа до миграции и даёт один
настоящий runtime-адаптер. Хранение графа, инвалидацию по основаниям, фильтрацию
доступа, миграцию состояния и просмотр для человека делает следующая волна
поверх контрактов 2А (раздел "Что осталось" в конце).

## Состояние

| Что | Состояние |
|---|---|
| Модель данных (этот документ) | описана, кодом пока не исполняется, кроме идентичностей runtime |
| Адаптер `access-log-jsonl-1` в `src/agent_graph/runtime_observations.py` | реализован, проверен офлайн |
| Стенд `tools/agent_service/runtime_stand/` с настоящими HTTP-вызовами | реализован, проверен локально (Windows, Python 3.14) |
| Подключение к access logs или трассам клиента | не проверено: нет доступа ни к одному источнику клиента |
| Приведение к контракту 2А (`output_contracts.py`, agent-graph-output 2.0) | сделано: `RuntimeEvidence`, `GraphRelationship`, `SourceFreshness`; сквозной тест проходит `parse_document` |
| Запись наблюдений в граф | не сделана, это следующая волна |

## Что есть в коде сейчас

Модель ниже опирается на текущий `main`, а не заменяет его.

- `contracts.Policy` задаёт область: `installation_id`, `environment`,
  репозитории, адреса сервисов. `view_id()` хеширует права чтения без
  `revision`, поэтому одинаковые права делят контексты.
- `discovery.operation_id` считает ID операции как
  `digest([installation_id, environment, service, METHOD, path])`. Окружение
  уже входит в ID, поэтому одноимённые операции разных окружений не
  смешиваются. Адаптер использует ту же формулу.
- ID зависимости в `discovery.consumers` равен
  `digest([operation_id, repository, path, call_line])`. Номер строки делает ID
  нестабильным: правка выше вызова меняет идентичность места вызова.
- `store.Store` хранит контексты как неизменяемые артефакты с `heads(view)`.
  Предложения и исправления привязаны к `basis` всего корпуса.
  `engine.Graph.proposals` помечает исправление `STALE`, как только `basis`
  корпуса отличается. Отсюда проблема из раздела 2 SPEC: несвязанная правка
  README обесценивает все исправления.
- `engine.Graph.freshness` знает два основания устаревания: изменился `basis`
  или превышен `limits.freshness_seconds`. Типов источников и окон наблюдения
  там нет.
- `store.py` импортирует `fcntl`, `sources.read_relative` использует
  `O_DIRECTORY`/`O_NOFOLLOW`. Ядро графа запускается только на POSIX. Адаптер
  runtime намеренно не зависит от этих модулей и работает и на Windows.

## Модель данных

### Область

Каждая сущность и связь принадлежит паре `(installation_id, environment)`.
Эта пара входит в каждый ID. Сервис `orders` в `prod` и `orders` в `stage`
остаются разными узлами, даже если у них один репозиторий. Связь между
окружениями не строится автоматически: если запись лога из `stage` попала в
источник `prod`, адаптер отвергает её с причиной `environment_mismatch`.

### Стабильные ID

`digest` здесь означает `contracts.digest`, то есть SHA-256 от канонического JSON.

| Сущность | ID | Что не входит в ID |
|---|---|---|
| Сервис | `output_contracts.entity_id(ServiceEntity)`, то есть `digest` от `{kind, installation_id, environment, service}` | репозиторий, адрес, команда |
| Операция API | `entity_id(OperationEntity)` = `digest([installation, environment, service, METHOD, route])`, как в `discovery.operation_id` | версия кода, файл объявления |
| Место вызова | `digest([installation, environment, "callsite", consumer_service, repository, path, operation_id, enclosing_symbol, ordinal])` | номер строки, commit, содержимое |
| Репозиторий | `digest([installation, environment, "repository", repository_id])` | revision |
| Команда | `digest([installation, "team", team_key])` | окружение: команда одна на установку |
| Источник runtime | `digest([installation, environment, "runtime_source", source_id])` | файлы сегментов |
| Связь | `digest([kind, from_id, to_id])`, `kind` из `GraphRelationship` (`calls`, `declares`, `owns`, `may_affect`) | основания, окна, статус |

Правила:

- `route` берётся из объявления (OpenAPI path, декоратор FastAPI) или из поля
  `route` наблюдения и приводится `output_contracts.normalize_route` (схлопывание
  `//`, без хвостового `/`). Метод приводится к верхнему регистру. Сырой путь запроса
  (`/orders/123`) никогда не превращается в шаблон маршрута: угадывание
  шаблона склеило бы разные операции.
- Место вызова идентифицируется функцией, в которой оно стоит
  (`enclosing_symbol`, квалифицированное имя), и порядковым номером вызова той
  же операции внутри этой функции. Номер строки остаётся атрибутом основания.
  Так вставка строки выше вызова не меняет ID. Текущий
  `digest([..., call_line])` следующая волна мигрирует на эту формулу (см.
  "Миграция").
- Переименование файла или функции даёт новое место вызова. Старое получает
  tombstone `code_moved` со ссылкой на новое, если совпал digest процитированного
  фрагмента. Иначе старое закрывается как `code_removed`, а новое появляется
  независимо.
- Связь отделена от оснований. Ребро "Reporting вызывает GET /orders в Orders"
  одно. К нему прикреплены основания разных классов: место вызова в коде,
  наблюдение runtime, гипотеза модели, исправление человека.

### Классы связей

| kind | from → to | Откуда берётся |
|---|---|---|
| `DECLARES` | сервис → операция | объявление в коде |
| `CALLS_OPERATION` | сервис-потребитель → операция | место вызова в коде; наблюдение runtime только при известных method и route |
| `CALLS_SERVICE` | сервис → сервис | наблюдение runtime без маршрута; выводится и из `CALLS_OPERATION` |
| `OWNS` | команда → сервис | настроенный источник владения |
| `MAY_AFFECT` | Jira/PR → сервис или операция | анализ; хранится как результат анализа, не как факт |

`CALLS_SERVICE` из runtime не порождает `CALLS_OPERATION`. Если в логе нет
маршрута, граф знает только "Reporting обращается к Orders".

В контракте 2.0 оба класса вызова выражены одним `GraphRelationship.kind="calls"`.
Различает их цель: `ServiceEntity` для `CALLS_SERVICE`, `OperationEntity` для
`CALLS_OPERATION`. Имена в таблице остаются внутренними именами модели.

### Основание

Основание (basis) это единица, которую можно проверить и инвалидировать отдельно.

| Поле | Код | Runtime | Гипотеза модели | Исправление |
|---|---|---|---|---|
| `origin` | `code` | `runtime` | `model_hypothesis` | `correction` |
| что закреплено | repository, commit, blob digest, path, строки, digest фрагмента | source, service identities, окно, method/route при наличии, агрегаты | модельная конфигурация, supporting refs | автор, ссылки на основания, которые исправляются |
| `dependency_key` | `(repository, path, blob digest)` | `(source_id, segment digests)` | множество `dependency_key` его refs | множество `dependency_key` его refs |
| `valid_interval` | от commit, где фрагмент появился, до commit, где он изменился | окно наблюдения | от создания до изменения любой ref | от создания до изменения любой ref |
| `checked_at` | время последней сверки с Git | время чтения источника | время валидации refs | время валидации refs |

Происхождение, семантическая достаточность и свежесть хранятся тремя полями:

- `provenance`: откуда основание, с digest входа;
- `sufficiency`: что оно доказывает. Для runtime в контракте 2.0 это
  `OBSERVED_WITHIN_WINDOW` для того ребра, к которому основание прикреплено.
  Уровень (`service` или `operation`) выражен наличием `method`/`route` в
  `RuntimeEvidence` и полем `semantic_level` наблюдения. Валидная цитата
  доказывает прочтение, а не зависимость;
- `freshness`: `CURRENT`, `STALE` или `UNKNOWN` с причинами.

Флага "достоверно" нет.

### Перенос оснований

Новый снимок Git или новое чтение runtime не пересоздают граф, а сверяются
с прежними основаниями.

1. Код. Если blob digest файла не изменился, основание переносится: к нему
   добавляется новый commit, `checked_at` обновляется. Если файл изменился, но
   место вызова с тем же ID существует и digest процитированного фрагмента тот
   же, основание переносится с полем `transferred_from` (старые строки, старый
   blob). Если фрагмент изменился, старое основание закрывается
   (`valid_interval.end` = новый commit), новое создаётся.
2. Runtime. Наблюдения окон не переносятся: у каждого окна своё основание.
   Новое окно добавляет основание, старое стареет по правилам свежести.
3. Исправления и гипотезы зависят от множества `dependency_key` своих ссылок.
   Правка README меняет только `(repository, README.md, blob)`. Исправление,
   которое на README не ссылается, остаётся `CURRENT`. Это заменяет текущую
   привязку к `basis` всего корпуса.
4. Статус связи вычисляется из активных оснований, а не хранится отдельно.

### Удаление, tombstone и история

Три события выглядят похоже, но последствия у них разные.

| Событие | Что происходит с основанием | Что видно в связи |
|---|---|---|
| Код удалён (место вызова исчезло в новом commit) | закрывается, tombstone `code_removed` с commit | если других активных оснований нет, связь `RETRACTED`; история сохраняется |
| Окно наблюдения закончилось, нового нет | остаётся, стареет до `STALE` по политике свежести | связь не удаляется; runtime-часть помечена устаревшей |
| Источник недоступен | остаётся, получает причину `source_unavailable` | кодовые основания не затронуты |
| Ноль трафика в покрытом окне | новое основание не создаётся, оценка `NO_TRAFFIC_OBSERVED` | кодовая связь остаётся `CURRENT` |
| Доступ к репозиторию или источнику отозван | скрывается для этого view, не удаляется | у кого доступа нет, тот не видит ни основания, ни счётчиков, ни истории |
| Доступ возвращён | снова виден, история цела | |

Tombstone хранит ID, причину, время, версию источника и ссылку на преемника.
Текста, путей и счётчиков в tombstone нет, поэтому после отзыва доступа он не
раскрывает содержимое. Физическое удаление выполняется только при удалении
установки или по сроку хранения, который задаёт конфигурация; это отдельная
операция с записью в журнал.

### Владение

Владение хранится как отдельная сущность `Team` и связь `OWNS` со своим основанием:

- `source`: `service_catalog`, `codeowners` или `installation_mapping`;
- `source_version`: commit CODEOWNERS, ревизия каталога или версия конфигурации
  установки;
- `checked_at`, свежесть по типу источника, `valid_interval`.

Правила:

- Владелец неизвестен: ответ называет сервис и пишет "команда не определена".
  Адресат не угадывается.
- Два источника называют разные команды: `OWNER_CONFLICT`, видны обе с
  источниками, адресат не выбирается.
- Смена владельца закрывает старое основание и открывает новое. История
  показывает, кто был владельцем и по какому источнику.
- Связь `OWNS` не даёт команде права согласовывать выпуск.

### Конфликт кода и наблюдений

Сравнение идёт по связи, а не по общему флагу.

| Код | Runtime | Результат |
|---|---|---|
| `CALLS_OPERATION` | наблюдение той же операции | два независимых основания одной связи |
| `CALLS_OPERATION` | только `CALLS_SERVICE` той же пары | runtime подтверждает пару сервисов, но не операцию; `ROUTE_NOT_RECORDED` |
| `CALLS_OPERATION` | ноль трафика в покрытом окне | кодовая связь `CURRENT`, runtime-оценка `NO_TRAFFIC_OBSERVED` |
| `CALLS_OPERATION` | окно с разрывом, sampling, неинструментированный сервис, источник недоступен | кодовая связь `CURRENT`, runtime-оценка называет причину |
| `CALLS_OPERATION` на `GET /orders` | та же пара сервисов ходит только на другой маршрут | `CONFLICT`: оба основания видны, ни одно не выбрано молча |
| нет | `CALLS_OPERATION` или `CALLS_SERVICE` | `RUNTIME_ONLY`: кандидат на пробел статической грамматики |
| удалён в новом commit | трафик продолжается в окне после commit | `CONFLICT`: возможен не задеплоенный код или другой клиент |

Последний случай важен: runtime может опережать или отставать от Git. Граф не
решает, кто прав, а показывает оба основания с версиями и окнами.

### Свежесть по типам источников

Политику свежести задаёт конфигурация установки для каждого типа источника.
Значения по умолчанию в адаптере:

| Тип источника | `max_age_seconds` по умолчанию | Что стареет |
|---|---|---|
| `access_log` | 86400 | наблюдение, если от конца окна прошло больше |
| `trace` (будущий адаптер) | 86400 | так же |
| `git` | не по времени | по смене commit в закреплённой карте |
| `ownership` | 604800 | связь `OWNS` |

Для пары сервисов, которую ждём по коду, адаптер различает исходы:

| Оценка | Когда | Доказывает отсутствие потребителя |
|---|---|---|
| `OBSERVED` | есть записи пары в окне | нет, это положительное основание |
| `NO_TRAFFIC_OBSERVED` | окно полностью покрыто, sampling 1.0, записей нет | нет |
| `SAMPLED_NOT_OBSERVED` | покрыто, но sampling ниже 1.0 | нет |
| `WINDOW_GAP` | у вызываемого сервиса нет покрытия части окна или сегмент повреждён | нет |
| `CALLEE_NOT_INSTRUMENTED` | источник не обещает логов этого сервиса | нет |
| `SOURCE_UNAVAILABLE` | источник не прочитан | нет |
| `ROUTE_NOT_RECORDED` | пара видна, но маршрут в записях отсутствует | нет |
| `OTHER_ROUTE_OBSERVED` | пара видна, но с другим записанным маршрутом; это конфликт с кодом | нет |

Поле `proves_absence` у оценки всегда `false`.

## Runtime-коннектор `access-log-jsonl-1`

Почему access logs: Tempo или OTel здесь недоступны, а раздел 3 SPEC разрешает
структурированные логи. Grafana с CPU/RPS направления вызова не даёт.

### Формат источника

Источник это каталог. Каждый закрытый сегмент состоит из двух файлов:

- `NAME.jsonl`: по одной JSON-записи на строку;
- `NAME.coverage.json`: метаданные, которые пишет процесс при ротации:

```json
{"schema": "access-log-segment-1", "file": "NAME.jsonl", "emitter": "orders-1",
 "environment": "stand", "start": "2026-10-24T10:00:00+00:00",
 "end": "2026-10-24T10:05:00+00:00", "sample_rate": 1.0, "sha256": "..."}
```

Запись:

```json
{"ts": "2026-10-24T10:00:01.250+00:00", "service": "orders-1", "env": "stand",
 "client": "reporting", "method": "GET", "route": "/orders", "path": "/orders?day=1",
 "status": 200, "duration_ms": 3.1}
```

Запись пишет вызываемый сервис (серверный access log). `client` содержит идентичность
вызывающего: заголовок, peer mTLS или поле service mesh. Без `client` запрос
попадает в `unattributed` и ребра не даёт.

### Нормализация

- Идентичности. Конфигурация источника задаёт `identities: [{alias, service}]`.
  Псевдоним сравнивается без учёта регистра. Неизвестный псевдоним не
  угадывается: запрос попадает в `unattributed`, а сам псевдоним выдаётся только
  как digest (данные лога недоверенные).
- Время. Принимается ISO 8601 только со смещением. Время без зоны отвергается
  (`timestamp_without_offset`). Всё приводится к UTC.
- Окно. Запрос задаёт `[start, end)` в UTC, не длиннее `max_window_seconds`.
  Покрытие сегментов обрезается окном; записи вне окна не считаются.
- Метод и маршрут. Метод из allowlist HTTP. Маршрут принимается только из поля
  `route`, по шаблону `^/[A-Za-z0-9._~{}:/-]*$`, не длиннее 200 символов.
  Маршрут с `..` отвергается. Поле `path` не читается. Невалидный маршрут
  считается отсутствующим, запрос остаётся в ребре `CALLS_SERVICE`.
- Агрегаты. `request_count` есть всегда. `error_count` и `client_error_count`
  появляются, только если у всех записей есть `status`. `latency_ms` (p50, p95)
  появляется, только если у всех записей есть `duration_ms`. При sampling ниже
  1.0 дополнительно выдаётся `estimated_request_count` с пометкой оценки.

### Отказы и пределы

| Ситуация | Поведение |
|---|---|
| Каталог не существует, не каталог или symlink | `status=UNAVAILABLE`, наблюдений нет, весь интервал в `gaps` |
| Сегмент без `coverage.json` (ещё пишется) | не читается, причина `open_segment_ignored` |
| SHA-256 сегмента не совпал | сегмент пропущен, его интервал в `gaps` (`segment_digest_mismatch`) |
| Повреждённая строка или любая отвергнутая запись, кроме чужого окружения | запись пропущена, интервал сегмента в `gaps` как `corrupt_records`; положительные наблюдения из целых строк остаются |
| Запись вне интервала своего сегмента | отвергается (`outside_segment`) |
| `env` записи или сегмента другое | отвергается (`environment_mismatch`) |
| `service` записи не совпадает с emitter сегмента | отвергается (`emitter_mismatch`) |
| Превышены `max_segment_bytes`, `max_line_bytes`, `max_segments`, `max_records` | сегмент или строка пропускается с причиной, источник `PARTIAL` |

Сырые строки, пути запросов и неизвестные псевдонимы в выдачу не попадают.

### Выдача

`read_access_logs(source, start, end)` возвращает JSON-совместимый `dict`:
состояние источника, покрытие по сервисам, `gaps`, `rejected` по причинам,
`unattributed` и `observations`. Наблюдение хранит больше, чем контракт:
полные агрегаты (оценка при sampling, `client_error_count`, `latency_ms`) и ID
сегментов.

Выдача в форме agent-graph-output 2.0, каждая запись проходит валидацию моделей
`output_contracts`:

| Функция | Модель 2.0 | Содержимое |
|---|---|---|
| `evidence(observation)`, `evidence_records(result)` | `RuntimeEvidence` | `provenance=AUTHENTIC` (SHA-256 сегмента сверен), `sufficiency=OBSERVED_WITHIN_WINDOW`, `consumer`/`provider`, `window_start`/`window_end`, `method`/`route` только при наличии, `aggregates` (`requests`, `errors` если у всех записей есть `status`, `sampled`), `source_version` = digest списка сегментов, `visibility=[source.id]` |
| `relationships(result)` | `GraphRelationship` | `kind=calls`, `status` `ACTIVE` или `STALE` по свежести, `origins=[runtime]`, `change_origin=runtime_sync`, `evidence_refs` на `RuntimeEvidence` |
| `source_freshness(result)` | `SourceFreshness` | `source_kind=runtime`; `UNKNOWN` с `source_unavailable` для недоступного источника, иначе причины `partial_coverage`, `window_gap`, `sampled_source`, `age_exceeded` |
| `assess(...)` | поля `freshness_reason` (`FreshnessReason`) и `unknown` (`UnknownCode`) | соответствие ниже |

| Оценка `assess` | `FreshnessReason` | `UnknownCode` |
|---|---|---|
| `OBSERVED` | нет | нет |
| `NO_TRAFFIC_OBSERVED` | `no_traffic_in_window` | `runtime_not_observed` |
| `SAMPLED_NOT_OBSERVED` | `sampled_source` | `runtime_not_observed` |
| `WINDOW_GAP` | `window_gap` | `runtime_window_gap` |
| `SOURCE_UNAVAILABLE` | `source_unavailable` | `runtime_not_observed` |
| `CALLEE_NOT_INSTRUMENTED` | нет кода | `runtime_not_observed` (неточно) |
| `ROUTE_NOT_RECORDED` | нет кода | нет кода |
| `OTHER_ROUTE_OBSERVED` | нет кода | нет кода; у связи есть статус `CONFLICT` |

Тест `test_assessment_codes_exist_in_the_output_contract` падает, если код
из этой таблицы исчезнет из контракта.

### Чего не хватает в контракте 2.0

`output_contracts.py` принадлежит mvp-2a-core, поэтому я его не правил.
Предложения для следующей минорной версии:

1. Коды для трёх исходов `assess`: `runtime_not_instrumented`,
   `runtime_route_not_recorded`, `runtime_route_conflict` (в `UnknownCode`;
   первый и в `FreshnessReason`). Сейчас неинструментированный сервис
   выражается общим `runtime_not_observed`, а два других исхода кодом не
   выражаются вовсе.
2. Достаточность по уровню. `RuntimeEvidence` без маршрута получает
   `OBSERVED_WITHIN_WINDOW`, и `AnalysisResult.semantics` примет его как опору
   факта "Reporting вызывает GET /orders". Нужна проверка, что факт об операции
   цитирует основание с `route`, или отдельное значение достаточности для
   сервисного ребра. Это прямой риск ложной уверенности из раздела 15 SPEC.
3. `CallsiteEntity` содержит `line`, значит `entity_id` места вызова меняется
   при вставке строки выше вызова. Это расходится с моделью этого документа
   (`enclosing_symbol` + ordinal) и с требованием не терять исправления при
   несвязанной правке. Решать нужно до миграции хранилища.
4. `RuntimeAggregates` без оценки при sampling, 4xx и латентности. Адаптер
   держит их в наблюдении; для просмотра человеком и приоритизации их стоит
   добавить как необязательные поля.
5. `Gap` без интервала и сервиса: разрыв окна (`not_covered`,
   `corrupt_records`, `segment_digest_mismatch`) в `AnalysisResult.gaps`
   выражается только как `runtime_source_unavailable`, что неверно по смыслу.
   Нужен код `runtime_window_gap` в `GapCode` и поля интервала.

## Стенд

`tools/agent_service/runtime_stand/stand.py` поднимает на loopback три
HTTP-сервера на `http.server`: Orders и Inventory (оба отвечают на
`GET /orders`) и каждый пишет серверный access log в формате выше. Клиенты
Reporting и Health делают настоящие HTTP-запросы через `urllib`:

- Reporting → Orders `GET /orders` (положительный случай);
- Health → Inventory `GET /orders` (тот же path у другого сервиса);
- Export не запускается, хотя код его как потребителя Orders знает (ноль
  трафика).

После вызовов стенд закрывает сегменты и пишет `coverage.json`. Запуск:

```bash
python tools/agent_service/runtime_stand/stand.py --out /tmp/runtime-stand
```

Каталог `--out` должен быть новым и лежать вне репозитория.

Скрипт печатает сводку адаптера: ребра `reporting → orders` и
`health → inventory`, ребра `reporting → inventory` нет, оценка
`export → orders` равна `NO_TRAFFIC_OBSERVED`.

Что это доказывает: адаптер правильно читает логи, порождённые реальными
HTTP-запросами через сокеты. Что не доказывает: что логи клиента устроены так
же, что его шиппер даёт закрытые сегменты с покрытием и что идентичность
вызывающего там вообще есть. Подключение к источнику клиента не проверено.

## Проверки

```bash
PYTHONPATH=.:src python -m unittest tests.graph.test_runtime_observations -v
```

На Windows разделитель `PYTHONPATH` это `;`.

| Тест | Что проверяет |
|---|---|
| `test_zero_traffic_in_a_fully_covered_window_is_reported_but_proves_no_absence` | ноль трафика даёт `NO_TRAFFIC_OBSERVED`, `proves_absence=false` |
| `test_record_without_route_yields_a_service_edge_and_never_an_api_dependency` | без `route` только `CALLS_SERVICE`, сырой `path` не становится маршрутом |
| `test_two_services_with_the_same_path_stay_two_operations` | Orders и Inventory с `GET /orders` дают разные ID, совпадающие с `discovery.operation_id` своего сервиса; `/orders/` и `/orders` сливаются в одно наблюдение |
| `test_uncovered_part_of_window_is_a_gap_not_zero_traffic` | разрыв окна даёт `WINDOW_GAP` с точным интервалом |
| `test_unavailable_source_gives_no_observations_and_says_so` | недоступный каталог даёт `UNAVAILABLE` и `SOURCE_UNAVAILABLE` |
| `test_corrupt_line_keeps_valid_records_and_blocks_the_no_traffic_claim` | битая строка не теряет целые записи и запрещает вывод "трафика нет" |
| `test_tampered_segment_is_dropped_as_a_gap` | сегмент с чужим SHA-256 не читается |
| `test_sampled_segment_gives_an_estimate_and_never_reports_no_traffic` | sampling 0.1 даёт оценку и `SAMPLED_NOT_OBSERVED` |
| `test_untrusted_records_are_rejected_or_left_unattributed` | время без зоны, чужое окружение, чужой emitter, `..` в маршруте, неизвестный псевдоним не попадает в выдачу |
| `test_old_window_is_stale_under_the_configured_age` | свежесть по `access_log_max_age_seconds`, ID наблюдения от времени проверки не зависит |
| `test_assessment_codes_exist_in_the_output_contract` | коды `assess` есть в `FreshnessReason`/`UnknownCode` контракта |
| `test_naive_window_is_refused` | окно без зоны отвергается |
| `test_real_http_calls_produce_the_expected_directed_edges` | сквозной прогон стенда, повторное чтение даёт те же ID, `AnalysisResult` с runtime-основаниями проходит `parse_document` |

## Прогоны

2026-10-24, Windows 11 Pro 10.0.26200, Python 3.14.0, venv в worktree
(pydantic 2.14.1).

- `python -m unittest tests.graph.test_runtime_observations -v`: 12 тестов, OK.
  С `-W error::ResourceWarning` тоже OK.
- После rebase на `d8dd64a` и приведения к контракту:
  `python -m unittest tests.graph.test_runtime_observations tests.graph.test_output_contracts`
  даёт 33 теста (13 мои, 20 контрактов 2А), OK. Новые проверки тоже ловят
  поломки: код вне контракта (1 падение), потерянный `sampled` (1), связь со
  ссылкой на несуществующее основание (1), отключённая нормализация маршрута
  (1, после того как тест начал проверять слияние `/orders/` и `/orders`).
- Проверка, что тесты падают по делу: по очереди внесены четыре поломки в
  адаптер. Сырой `path` как маршрут: падают 2 теста. `assess` игнорирует
  разрывы: 3. Битая строка не снимает покрытие: 1. Окружение выпало из ID
  операции: 2. После отката снова OK.
- `ruff check --select F401,F811,F841` (правила CI) по новым файлам: чисто.
- `python tools/agent_service/runtime_stand/stand.py --out <dir>`: 7 HTTP-вызовов
  (6 по 200, 1 по 404), источник `AVAILABLE`. Ребра:
  `reporting → orders` `CALLS_OPERATION GET /orders` 3 запроса и
  `CALLS_SERVICE` 4 запроса (404 на `/missing` маршрута не имеет);
  `health → inventory` `CALLS_OPERATION GET /orders` 2 и `CALLS_SERVICE` 2.
  Ребра `reporting → inventory` нет. Один запрос без идентичности вызывающего
  попал в `unattributed`. `assess(export → orders)` равен `NO_TRAFFIC_OBSERVED`
  (`no_traffic_in_window`, `runtime_not_observed`). Стенд пишет также
  `contract.json`: 4 `RuntimeEvidence`, 4 `GraphRelationship`, `SourceFreshness`
  `CURRENT`.
- Остальные модули `tests/graph` на Windows не запускаются:
  `ModuleNotFoundError: No module named 'fcntl'` из `store.py`. Это свойство
  `main`, новые файлы его не трогают. Полный прогон `tests/graph` на Linux
  здесь не выполнялся, его делает CI (`core-tests.yml`, Python 3.12).

## Rebase на контракты 2А

Ветка перебазирована на `d8dd64a` (`feat(contracts): add versioned
agent-graph-output 2.0 contracts`). Конфликтов не было: файлы не пересекаются.
`runtime_observations.py` импортирует только `contracts` и `output_contracts`,
от `store.py` и `sources.py` не зависит, поэтому работает и на Windows.
Пока коммит 2А не слит в `main`, PR этой ветки показывает и его; сливать
нужно после PR 2А.

## Что осталось следующей волне

- Хранение: таблицы сущностей, связей, оснований и tombstone поверх `store.py`
  или рядом с ним; запись `relationships()` и `observations` адаптера.
- Инвалидация по основаниям: `dependency_key` вместо `basis` корпуса для
  исправлений и гипотез; перенос кодовых оснований по blob digest и digest
  фрагмента.
- Фильтрация доступа: скрытие оснований, счётчиков, cache, истории и подсказок
  поиска по текущему view; старый `context_id` или receipt не обходит права.
- Решение по `CallsiteEntity.line` и остальным пунктам "Чего не хватает в
  контракте 2.0" вместе с mvp-2a-core.
- Миграция: перевод ID мест вызова с `call_line` на `enclosing_symbol` и
  ordinal; перенос предложений v1 на `dependency_key` с проверкой старых
  контекстов и исправлений; прежнее хранилище не удаляется.
- Просмотр для человека: путь влияния, происхождение и свежесть с фильтром
  окружения, без CLI.
- Обновление по событию и периодическая сверка, ограниченный graph query для
  агента, источник владения (`installation_mapping` как первый).
- Живое подключение runtime-источника клиента: нужен доступ на чтение к его
  access logs или Tempo/OTel и описание, как там задаётся идентичность
  вызывающего.
