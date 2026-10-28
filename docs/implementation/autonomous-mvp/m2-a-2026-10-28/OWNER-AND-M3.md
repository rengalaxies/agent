# Единый список действий — владелец и M3

Значения секретов не отправлять в чат/PR, не печатать и не класть в Git/artifacts.
Достаточны не-секретные IDs/URL и подтверждение доверенной доставки. Сессия исполнителя
уже имеет GitHub-доступ; повторно подключать существующий agent не требуется.

| Кто | Конкретное действие | Какую проверку блокирует |
|---|---|---|
| M3 | Ответить в #71/#72 на [запрос](https://github.com/rengalaxies/agent/pull/71#issuecomment-6477834664): принять f72c018/profile5 после нового зелёного CI, сохранив release14e как старый checkpoint; новую поставку согласовать отдельно | Merge #72 / выбор кода будущей приёмки |
| Владелец GitHub | Создать **пустые private** `rengalaxies/agent-pilot-orders` и `rengalaxies/agent-pilot-reporting`, без README/license/.gitignore, платных настроек и чужого содержимого. Доступная интеграция вернула 403 create | Публикация уже подготовленных refs и реальные pilot read API |
| Владелец GitHub | Для публикации исполнителем разрешить этим двум repos доступ существующей Codex Connector installation [162282851](https://github.com/settings/installations/162282851), либо самостоятельно push готовых bundles командами ниже | Заполнение pilot без передачи PAT в чат |
| Владелец GitHub | В [New GitHub App](https://github.com/settings/apps/new) создать отдельную private App по github-app-settings.json и установить только на два pilot-repo; вернуть App ID, installation ID, реальный bot login | JWT/token exchange, App identity, права/границы установки; PAT-read это не заменяет |
| Владелец Jira | Назначить существующий Jira Cloud site и изолированный test project (предлагаемый ключ APILOT, пока не создан), bot accountId и способ выдачи API token. Новую подписку/trial не создавать этой пачкой | Jira identity, Browse/comments, реальные задачи и webhook protocol |
| Владелец → M3 | Сохранить PEM/отдельные webhook secrets и Jira API token в доверенном password manager/secret store, затем доставить на M3 по уже согласованному защищённому каналу. Не читать обратно GitHub Secrets | Credential probes и последующее подключение |
| M3/support | Завершить расследование stopped dm-p1-ui; M3 затем перепроверяет VM/FIP/host key, inventory/backup, согласует точный релиз и план установки | Установленный SHA, loaded/status, worker/restart/recovery |
| M3 + администраторы GitHub/Jira | После подтверждения HTTPS origin заполнить public base, зарегистрировать оба webhook, сохранив raw body/подписи и TLS; проверить настоящие request/delivery ID | Доставка внешних событий, self-loop/redelivery и вся LIVE M2 |

Это внешние шаги, которые невозможно выполнить имеющимися инструментами/правами;
они не заменяют уже выполненные исправления, тесты и подготовку источников.

## Заполнение repos после их создания

В checkout этого PR выполнить:

```bash
python examples/pilot_orders_reporting/prepare.py work/pilot-ready
git clone work/pilot-ready/agent-pilot-orders.bundle work/pilot-orders-push
git clone work/pilot-ready/agent-pilot-reporting.bundle work/pilot-reporting-push
```

Сверить `prepared.json` с evidence/prepared.json. Проверить через настоящий API owner,
private=true и отсутствие чужих commits в remote. Если repo уже не пустой — остановиться,
не force-push и не смешивать историю. Для свежих созданных владельцем repos:

```bash
git -C work/pilot-ready/orders remote add pilot https://github.com/rengalaxies/agent-pilot-orders.git
git -C work/pilot-ready/orders push pilot --all
git -C work/pilot-ready/reporting remote add pilot https://github.com/rengalaxies/agent-pilot-reporting.git
git -C work/pilot-ready/reporting push pilot --all
```

Пуш выполняется собственной авторизованной GitHub credential владельца/разрешённого
исполнителя, **не** private key сервисной App: ей Contents write не требуется.
GET repository/branch/blob API должен подтвердить точные SHA/bytes в evidence/prepared.json.
После изменения назначения branch или requirement обновить manifest/ожидания явно.

## App: точные параметры и почему такие права

[github-app-settings.json](github-app-settings.json) — параметры формы, **не отправленный
App manifest**. Manifest flow требует receive/redirect URL; здесь их нет, поэтому не
создаём фиктивный endpoint и обработчик обмена секретами. Имя `rengalaxies-agent-pilot`
предлагается, его глобальная доступность не проверена. Homepage — реальный agent URL;
OAuth callback/setup/device flow не нужны. Only on this account. Webhook **Active OFF**
до настоящего M3 HTTPS. Позже выбрать `pull_request`, `issue_comment`, SSL verification ON.

Минимальные repository permissions из кода:

| Permission | Реальное использование |
|---|---|
| Metadata read | repository/branch metadata, обязательное базовое право |
| Contents read | Git mirrors и pinned source/branch чтение |
| Pull requests read | fetch/list PR и события pull_request |
| Issues write | GET/POST/PATCH `/repos/{owner}/{repo}/issues/.../comments` для единственного комментария; не review comment API |

Checks, Actions, Administration, Workflows, Contents write, org/account permissions
сервису не нужны. Issue comment нужен для self-loop проверки; сервис такие события
игнорирует. Consumer repo читается, provider repo watch_prs=true. После установки
получить App metadata, installation selected-repositories и `/users/<actual-bot-login>`;
не вычислять bot numeric ID из App ID и не брать Codex Connector как bot сервиса.

## Jira: один вариант подключения без новой подписки

На существующем Jira Cloud site выделить test project/APILOT и отдельного test bot с
Browse projects, Add comments, Edit own comments и видимостью всех тестовых задач.
Право Administer Jira нужно **администратору**, регистрирующему webhook, не worker.
Создавать/изменять задачи может тестовый оператор с Create/Edit issues; worker этого
не делает и такие права не запрашиваются для него. Если существующего site нет,
сначала требуется отдельное решение владельца о Jira; trial этой пачкой не создаётся.

Базовый вариант: отдельный expiring unscoped API token тестового bot account,
**Basic email + API token**, API base `https://<подтверждённый-site>.atlassian.net`.
Права account ограничить этим проектом; срок token выбрать под приёмку, затем отозвать.
Если политика владельца требует scoped API token: тот же **Basic**, но base
`https://api.atlassian.com/ex/jira/<реальный-cloudId>` и scopes для реальных endpoint.
Scoped API token **не становится Bearer** только из-за наличия scopes.
Bearer в коде — отдельный настоящий OAuth access token с подходящими scopes, не этот вариант.
Endpoint/scopes сверить с выбранным типом токена до выдачи, не отключать auth.

На настоящем API проверить `/rest/api/3/myself` (accountId), `/project/<key>`,
`/mypermissions`, issue GET, `/search/jql`, comment list. Probe script проверяет identity,
project и базовые permissions; shipped box probes дополнительно читает branch/list PR и
Jira search. Write rights окончательно проверяет только настоящий тестовый комментарий.

Администратор позже создаёт **admin webhook с Secret**, issue created/updated/deleted
и comment created/updated/deleted, JQL `project = <реальный ключ>`, Body включено,
target `<подтверждённый HTTPS origin>/webhooks/jira`. До появления origin ничего не
регистрируем. При первой реальной доставке обязательно проверить
`X-Hub-Signature: sha256=...` и `X-Atlassian-Webhook-Identifier`.
Если выбранный webhook выдаёт JWT, unsigned body, иной HMAC algorithm или не даёт
identifier, это **PROTOCOL BLOCKED**, а не повод убрать проверку. OAuth dynamic webhooks
не считать admin webhook; availability redelivery у Jira выясняется фактически.

## Credentials: имена, место, потребитель, ротация

Текущее хранилище владельца не подтверждено. Схема доставки подготовлена, доставка NOT_RUN.
Первичный источник — выбранное владельцем доверенное хранилище; на M3 — root-only
`/etc/agent-service/secrets.env` и PEM с service-readable доступом по box runbook.

| Имя | Потребитель | Ротация/отзыв |
|---|---|---|
| GITHUB_APP_PRIVATE_KEY_PATH | GitHubAppAuth; путь к PEM, не содержимое | Выпустить новую App private key, доставить PEM, проверить token/read; удалить старый key в App и старый файл |
| GITHUB_WEBHOOK_SECRET | `/webhooks/github` HMAC | Согласованно заменить secret в App и host env, затем redeliver; старый не выводить |
| JIRA_EMAIL | Jira Basic identity | Изменять вместе с token/accountId, затем `/myself` |
| JIRA_API_TOKEN | Jira REST | Создать replacement с нужным сроком/правами, probe, затем revoke старый в Atlassian |
| JIRA_WEBHOOK_SECRET | `/webhooks/jira` HMAC | Обновить admin webhook и host env; проверить подписанную доставку |
| AGENT_SERVICE_STATUS_TOKEN | приватные `/status`, `/graph`; генерирует box | Заменить значение в root-only secrets.env, перезапустить через M3 runbook; старый токен должен получить 401 (отдельной rotate команды нет) |

Никаких MODEL_API_KEY/MODEL configuration здесь нет. GitHub Secrets read-back не нужен.
Если M3 ещё не восстановлена, секреты остаются в доверенном хранилище, не во временном
public artifact. GitHub App client secret сервису не требуется; генерировать/передавать
его ради этой проверки не нужно.

## Конфигурация/подключение и наблюдение M3

Заполнить только реальные не-секретные IDs в inputs.json; значения secrets туда не вносить.
Renderer не пишет output при missing IDs. После заполнения:

```bash
PYTHONPATH=.:src python docs/implementation/autonomous-mvp/m2-a-2026-10-28/render_config.py --inputs work/pilot-inputs.json --output work/pilot-box.yaml
PYTHONPATH=.:src python docs/implementation/autonomous-mvp/m2-a-2026-10-28/probe_connections.py --box-config work/pilot-box.yaml --output work/pilot-identity.json
```

Probe потребляет уже настроенный secret environment, не выводит его; установка сервиса
не нужна. До credentials ожидается BLOCKED, не PASS. API probes не заменяют webhook/live.
BoxConfig schema проверена, target `box plan` пока NOT_RUN. Placement/port ниже — candidate,
принадлежит M3; не применять поверх демо без её inventory/плана.

Согласованную версию/asset M3 проверяет по release runbook; новый installation
`agent-pilot-m2-live`, отдельный state. Сначала отдельная dry-run установка/probe, затем
чистое live installation/state, чтобы dry-run receipt не подменял публикацию.
Историю старой установки не удалять и параллельных workers для одного state не запускать.
Открыть только `/webhooks/github` и `/webhooks/jira`, private `/status`/`graph`/`healthz`
через доверенный доступ; Caddy/raw-body template в M2/HANDOFF-M3. TLS не ослаблять.

На M3 сохранить: `agent-service-box status --json`, `doctor`, loaded.json с process/release/core
identity, manifest code.commit/profile, journal agent-service/agent-service-sync и timer,
request/event IDs и sanitizer-reviewed state/history. `/healthz` — только живость.
`/status`/`graph` требуют bearer status token; не вставлять его в отчёт/команды с echo.

До нового release/profile5 согласования не менять существующий pin. Backup/rollback/restore
делает один исполнитель M3; SQLite restore не откатывает уже существующие внешние comments.

## Проверенные источники протоколов

- [GitHub App registration](https://docs.github.com/en/apps/creating-github-apps/registering-a-github-app/registering-a-github-app): можно отключить Active без выдуманного URL.
- [GitHub App manifest](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest): manifest flow требует webhook URL при hook_attributes.
- [Jira admin webhooks](https://developer.atlassian.com/cloud/jira/platform/webhooks/): Secret/HMAC и стабильный identifier, в отличие от иных webhook типов.
- [Atlassian API tokens](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/): Basic и gateway base для scoped API tokens.

Это проверка документации, не доказательство protocol delivery конкретного tenant.
