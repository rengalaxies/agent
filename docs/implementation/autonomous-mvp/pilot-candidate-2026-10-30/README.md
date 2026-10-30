# Кандидат пилота: анализ, переход состояния и согласование

30.10.2026. База этапа: main **e84e91395a8846e2f43df3a1a6e402e3487e7a27**.
Ветка самостоятельных исправлений: `codex/pilot-candidate-evidence-2026-10-30`.
Объединённая ветка: `codex/pilot-profile6-candidate-2026-10-30`, **PENDING_APPROVAL**.
Точные окончательные heads, Checks и состояние интеграции закреплены в собственных PR.
MODEL OFF; участник/клиентский корпус/целевая ВМ/внешние интеграции NOT_RUN.

## Состав и граница интеграции

Main включает #78 и #79. #72 проверена на точном head
`f25e82f9a83f4e15bdfeb16088fdf1fc6d335bee`; #71 — `5ac9dbb291e9784f02fb4ccc266f459bdca52c0b`.
В [комментариях #71](https://github.com/rengalaxies/agent/pull/71#issuecomment-6502473730)
и [#72](https://github.com/rengalaxies/agent/pull/72#issuecomment-6477837535)
найдены запросы согласования, **явного M3 ack нет**. Не считать запрос, старый green
или отсутствие ответа согласием. Чужие refs не менялись; merge/auto-merge #71/#72 не выполнялись.

Две самостоятельные проблемы исправлены без переноса #72: сохранённый demo graph/knowledge
после смены профиля больше не представлен CURRENT; недоступность code source передаётся
в уже существующий reconciliation gate. Также PARTIAL требует восстановления/разбора
источников вместо подсказки «показ завершён». Эти изменения могут интегрироваться отдельно.
В локальном объединении #72 добавлено сужение AST-доказательств для явного setattr/delattr;
профиль повышен до **http-requests-6**, чтобы и промежуточные profile5 основания стали STALE.
Это изменение не переносится в main до согласования вместе с #72.

## Пять сохранённых DEFERRED_72

Повтор именно сохранённого verifier `tests.graph.pilot_boundaries` на актуальном main,
затем на точном объединении. [Main](evidence/main-boundaries.json),
[кандидат](evidence/profile6-boundaries.json). Контроль mixed-negation проходит в обоих.

| Случай | Ожидание | Main e84e913 | Причина | Решение #72 | Кандидат |
|---|---|---|---|---|---|
| documentation | только README: ни одной операции | GET+POST выбраны | route mention принимался за изменение | intent._documentation_only и локальные clauses | PASS: [] |
| scope | GET двух сервисов не угадывать по другому POST | оба warehouse метода | общий service scope переносился между clauses | _route_clauses/local/context_services, ambiguous_route | PASS: [] |
| old_pinned_profile | старый context STALE при тех же Git SHA | CURRENT | pinned fast path обходил profile check | Graph.freshness проверяет profile до pinned_freshness | PASS: STALE |
| old_knowledge_profile | прежний proposal STALE, ID/история сохраняются | CURRENT | sufficiency config не включал профиль | config_digest/holds и legacy cited_profile | PASS: STALE |
| rebound_factory | Plain decorator не объявляет HTTP API | /ghost объявлен | app/factory не проверялись на повторные binding | providers/bindings; unsupported gap вместо удаления API | PASS: [] / PARTIAL |

Это решения **в кандидате**, не доказательство, что пять ошибок уже исправлены в main.
Persistent code bases дополнительно получают профиль и меняют identity; GraphQuery
возвращает STALE до sync. Legacy knowledge без config digest требует профиль исходного
контекста; неизвестный исходный профиль не становится CURRENT. Публичные result и SQLite
schemas не изменены. Исторические корпуса и manifests 2b-r1/6-r1..6-r3 не менялись.

## Новые воспроизведения и минимальные исправления

1. **Demo API:** реальное CLI обследование и human proposal; новая API-версия поверх
   сохранённого результата возвращала CURRENT. [RED](evidence/ui-profile-before.log),
   [GREEN с API-контролями](evidence/ui-profile-after.log). Теперь read сравнивает profile,
   proposal status/freshness согласованы, UI объясняет причину, новая correction запрещена.
   Исходный artifact не переписан, его ID и idempotent replay ранее принятого job сохранены.
2. **Явная мутация декоратора:** `setattr(api, "get", lambda ... )` снимает реальную
   регистрацию маршрута, а profile4 и #72/profile5 объявляли его. [RED](evidence/mutation-before.log),
   [GREEN/контроли](evidence/mutation-after.log). `bindings` учитывает прямые setattr/delattr
   над именованным объектом так же консервативно, как `api.get = ...`. Мутация другого
   объекта не убирает корректные GET/POST. Alias/dataflow, wrappers и APIRouter не расширены.
3. **Code source/reconciliation:** GraphStore уже помечал missing Git repository UNAVAILABLE,
   но GraphMaintainer терял этот статус: новый basis checkpoint принимался и открывались
   два job при отсутствующем источнике. [RED](evidence/source-upgrade-before.log),
   [GREEN + #78 controls](evidence/source-upgrade-after.log). Передаётся существующий
   UNAVAILABLE_GAPS; checkpoint не двигается, notice видим. После возврата источника
   пересчитываются прежние ресурсы/комментарии. UNKNOWN-вызов даёт PARTIAL, но status OK:
   неподдерживаемая грамматика не означает недоступный репозиторий.
4. **PARTIAL UX:** настоящий browser capture показал «показ завершён» при PARTIAL.
   [До](evidence/screenshots/before-partial-next-action.png). Следующий шаг теперь просит
   изучить gaps/восстановить источник; отдельная browser assertion требует этот текст.
   Финальное подтверждение этой последней правки — HTTP CI окончательного head.

Ни очередь, ни коннекторы, ни installer не переписаны. New status делает существующую
проверку box task_graph также видеть failure; целевую установку это не подтверждает.

## Новый авторский корпус

Ожидания записаны до Graph: [JSON](evidence/new-expectations-before.json).
Факты: [main](evidence/main-new-cases.json), [#72/profile5](evidence/profile5-new-cases.json),
[profile6](evidence/profile6-new-cases.json). Это дополнительные авторские случаи после
изучения реализации; не слепой held-out и не независимый человеческий benchmark.
Policy получает только sources/addresses, не expected consumer map.

| Комбинация | Независимое основание/наблюдение | Что установлено |
|---|---|---|
| GET/POST template /records/{record_id}, два service prefix | реальный FastAPI/requests, method/path/address/port/status/body | display→catalog GET, submit→catalog POST, admin_display→admin GET |
| schema change state string→int при том же handler | реальный ответ меняется open→42, POST/admin стабильны | unclassified static recheck; только runtime oracle наблюдает нарушение авторского условия |
| Нет approved requirement в Policy | requirements=[], все findings test_executed=false/compatibility_confirmed=false | анализатор не доказал нарушение требования; внешний авторский oracle — другой уровень |
| Неверный prefix/DELETE | HTTP 404/405 | запрос был, но положительной связи с объявленной операцией нет |
| Dynamic wrapper с тем же ответом | реально делает GET и получает open→42 | static edge отсутствует; известный пропуск и unsupported abstention, не безопасность |
| README GET рядом с API POST; отрицание GET+изменение POST | фиксированные clauses и named service | main FAIL, #72/6 PASS: только POST |
| GET с тем же template без service | два возможных поставщика | честное воздержание |
| setattr и похожий «декоратор» | исполнение Python/FastAPI регистрирует ноль соответствующих routes | main/#72 FP, profile6 PARTIAL/нет доказанного удаления |

Структурный знаменатель: **4 известных успешных runtime callers**, из них 3 в профиле,
1 wrapper вне профиля. Profile6: edge FP=0, supported FN=0, все runtime FN=1,
unsupported abstentions=1 (эта единица одновременно FN, не другой знаменатель).
Отдельный отрицательный provider case: FP=1 до исправления, 0 после. Не складывать
provider FP с caller FP и не вычислять «качество на неизвестном проекте» из этого корпуса.
Runtime этапы имеют разные ephemeral ports; статический корпус использует первый
явно сконфигурированный origin. Настоящие ports записаны, постоянный адрес не выдуман.
Проверки port controls, caller add/remove, citations/access/revocation и несовместимого
результата не копировались из #79/#72: их существующие регрессии повторяются в full CI.

## Переход настоящего старого состояния

[LOCAL-MIGRATION.json](evidence/LOCAL-MIGRATION.json) создан разными процессами:
старый **e84e913**, новый **99ce1f0ecd39c838b0a8613d64311655c743321f** (profile6).
PROFILE не monkeypatch; одинаковые SQLite/core state и настоящие loopback HTTP stands.

- Старые pinned contexts, code bases, modern и schema-1 knowledge проверены до sync.
  Новым кодом старые основания STALE, proposal IDs не удалены.
- Недоступный Git source даёт PARTIAL; новая основа не принимается, reanalysed=0.
- После восстановления source открываются 3 resource generations. Процесс остановлен
  после durable ANALYZED+publication intent до отправки, затем запущен другим процессом.
- Во время паузы меняется head PR. Подписанное новое событие поступает до resume:
  старый неподтверждённый результат не становится текущим, итог содержит новый head.
- IDs комментариев **1001, 1002, 5001** сохраняются во всех фазах; история монотонно растёт.
- Существующий механизм #76 + #78 действительно обновляет unchanged Jira/PR при смене
  basis; прежнее ограничение исторического отчёта #72 уже не описывает сегодняшний main.
- Откат кодом e84e913 и повторное обновление проверены. Старый код до reconciliation
  ошибочно считает и более новый pinned context CURRENT: это свойство старого кода,
  не безопасный API для работы между switch и rebuild. Публикацию следует держать
  остановленной до graph/reconciliation/loaded-identity проверки. Старый release14e
  этим не проверен; нужен его matching backup и целевая приёмка M3.

Атомарности БД↔API нет. Во время остановки/отсутствия источника старое тело комментария
может сохраняться до durable notice и нового result. После возврата sources/worker
проверено eventual обновление; верхней границы outage/stale window и LIVE-длительности нет.

## UI, сборка и уровни доказательств

[LOCAL UI](evidence/LOCAL-UI.json): настоящий CLI/backend/Docker/Chromium на
**d66e4a6aeb5e19e4be510f8f4ae4f4d374a76a5f**, A/B/D/E PASS (B ожидаемый runtime FAIL),
пять показов, zero sandbox. [E](evidence/screenshots/desktop-E.png),
[старый профиль](evidence/screenshots/profile-stale.png). Последний PARTIAL hint изменён
после этого прогона, его проверяет финальный CI. Profile/PARTIAL UI probes явно используют
авторские persisted-graph fixtures через настоящий API, не выдаются за новый discovery.
Недоступный source и реальная миграция отдельно подтверждены описанным выше core harness.

Сервисный payload зафиксирован **99ce1f0e…**. Две сборки побайтно одинаковы;
[build](evidence/candidate-build.json), [verify](evidence/verify-source.json),
[manifest](evidence/agent-service-0.1.0-g99ce1f0ecd39-linux-x86_64-cp312.manifest.json),
[checksum](evidence/agent-service-0.1.0-g99ce1f0ecd39-linux-x86_64-cp312.tar.gz.sha256).
Archive SHA256 **64955e17e68b0e94e37f31c312f3dc1aba84c3c52e57d5a3d921854717b73f8b**,
manifest **7f00a2aa0ec39735fbbd2985f723688e8dc2c8d845f6fe8c34dbc168df1830c7**.
Это **неопубликованная проверенная сборка PENDING_APPROVAL**, не принятый релиз.
Agent-service archive по существующему allowlist не включает demo UI. Локальный показ
собирается отдельным существующим Dockerfile из того же checkout; это два артефакта.
Final CI отдельно собирает точный head дважды и проверяет manifest; его SHA/артефакты
связаны в PR. Текущий pin/release14e не менялись. [Handoff M3](HANDOFF-M3.md).

LOCAL full suite сперва FAIL из-за неверного PYTHONPATH без tools (run_pr_assistant
не импортировался), не продуктовая ошибка. Команда повторена с точным CI PYTHONPATH.
Повторный полный LOCAL suite **917 tests PASS**, runner **152 PASS** на service/core
99ce1f0e (UI-only hint позже). [Full log](evidence/full-local.log),
[runner log](evidence/runner-local.log). Итоговые Checks точного final head — в PR;
предыдущий green не засчитывается окончательному head.
Исторические expectation/results не переписывались. Whole diff --check к main
указывает две унаследованные trailing-whitespace строки старых logs #72; новый diff
проверен отдельно к обоим родителям, эти исторические logs сохранены. Ранний migration harness FAIL
reanalysed 3 вместо 0 сохранён как подтверждение source-status дефекта, ожидание не ослаблено.

| Уровень | Факт |
|---|---|
| Код | самостоятельные API/source/UX fixes отдельно; #72 + profile6 только в pending integration |
| LOCAL | новые HTTP cases, RED/GREEN, real migration, reproducible build/verify, browser выполнены; точные SHA выше |
| CI | обязательные Checks точного окончательного head, включая HTTP и existing box/systemd; состояние в PR |
| Человек/клиент | NOT_RUN; [пустой протокол участника](../../../product/pilot/PARTICIPANT-SESSION.md) |
| Целевая ВМ | NOT_RUN; отсутствует доступ и здесь не требуется |
| Настоящие endpoints/интеграции | NOT_RUN; loopback stands не LIVE |

Приоритеты: P1 — M3 ack и согласованный релиз; P1 — старый код при откате до rebuild;
P1 — внешняя приёмка и установка не выполнены. P2 — ограниченная грамматика, wrapper FN,
неизмеренная клиентская полезность и человеческое прохождение. Нет SLA окна устаревания.

| Работа | Исполнитель | Можно без ВМ | Доступы | Критерий завершения |
|---|---|---|---|---|
| Ack точного integration head/profile6 | M3 через владельца | да | PR/доказательства | явный ответ с SHA/составом; не молчание |
| Интеграция #72/profile6 | исполнитель | да | ack + обязательные checks/review | совпадение main с проверенным деревом |
| Новый опубликованный release | оператор выпуска | да | accepted main, штатный workflow | download/hash/manifest/install-published VERIFIED |
| Сверка #71 | M3 | да | актуальные heads | разрешён конфликт сохранённого плана, ни одна история не потеряна |
| Update/backup/restore/rollback | один оператор M3 | нет | доверенный восстановленный хост | loaded SHA, restart/recovery/history/rollback на ВМ |
| Независимый корпус и участник | владелец/разработчик | да | проект, независимо заданные ожидания | FP/FN/unknown и реальные наблюдения без подсказанных ответов |
| Настоящая M2 LIVE | M3 + владелец | работающий сервис | HTTPS/App/Jira/согласованный контур | реальные endpoints, дубли/new head/error/self-loop |
