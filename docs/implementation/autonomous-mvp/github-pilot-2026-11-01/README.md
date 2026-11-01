# GitHub pilot preparation — 01.11.2026

Исходный main `837f8565b626e1b73a07cff8d99f850581d22a48`. Отдельная GitHub-пачка;
не deployment evidence M3. MODEL OFF. Pilot repositories не изменялись.

| Проверка | Уровень / auth | Результат |
|---|---|---|
| Repo IDs 1437522215 / 1437522551, private=true | REAL API / Codex Connector | PASS |
| 6 refs и 6 main-file SHA256 против prepared.json | REAL API / Connector | PASS |
| Bot rengalaxies-agent-pilot[bot], ID349497413, type Bot | REAL API / Connector | PASS |
| Списки всех PR обоих repos | REAL API / Connector | PASS, оба пусты |
| Environment agent-pilot-app | REAL GitHub admin metadata | отсутствует: list200 total5, detail404 |
| Environment secret AGENT_PILOT_APP_PRIVATE_KEY | REAL metadata | environment отсутствует; значения не читались |
| Repository-level secret metadata | API | недоступны; отсутствие PEM из этого не выводится |
| App5515659 / installation176298402 | Config + ранее owner UI | CONFIGURED, App API NOT_RUN |
| JWT→installation token, permissions и scope от имени App | REAL App API | BLOCKED / NOT_RUN |
| Wrong installation / foreign repo refusal | LOCAL scripted probe regression | PASS, не LIVE |
| Existing auth + preparation + probe tests | LOCAL | 12 PASS |
| Runtime Orders→Reporting (100→20→100 + explicit limit) | LOCAL real loopback HTTP | PASS, авторский fixture |
| M3, external Jira→PR→comment, webhook delivery | LIVE | NOT_RUN |

[Connector reads](evidence/connector-reads.json), [remote bytes](evidence/source-bytes.json),
[environment proof](evidence/environment.json), [LOCAL runtime](evidence/runtime.json).

## Исправленные дефекты

[RED](evidence/red.log): три регрессии воспроизвели прежний PASS при другом installation.id,
продолжение repo reads после неправильного installation scope и отсутствие PR reads.
Теперь probe сверяет installation.id, прекращает чтения при неверной App/installation/scope,
отзывает уже полученный token и читает refs + PR endpoint обоих разрешённых repos.
[GREEN](evidence/green.log) — 12 tests, включая существующий RSA/JWT token transport.
Новые boundary tests используют scripted HTTP responses; они не подтверждают настоящий App key.
Service queue/connectors/auth не переписывались. Негативные App API вызовы NOT_RUN.

## Защита секретов и запуск

Действующий workflow `.github/workflows/agent-pilot-app-probe.yml` (#74): manual/main-only,
exact expected_main_sha, attempt1, environment agent-pilot-app, contents:read.
PEM передаётся через environment secret, пишется под umask077 в RUNNER_TEMP, не в checkout;
добавлен EXIT trap удаления при неуспехе. JWT создаётся внутри Python; headers, token body,
PEM и exception details не печатаются. Artifact whitelist — только work/app-identity.json,
где IDs, permissions, refs/PR metadata, request IDs и безопасные reason codes; revoke проверяется.
Публикаций, DB, webhook registration и LLM вызовов probe не делает. Чтение permissions
не доказывает успешную запись комментария; это остаётся для согласованной LIVE-приёмки.

Probe НЕ dispatched: environment отсутствует; GitHub мог бы создать его автоматически
без требуемых reviewer/main-only rules. Секреты не создавались, не менялись и не извлекались.
Обязательная защита до dispatch: required reviewer, main-only deployment branch policy,
доверенный PEM только как AGENT_PILOT_APP_PRIVATE_KEY. Состояние/значение PEM не предполагается.
После принятия исправления указать полный актуальный main SHA, не использовать rerun.

Сохранённые материалы m2-a-2026-10-28 содержат исторические ссылки на несогласованный #72
и отсутствие выпуска. Они не определяют нынешнюю поставку: #81–84 приняты, release234
проверен отдельно. Здесь deployment pin и установленная конфигурация не менялись.
[Короткий актуальный handoff](HANDOFF.md).
