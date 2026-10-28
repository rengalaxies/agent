# M4-A integration + M2-A external contour preparation — 28.10.2026

**PARTIAL / LIVE BLOCKED. MODEL OFF.** Ни сервис, ни Jira, ни собственная GitHub App
не подключены этой пачкой. Основной `rengalaxies/agent` остаётся репозиторием разработки.
Ни одной тестовой задачи, PR или bot comment во внешних системах здесь не создано.

## A. Интеграционное решение

Main при начале проверки: `d5e25fde5927eca99e574b2ac82be80cd5adfe16`.
M3 #71: `5ac9dbb291e9784f02fb4ccc266f459bdca52c0b`, draft, HOST STOPPED / SUPPORT
INVESTIGATION по сообщению владельца. Мы не делали Cloud.ru/SSH/VM/network/recovery вызовов.

Предметное ревью #72 на `214bec72ccb6df59a29e8d1069eca91202cf5c1e` подтвердило основные
исправления scope/router/unknown и обнаружило 3 дополнительных пробела. Они воспроизведены
до исправления: глагол редактирования README, legacy knowledge без config digest,
persistent graph code bases до profile rebuild. Исправления отправлены в тот же #72:
**`f72c01827f203c2df46df9dc8e9071673df430e0`**. 32 targeted и 883 full LOCAL PASS.
[Ревью, RED/GREEN, профиль/история и ограничения](https://github.com/rengalaxies/agent/blob/f72c01827f203c2df46df9dc8e9071673df430e0/docs/implementation/autonomous-mvp/m4-a-2026-10-28/integration-review/README.md).

Profile остаётся `http-requests-5`; positive grammar сужена, wrappers не поддержаны
как достоверная зависимость. Старые contexts/knowledge/code bases становятся STALE;
sync пересчитывает основания с сохранением истории. Legacy/SQLite/public schemas не менялись.
**Смена профиля не переиздаёт автоматически внешние комментарии неизменных ресурсов**:
это ограничение очереди явно сохранено, очередь/коннекторы в этой пачке не менялись.

С #71 нет пересечений файлов #72; `git merge-tree --write-tree` на f72c018 и 5ac9dbb
прошёл, виртуальное дерево `d399f4c65feee879991c39caedec3d0a55b58b40`.
[Явный запрос согласования M3](https://github.com/rengalaxies/agent/pull/71#issuecomment-6477834664)
содержит новые heads/scope и решение о версии. **Ack не получен: #72 не слит**, auto-merge
не включался. Отсутствие конфликтов и зелёный CI не считаются согласованием.
Новый CI/актуальный gate записывается в [integration.json](integration.json).

Подготовленный M3 release — `14e65e8affe3b64a9ceb647f537e8af6ff7a1138`, profile 4;
он не содержит #72. Pin/installer/release/ВМ не менялись. После ack и merge нужен
**отдельно согласованный** release на полном merge SHA: штатный release workflow,
проверка двух сборок, опубликованного asset/manifest и install-published, затем PR pin
и план M3. Старый tag не заменять. Никакого автоматического обновления установленной
или подготовленной M3 этим PR нет.

## B. Фактический внешний доступ

[Санитизированные ответы настоящего GitHub API](evidence/github-api-inventory.json):
GET `/user` подтверждает rengalaxies / `297624087`, development main читается.
Доступная gh credential обслуживается интеграцией; её значение/формат не исследовались.
Это **не подтверждение PAT и не проверка App installation нашего сервиса**.
GET `/user/installations` видит только ChatGPT Codex Connector App `1144995`,
installation `162282851`. Это перечень видимых credential установок, не полный
перечень всех зарегистрированных владельцем Apps. Эту стороннюю App не используем.

Оба целевых repository GET вернули 404 (отсутствие и скрытый доступ этим не различаются); назначения существующих приватных repos не
подтверждены, они не использовались. Разрешённый POST `/user/repos` для
`agent-pilot-orders` вернул **403 Resource not accessible by integration**. Создание
не состоялось; второй POST не повторял заведомо недоступную операцию. Connector не
предлагает create-repository/App-registration, браузерной сессии нет. Поэтому точные
remote repository IDs, service App/installation/bot IDs остаются null.

Инструментов Jira и настроенных runtime secret bindings нет; site/project не назначены.
Нет основания обращаться к случайному Jira tenant или создавать новый тариф/trial.
Реальные Jira read/write/webhook проверки NOT_RUN. Официальные admin webhooks
поддерживают secret/HMAC и identifier; фактическую выбранную Jira-доставку ещё надо
проверить. OAuth dynamic/Connect JWT не подменяют нужный протокол.

## Что уже выполнено независимо от доступа

- [Минимальные приложения и генератор](../../../../examples/pilot_orders_reporting/prepare.py)
  создают два локальных Git repository и bundles. Две независимые сборки побайтно
  совпали; фиксированные SHA/digests в [prepared.json](evidence/prepared.json).
  Ветка `pilot-page-limit` и её descendant `pilot-restored` позволяют обновить один PR
  обычным fast-forward 100 → 20 → 100. `pilot-docs-only` — отрицательный контроль;
  Reporting `pilot-explicit-limit` — дополнительный consumer repair control.
- Исполнены настоящие FastAPI/uvicorn и requests через loopback HTTP, без shim:
  **60 → 20 → 60**, docs-only 60. [Результат LOCAL](evidence/runtime-local.json).
  Окружение отдельно от зависимостей продукта: Python 3.12, fastapi 0.135.1,
  uvicorn 0.41.0, requests 2.32.5. Это авторские данные, не независимый проект.
- [Три проверки подготовки](evidence/preparation-tests.log): повторяемость Git bundles,
  реальный статический Graph на pin/base/head и schema/fail-closed config.
  Зависимость обнаружена без требования; затем requirement включён с digest явного
  тестового условия. Limit даёт POSSIBLE_TRUNCATION / test_executed=false; restored/docs
  не дают deltas/findings. Expected IDs не передаются анализатору как consumer map.
- [box.partial.yaml](box.partial.yaml), [inputs.json](inputs.json),
  [render_config.py](render_config.py) проверяют реальную BoxConfig schema.
  На неполных inputs renderer отклоняет материализацию; installable config **нет**.
  Surrogate IDs используются только в schema test, никогда в сохранённой конфигурации.
  `.invalid` — символический address fixture, не внешний endpoint, DNS или webhook.
- [Параметры App](github-app-settings.json), [webhook protocol/routes](webhooks.json),
  [credentials/owner инструкция](OWNER-AND-M3.md), [LIVE/cleanup](LIVE.md),
  [проверка реальной identity](probe_connections.py) подготовлены. Последняя не запускалась
  с credentials, пишет только выбранные metadata/request ID, не открывает state БД.

[Реестр состояния](registry.json) отличает requested/prepared, REAL_API и connected.
CI этой отдельной ветки указывается в PR; он не является LIVE.

## Границы и оставшийся шаг

Единый список владельца/M3 — [OWNER-AND-M3.md](OWNER-AND-M3.md). Интеграция #72 ждёт
явного ack, создание repos — owner-only UI/credential capability, Jira — выбор
существующего проекта/доставка секретов. Восстановление хоста принадлежит M3/support.
MODEL OFF; M2 не DONE, вся M4/клиентская полезность UNVERIFIED. Исторические
2b-r1/6-r1..6-r3, их manifest/corpus/results не менялись. Человеческие минуты не измерялись.

Ручные действия исполнителя: чтение/ревью кода/PR, воспроизведение ошибок и правки,
локальные тесты/HTTP, API inventory/отказ create, публикация координационных PR comments,
подготовка Git bundles/config/runbook. Действий человека в LIVE контуре не было.
