# Пачка 4, офлайн-часть: Jira и PR без оператора

Задача: [#52](https://github.com/rengalaxies/agent/issues/52). Сессия `mvp-4-service`, ветка
`claude/mvp-4-service-2a`, основа: ветка 2A `dde1f90`. Будущий PR идёт против
`claude/mvp-2a-core-205322`. Прежняя ветка `claude/mvp-4-service-814d77` (основа `d8dd64a`)
заменена этой и больше не обновляется.

## Состояние на 24.10.2026

| Что | Состояние |
|---|---|
| `EventEnvelope`, `PublicationIntent`, SQLite-очередь одной установки | реализовано, проверено офлайн |
| Коннектор GitHub (PR, base/head, diff, события, комментарий) | реализовано, проверено на локальном HTTP-стенде |
| Коннектор Jira Cloud (задача, события, комментарий, сверка по JQL) | реализовано, проверено на локальном HTTP-стенде |
| Publisher: один обновляемый комментарий на ресурс | реализовано, проверено на стендах |
| Анализ ядром 2A (`CoreAnalyzer`) на Git-стенде Orders/Reporting | реализовано, проверено офлайн |
| Сквозной smoke одной командой (`python -m agent_service smoke`) | реализовано, проходит |
| Модельная часть через исполнитель конституции | подключена за флагом `model_qualified`; не проверена, квалифицированной модели нет |
| Живой GitHub App и живая Jira | не проверено: нет приложения, тестового репозитория, Jira-проекта и прав публикации |
| Замеры времени и памяти на Linux | не проверено: на машине только Windows |

`python -m agent_service serve` берёт анализатор из секции `core` конфигурации. Без неё остаётся
`NotWiredAnalyzer`: каждое задание заканчивается видимым техническим отказом `analysis_not_wired`.

## Волна 2: анализ ядром 2A

`src/agent_service/core_analyzer.py` реализует протокол `Analyzer` поверх ядра:

- PR: контекст ядра на коммите base PR, затем `Graph.analyze_change` на закреплённой карте с head
  PR и сборка результата `agent_graph.results.change_result`.
- Jira: один контекст на закреплённых ветках, выбор операций из текста задачи
  (`src/agent_service/intent.py`), сборка `preliminary_result`.
- Статус и `reason_code` задаёт сборщик результатов 2A, сервис своих не добавляет. Статический
  результат по кодовым основаниям остаётся `USEFUL` (`impact_found_within_profile`,
  `preliminary_impact_found`), как определено в 2A; это предварительная классификация, а не
  подтверждённая польза. Модельных `USEFUL` нет: без квалифицированной модели модель не вызывается.
- Модель: `agent_graph.executor.run_investigation` вызывается, только если в политике ядра есть модель
  и в конфигурации сервиса стоит `core.model_qualified: true` (ставится по итогам 2Б). Гипотезы модели
  сборщик 2A оставляет гипотезами. Тест проверяет, что настроенная, но неквалифицированная модель не
  получает ни одного вызова.
- Поиск потребителей идёт через `DependencyQuery`; сейчас это `CoreDependencies` поверх
  `Graph.dependencies()`. Graph query пачки 3 заменит его в одном месте.
- Ревизии: ядро читает закреплённые коммиты из локальных Git-зеркал, указанных в его политике.
  Синхронизации зеркал с GitHub в пакете нет (пачка 3 или 5А). Если head PR в зеркале отсутствует,
  результат `FAILED commit_unavailable`, и комментарий так и говорит; другой коммит не подставляется.
- Store ядра держит соединение SQLite на поток, поэтому `Graph` создаётся лениво в потоке worker'а.

Правила выбора операций по задаче Jira:
1. Явный `METHOD /route` в тексте сопоставляется с операциями графа.
2. Если маршрут объявлен несколькими сервисами, нужен названный в тексте сервис. Иначе выбора нет и
   результат `ABSTAINED intent_unclear`: одноимённый `GET /orders` billing не принимается за Orders.
3. Путь маршрута (`/orders`) не считается упоминанием сервиса.
4. Без маршрута берутся операции названных сервисов; без упоминаний результат `intent_unclear`.

Это детерминированная основа. Квалифицированная модель позже сможет добавлять кандидатов только как
гипотезы через исполнитель конституции.

### Сквозной smoke

```bash
python -m agent_service smoke
```

Команда строит Git-стенд Orders/Reporting во временном каталоге, поднимает стенды GitHub и Jira и
приёмник webhook на 127.0.0.1, гоняет настоящий worker и ядро 2A, печатает JSON с проверками и
возвращает 0 только при успехе всех проверок. `--keep <новый каталог>` оставляет стенд и состояние.
Сценарий:

1. Jira ORD-12 создана → один комментарий: Reporting и Archive с владельцами, без audit и billing,
   `jira_without_diff`, оговорка о предварительности.
2. PR #7 открыт на head `readme-only` → один комментарий `ABSTAINED no_supported_delta`.
3. Push `unclassified`, и во время его анализа push `pr-7` с доставкой → старое поколение отменено
   (`SUPERSEDED`), результат для `unclassified` не публикуется, тот же комментарий (тот же id, один
   POST) обновлён результатом `pr-7`: base/head, `PAGE_DEFAULT_CHANGED 100 -> 20`,
   `POSSIBLE_TRUNCATION у reporting` с местом вызова `reporting:client.py:7` и требованием
   `reporting-complete`, у archive только `RECHECK_REQUIRED` (корректная пагинация), audit не
   упоминается.

Прогон на этой машине: 16 проверок из 16, около 8 с. Вывод в ASCII-JSON, чтобы установщик разобрал его при любой кодировке консоли. Установщику 5А нужен в релизе каталог
`examples/orders_reporting/` рядом с пакетом: smoke ищет `stand.py` по пути
`<корень>/examples/orders_reporting/stand.py`.

Текст выводов, проверок и утверждений приходит из ядра на английском; разделы комментария сервиса на
русском. Локализация текстов ядра в этот пакет не входит.

## Состав пакета

| Ответственность из раздела 4 задания | Файл |
|---|---|
| События и контракт публикации | `src/agent_service/envelope.py` |
| Очередь, lease, backoff, recovery, supersede, outbox | `src/agent_service/queue.py` |
| HTTP с закреплённым хостом и классификацией ошибок | `src/agent_service/http.py` |
| Подпись webhook, общие типы | `src/agent_service/connectors/base.py` |
| GitHub | `src/agent_service/connectors/github.py` |
| Jira Cloud | `src/agent_service/connectors/jira.py` |
| Тонкий адаптер к контрактам 2A | `src/agent_service/analysis.py` |
| Publisher и формат комментария | `src/agent_service/publisher.py` |
| Оркестрация receive → ingest → analyze → publish, сверка | `src/agent_service/service.py` |
| Приёмник webhook (FastAPI) | `src/agent_service/api.py` |
| Конфигурация, секреты по имени переменной окружения | `src/agent_service/config.py` |
| Анализ ядром 2A, шов для graph query пачки 3 | `src/agent_service/core_analyzer.py` |
| Выбор операций по тексту задачи Jira | `src/agent_service/intent.py` |
| Стенды GitHub и Jira (HTTP на 127.0.0.1) | `src/agent_service/stands.py` |
| Сквозной офлайн smoke | `src/agent_service/smoke.py` |
| Точка входа `serve`, `reconcile`, `status`, `smoke` | `src/agent_service/__main__.py` |
| Регрессии | `tests/service/` |

### Что переиспользовано и что нет

- Из `agent_graph_demo/store.py` взят приём работы с SQLite: отдельное соединение на операцию,
  `BEGIN IMMEDIATE`, WAL, `synchronous=FULL`, закрывающееся соединение. Сам `Store` не подходит: он
  держит одну сессию демо с ревизией, а не поколения внешних ресурсов, и не знает о внешней записи.
- Из `change_completion/workflow_store.py` взяты append-only история на триггерах и правило
  outbox "состояние SENDING после рестарта не повторяется вслепую, а сверяется". Таблицы workflow
  с ревью владельцев к сценарию не относятся.
- `agent_graph_demo/worker.py` восстанавливает задачу как `UNKNOWN_AFTER_RESTART` без повтора. Для
  автономного сервиса это неверно: прерванное задание должно продолжиться само, поэтому здесь lease
  с повторной выдачей и ограничением попыток.
- `change_completion/git_bundle.py` и `action_policy.py` не используются: чтение Git и права
  действий модели остаются в ядре 2A, сервис передаёт только закреплённые SHA.
- Второго ядра нет: сервис не извлекает зависимости и не классифицирует изменения.

## Решения по внешним API

Документация проверена 24.10.2026.

### GitHub

- Подлинность: заголовок `X-Hub-Signature-256`, HMAC-SHA256 от сырого тела с секретом webhook,
  формат `sha256=<hex>`, сравнение за постоянное время. `X-Hub-Signature` (SHA-1) не принимается.
  [Validating webhook deliveries](https://docs.github.com/en/webhooks/using-webhooks/validating-webhook-deliveries).
- Идентификатор доставки: `X-GitHub-Delivery`, тип: `X-GitHub-Event`.
- Версия REST API: `X-GitHub-Api-Version: 2022-11-28`. Это версия по умолчанию, поддержка до
  10.03.2028. Существует новая версия `2026-03-10`; переход на неё не сделан, потому что формы ответов
  проверены только для `2022-11-28`. Переход нужен до марта 2028.
  [API versions](https://docs.github.com/en/rest/about-the-rest-api/api-versions).
- Аутентификация: GitHub App, JWT RS256 → `POST /app/installations/{id}/access_tokens`. Токен
  кэшируется до двух минут до истечения.
- Чтение: `GET /repos/{o}/{r}/pulls/{n}`, `GET /repos/{o}/{r}/compare/{base}...{head}` (JSON со
  списком файлов и `application/vnd.github.diff`), `GET /repos/{o}/{r}/commits/{branch}` с
  `application/vnd.github.sha`, `GET /repos/{o}/{r}/pulls?state=open` для сверки.
- Запись только одна: комментарий PR через `POST /repos/{o}/{r}/issues/{n}/comments` и
  `PATCH /repos/{o}/{r}/issues/comments/{id}`.
  [Issue comments](https://docs.github.com/en/rest/issues/comments).
- Права приложения: Pull requests read and write (чтение PR и комментарий), Contents read (compare,
  commits), Metadata read. Права из
  [Permissions required for GitHub Apps](https://docs.github.com/en/rest/authentication/permissions-required-for-github-apps).
- Лимиты: 429 или 403 с `Retry-After` либо `x-ratelimit-remaining: 0` считаются ограничением
  частоты, а не проблемой прав.

### Jira

Подключённой Jira Data Center нет, доступа к Jira на машине нет. Поэтому выбрана Jira Cloud как
техническое предложение исполнителя, не как решение владельца. Если у компании Data Center, меняются
только подпись webhook и аутентификация; пути REST v2/v3 и модель событий сходны, вторую реализацию
заранее не делаю.

- Подлинность: webhook, зарегистрированный администратором, с секретом. Jira присылает
  `X-Hub-Signature: sha256=<hex>`, HMAC-SHA256 от тела. Проверка сверена с тестовым вектором из
  документации. Webhook OAuth 2.0 (bearer в `Authorization`) и Connect (JWT) не используются: для одной
  установки достаточно одного webhook администратора.
  [Jira Cloud webhooks](https://developer.atlassian.com/cloud/jira/platform/webhooks/).
- Идентификатор доставки: `X-Atlassian-Webhook-Identifier`, он одинаков у повторов одной доставки.
  Jira повторяет до 5 раз через 5-15 минут на 408/409/425/429/5xx; поэтому приёмник отвечает быстро и
  только записывает событие.
- REST API v3: `GET /rest/api/3/issue/{id}`, комментарии
  `GET|POST /rest/api/3/issue/{id}/comment`, `GET|PUT /rest/api/3/issue/{id}/comment/{cid}` с
  `notifyUsers=false` при обновлении.
  [Issue comments](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-comments/).
- Сверка: `GET /rest/api/3/search/jql` с `nextPageToken`; старый `GET /rest/api/3/search` помечен
  как удаляемый. Окно задаётся относительным JQL `updated >= -Nm`, чтобы не зависеть от часового
  пояса учётной записи.
  [Issue search](https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/).
- Учётная запись сервиса: отдельный пользователь с API-токеном (basic) или OAuth/scoped-токен через
  `https://api.atlassian.com/ex/jira/<cloudId>`; пути одинаковы, базовый URL задаётся в конфигурации.

### Недоверенный payload

Из webhook берутся только идентификаторы: репозиторий и номер PR, id задачи Jira, id доставки.
Все URL из payload (`url`, `diff_url`, `self` и т.п.) игнорируются. Коннектор строит путь из
проверенных сегментов к базовому URL из конфигурации, редиректы запрещены. Ресурс вне настроенных
репозиториев и проектов не читается. Сырой payload не хранится, только его SHA-256.

## Контракты

`EventEnvelope` (`agent-service-event/1`): `provider`, `source`, `event_id` (доставка),
`event_kind`, `resource_id`, `resource_version_hint`, `payload_digest`, `received_at`,
`ignored_reason`. Версия ресурса из payload только подсказка: при обработке коннектор заново читает
ресурс и берёт версию из ответа API, поэтому переставленная старая доставка не откатывает результат.

`PublicationIntent` (`agent-service-intent/1`): ресурс, поколение, версия ресурса, вид (`result`,
`stale`, `failure`), digest результата и тела, marker, comment id, состояние
`PENDING|SENDING|UNKNOWN|DELIVERED|SUPERSEDED|BLOCKED|FAILED`, попытки, `not_before`, причина.

Версия ресурса:
- PR: digest от `head_sha`, целевой ветки и явных ключей Jira в заголовке или имени ветки. Сдвиг
  базовой ветки сам по себе поколение не открывает.
- Jira: digest от настроенных смысловых полей (по умолчанию summary, description, issuetype, labels,
  components). `updated` в версию не входит: комментарий сервиса меняет `updated`, но не версию.

### Соответствие контрактам 2A (`agent-graph-output` 2.0)

- `AnalysisRequest` строится и проверяется `parse_document` из `agent_graph.output_contracts`.
  `repository_revisions` закрепляет все читаемые репозитории: для PR его репозиторий берётся по
  `head_sha`, остальные по закреплённой ветке; для Jira все по закреплённым веткам.
- `AnalysisResult` проверяется тем же модулем. Неизвестная major-версия, более новая minor, неизвестный
  код и результат другого запроса или другой версии ресурса (`result_request_mismatch`) показываются
  как несовместимость, без затронутых сервисов и путей.

Пробелы контракта 2.0, которые сервис обходит сам. Их стоит закрыть в 2A:
1. `Name` не допускает `/`, поэтому `owner/repo` GitHub отображается в имя репозитория графа через
   `repository_ids` (по умолчанию `owner.repo`).
2. В `PullRequestTrigger` нет связанных ключей Jira и списка изменённых файлов; они передаются
   анализатору в `attachments` вместе с diff.
3. `JiraTrigger.updated_at` требует `+00:00`, Jira отдаёт `+0000`; сервис нормализует.
4. Версии графа в ядре ещё нет. `CoreAnalyzer` передаёт `graph_version = view:<первые 32 знака view_id>`
   и `constitution_version` из `agent_graph.constitution.load()`; без ядра значения берутся из
   конфигурации. Настоящая версия графа появится с хранилищем пачки 3.

## Модель отказов и гарантии

Внешние API не дают exactly-once для комментариев. Сервис обеспечивает идемпотентность и сверку в
такой модели отказов: падение процесса в любой фазе, потеря ответа после записи, таймаут, 429, 5xx,
401/403, удалённый комментарий, перестановка и повтор доставки, потерянная доставка.

- Одна установка, один файл SQLite, один активный worker. Lease защищает от рестарта и случайного
  второго процесса, но не обещает горизонтального масштабирования.
- Дедупликация: `(provider, event_id)` уникален. Одинаковая версия ресурса не открывает поколение.
- Поколения: новая версия открывает поколение N+1 и в той же транзакции отзывает задания и
  неотправленные intent'ы старших поколений. Результат пишется только CAS: владелец lease и текущее
  поколение.
- Отмена во время анализа: `cancelled()` возвращает истину, если поколение сменилось или пришла
  подписанная доставка с другой версией.
- Перед отправкой publisher заново читает ресурс у провайдера. Изменился: открывается новое
  поколение, intent отзывается. После записи ресурс читается ещё раз; если head сдвинулся во время
  отправки, открывается новое поколение, и комментарий сначала заменяется уведомлением "Предыдущий
  вывод устарел", затем новым результатом.
- Перед любой внешней записью intent переводится в `SENDING`. После рестарта такой intent становится
  `UNKNOWN`, и до create выполняется поиск комментария по marker и автору (`bot_login` GitHub,
  `accountId` Jira). Комментарий с тем же marker от другого автора не принимается за свой. Если digest
  найденного совпадает, запись не повторяется.
- Узкое место: если create прошёл, а список комментариев у провайдера ещё не показывает его, возможен
  второй комментарий. Для этого есть пауза `create_settle_seconds` (30 с по умолчанию) перед create
  после неясного create. Это снижает, но не исключает риск; живыми замерами не подтверждено.
- Повторы ограничены: анализ 4 попытки, публикация 6, backoff от 5 с до 15 минут, `Retry-After`
  до часа. Исчерпанные временные отказы ждут следующей сверки (по умолчанию раз в 15 минут), которая
  даёт ещё один ограниченный круг.
- 401/403: intent `BLOCKED`, повтор через 15 минут без расхода попыток, одна запись `notices` со
  счётчиком. Запись снимается после первого успешного обращения. Состояние видно в `GET /status`.
- Удалённый комментарий: при следующей публикации создаётся новый, ровно один.
- Повторный одинаковый отказ анализа даёт тот же digest тела, поэтому комментарий не переписывается.
- Собственный комментарий: события `comment_*` Jira и `issue_comment` GitHub не запускают анализ;
  `jira:issue_updated` без смысловых полей в changelog отбрасывается; если такое событие всё же прошло,
  перечитанная версия совпадает и событие объединяется.
- Источники только читаются. Единственная запись: комментарий в настроенный PR или задачу.

## Формат комментария

Один комментарий на ресурс, разделы по порядку: "Что может затронуть" → "Почему и через какой путь"
→ "Что проверить" → "Неизвестные и свежесть" → "Версии". В "Почему" каждое утверждение помечено как
факт в пределах профиля или гипотеза, с применимостью, неопределённостью и типом основания (код,
наблюдаемые вызовы, гипотеза модели, исправление, внешняя проверка). Неизвестный владелец выводится
как "команда не определена", спорный показывает всех кандидатов. Для Jira добавляется оговорка, что
вывод предварительный и не доказывает поломку. Текст из результата анализа считается недоверенным:
в GitHub экранируются упоминания, ссылки, картинки и HTML, URL выводятся как код; в Jira используются
только текстовые узлы ADF. В конце скрытый (GitHub) или моноширинный (Jira) marker с digest и
поколением.

## Однократное подключение

Все секреты передаются через переменные окружения; в файле конфигурации только их имена.

### GitHub App

1. Создать GitHub App в организации: Settings → Developer settings → GitHub Apps → New GitHub App.
2. Webhook URL: `https://<адрес сервиса>/webhooks/github`, сгенерировать секрет.
3. Права: Pull requests read and write, Contents read, Metadata read. События: Pull request.
4. Сгенерировать private key, сохранить PEM на машине сервиса с правами только для пользователя сервиса.
5. Установить приложение только на нужные репозитории и записать installation id.
6. `bot_login` равен `<slug приложения>[bot]`.

### Jira Cloud

1. Завести отдельного пользователя сервиса с правами Browse projects, Add comments и Edit own
   comments в нужных проектах; выпустить для него API-токен; записать его `accountId`.
2. Администратор Jira: System → WebHooks → Create. URL `https://<адрес сервиса>/webhooks/jira`,
   секрет, события Issue created и Issue updated, фильтр JQL `project in (ORD)`. События комментариев
   не включать.

### Конфигурация и запуск

```yaml
installation_id: acme
environment: prod
state_path: /var/lib/agent-service/service.sqlite
publication: dry_run        # после проверки переключить на live
github:
  repositories: [acme/orders]
  read_repositories: {acme/orders: main, acme/reporting: main}
  repository_ids: {acme/orders: orders, acme/reporting: reporting}
  bot_login: acme-impact[bot]
  webhook_secret_env: GITHUB_WEBHOOK_SECRET
  auth: {kind: app, app_id: "123456", installation_id: 7890, private_key_path_env: GITHUB_APP_KEY_PATH}
jira:
  base_url: https://acme.atlassian.net
  project_keys: [ORD]
  bot_account_id: 5b10ac8d82e05b22cc7d4ef5
  webhook_secret_env: JIRA_WEBHOOK_SECRET
  auth: {kind: basic, email_env: JIRA_EMAIL, token_env: JIRA_API_TOKEN}
analysis: {graph_version: graph-not-wired, constitution_version: agent-service-v1}
```

```bash
python -m agent_service serve --config service.yaml --host 0.0.0.0 --port 8090
```

TLS терминируется перед сервисом (обратный прокси); установщик, readiness и doctor входят в пачку 5А.
`GET /status` с `Authorization: Bearer $AGENT_SERVICE_STATUS_TOKEN` показывает состояния очереди и
проблемы подключения без секретов. `GET /healthz` означает только, что процесс жив.

## Проверки

Окружение: Windows 11, Python 3.14.0, venv в worktree, `pip install -e '.[api,test-api,distributed]'`
(pydantic 2.14.1, fastapi 0.162.0, uvicorn 0.54.0, cryptography 46.0.7).

| Команда | Результат |
|---|---|
| `PYTHONPATH=".;src" python -m unittest discover -s tests/service -t .` | 65 тестов, OK, около 76 с |
| `python -m agent_service smoke` | 16 из 16 проверок, exit 0, около 8 с |
| `PYTHONPATH=".;src" python -m unittest tests.graph.test_results tests.graph.test_output_contracts` | OK |
| `python -m ruff check src/agent_service tests/service --select F` | без замечаний |
| `PYTHONPATH=".;src;tests;tools" python -m unittest discover -s tests` | см. ниже |

Полный набор на Windows: на ветке 615 тестов, failures=35, errors=120. На основе 2A `dde1f90` тем
же venv: 550 тестов, failures=35, errors=120, и список упавших тестов совпадает построчно. Разница в
65 тестов, это `tests/service`, все проходят. Падения основы на Windows связаны по заметкам соседних
сессий с `fcntl`, `O_DIRECTORY`, symlink и CRLF в фикстурах. Решающим остаётся Linux CI.

Тесты `tests/service` работают с настоящими HTTP-запросами: стенды GitHub и Jira на 127.0.0.1
отвечают по документированным путям и заголовкам, приёмник webhook поднят через uvicorn на случайном
порту. В тестах очереди и отказов заменены часы (lease и backoff) и анализатор; в `test_core` и
smoke работает настоящее ядро 2A на Git-стенде. Что покрыто:

- Ядро на стенде (`test_core`): smoke целиком; Jira без требования полноты пишет
  `requirement_unknown (reporting)` и не заявляет поломку; задача с одним `GET /orders` без имени
  сервиса даёт `intent_unclear`, а не потребителей billing; head, которого нет в зеркале, даёт видимый
  `commit_unavailable`; настроенная неквалифицированная модель не получает вызовов; правила выбора
  операций по тексту.

- Jira без PR даёт предварительный комментарий; PR уточняет его и показывает base/head, diff и
  ссылку на ключ Jira (`test_flow`).
- Повтор и перестановка доставки дают одно поколение и один комментарий; неверная подпись
  отвергается; URL из payload не запрашиваются; чужой репозиторий не читается (`test_delivery`).
- Новый head во время анализа (с доставкой и без неё) не публикуется; новый head во время отправки
  заменяется уведомлением об устаревании и новым результатом; закрытый PR отзывает публикацию
  (`test_races`).
- Рестарт после приёма, claim, анализа, claim intent, записи `SENDING`, внешней записи и потеря ответа
  после записи в GitHub и Jira: задание не теряется, create выполняется один раз (`test_restart`).
- 429 с `Retry-After`, вторичный лимит 403, бесконечный 429 и 5xx ограничены; 403 виден как проблема
  подключения; отозванный токен на чтении; удалённый комментарий; чужой комментарий с нашим marker;
  отказ анализа без потока одинаковых записей; несовместимая версия, неизвестный код, результат
  другой версии; недоверенный текст (`test_errors`).
- Сверка находит пропущенный PR, пропущенный push, закрытый PR и обновлённую задачу; сбой сверки не
  двигает checkpoint (`test_reconcile`).
- Lease и CAS очереди, отзыв поколения, ограничение попыток, append-only история (`test_queue`).
- Обмен JWT GitHub App на токен установки, неверный ключ, секреты по имени, dry-run без записи к
  провайдеру, доступ к `/status` (`test_connection`).

Каждый ключевой тест проверен на способность упасть: при отключённом поиске по marker падают 4 теста
рестарта, без проверки свежести перед отправкой падают 2 теста гонок, без фильтра событий комментариев
и с `updated` в версии Jira падают 2 теста цикла, без правила неоднозначного маршрута падают 3 теста
выбора операций.

## Не проверено

- Живые GitHub и Jira: нет GitHub App, тестового репозитория, тестового Jira-проекта, учётной записи
  сервиса и разрешения на комментарии. Ссылок на живые комментарии нет.
- Анализ ядром проверен только на синтетическом стенде Orders/Reporting, не на репозиториях компании.
  Тесты транспорта и отказов (`test_flow`, `test_errors` и другие) по-прежнему используют
  анализатор-заглушку с валидным `AnalysisResult` 2.0, чтобы проверять очередь отдельно от ядра.
- Модельная часть: квалифицированной модели нет, путь `run_investigation` в сервисе не запускался.
- Синхронизация локальных Git-зеркал с GitHub (fetch head PR) не реализована.
- Задержка списка комментариев у провайдеров после create и поведение при ней.
- Jira Data Center.
- Linux: время обработки события, память, поведение SQLite на целевом диске.

## Что нужно от владельца для живой приёмки

1. Тестовый репозиторий GitHub и право создать в организации GitHub App с правами выше.
2. Тестовый проект Jira Cloud (или сведения, что используется Data Center), учётная запись сервиса и
   API-токен, право администратора создать webhook.
3. Публичный HTTPS-адрес для webhook (ВМ пачки 5А или временный туннель).
4. Разрешение публиковать комментарии в этих тестовых PR и задачах.

## Следующий шаг

1. Когда пачка 3 пришлёт SHA graph query: заменить `CoreDependencies` и брать `graph_version` из
   хранилища графа вместо `view:<digest>`.
2. Синхронизация Git-зеркал с GitHub перед анализом (пачка 3 или 5А).
3. Живой smoke в тестовом контуре: одна задача Jira, один PR, корреляция событий и итоговое число
   комментариев.
