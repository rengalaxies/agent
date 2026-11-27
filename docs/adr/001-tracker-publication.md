# ADR 001 — минимальный контракт публикации в трекеры

14.11.2026. Решение для пачки07; интеграция с runtime запланирована в08/09. Доказательство доступности реальных tenant API пока отсутствует; см. [приёмку07](../integrations/batch07/README.md).

## Контекст и выбор

Сегодня Publisher использует пять операций backend: bot_identity, list_comments, get_comment, create_comment, update_comment. BitbucketJiraBackend перед каждым обращением проверяет актуальную версию PR и единственную Jira-связь, а ID комментария содержит целевую задачу. Нужна такая же дисциплина для Kaiten и Яндекс Трекера. CoreAnalyzer, граф и outbox не требуют переписывания ради другой площадки комментария.

Выбран **структурный PublicationBackend Protocol** в connectors/base.py и отдельные TaskIdentity/CommentIdentity в tracker_contract.py. Альтернативы — универсальный CRUD-трекер со сменой всех Jira ID либо два полностью независимых Publisher — увеличивают миграцию/дублирование без необходимости для этого сценария. Runtime Jira сохраняет текущую схему ID и поведение; новые helpers пока только additive и используются диагностической пробой. Protocol проверяет форму интерфейса, а поведенческие гарантии проверяются тестами и приёмкой адаптера.

## Идентификация и связь

- TaskIdentity = provider + tenant + **неизменяемый native ID строкой**. Kaiten tenant — канонический origin компании, native ID — десятичный card.id; Яндекс — тип заголовка организации + org ID, issue.id. Jira legacy jira:<issue_id> остаётся внутри прежней connection. Task key, URL и title служат отображению/разрешению алиаса; не являются каноническим ключом.
- CommentIdentity = TaskIdentity + native comment ID. Новые ID кодируются versioned JSON-массивом с prefix tracker-comment:v1:, без неоднозначного разделителя. Яндекс longId предпочтителен; числовой id нельзя проводить через float/JavaScript Number. Декодирование с expected-target отвергает другой tenant/задачу.
- В08/09 явный binding для разрешённого Bitbucket PR указывает ровно одну (provider, connection/tenant, task) в allowlist доски/очереди. Способ хранения binding выбирается при реализации; поиск произвольных похожих ключей в тексте не разрешает публикацию. Ноль/несколько/недоступная цель — видимый отказ, без fallback в иной трекер.
- Перед **каждой** операцией публикации заново читается PR, сверяется сохранённая source version и разрешённая связь; алиас разрешается в immutable ID, scope проверяется по REST. Comment ID другого target не используется. Смена связи supersede/recheck; комментарий в старой задаче автоматически не удаляется.

## Чтение задачи и версии

Адаптер читает разрешённую задачу, сохраняет исходную provider revision отдельно, проецирует согласованные semantic fields и признак доступности/закрытия. semantic_version хеширует identity, closed и **полные** выбранные поля до обрезания для UI. Set-поля адаптер сортирует; отсутствие/пустое значение различаются по согласованному mapping. Минимальный контекст: immutable ID, display key/URL, title/summary, description, scope, closed/unavailable, semantic version. Native version, updated, comments_total/lastCommentUpdatedAt и тело собственного комментария в semantic projection не входят. Текст не исполняется и не даёт новых прав.

Для первой реализации контекст карточки/задачи передаётся как attachment/context существующему PR-анализу; поддержка task-only/pre-PR анализа отдельно потребует расширения Jira-specific trigger/request mapping. В07 новые providers в settings/envelope/Service не зарегистрированы. Должны сохраниться текущие ограничения Python HTTP/API и MODEL OFF.

Состояния done/archive и недоступности адаптер фиксирует явно по своей модели/настройке scope. Числовые состояния Kaiten и локальные статусы Яндекса нельзя приравнивать к Jira без live-пробы; probe проверяет только идентичность/scope и archived/deleted там, где эти поля есть.

## Комментарии, marker, повторы

Публичная форма соответствует существующим Comment/Publisher: ID, author, marker, digest, generation; native comment revision при наличии остаётся адаптерной метаданной. Marker стабилен для installation + исходного Bitbucket resource, digest — от канонического результата, generation — локальное поколение. Provider revision, digest и generation — разные величины.

Результат ищется по **marker и автору выделенного bot**. get_comment возвращает None только при подтверждённом исчезновении комментария; недоступную задачу/connection нельзя маскировать под отсутствие комментария. list_comments возвращает полный набор либо явную ошибку. Две подходящие копии — диагностика; нельзя скрыть проблему произвольным выбором первого элемента в новом адаптере. Существующая Jira-дисциплина duplicates не изменена в07.

Create передаёт один текстовый результат с marker; update редактирует тот же native ID. В Kaiten renderer должен уместить **весь** текст вместе с marker в4096 символов: краткий статус, существенные выводы, явное сокращение; полный результат остаётся в outbox. Нельзя отрезать marker или публиковать несуществующую ссылку на outbox. До поставки08 нужен тест renderer на длинный реальный результат и решение, как пользователь получит детали. Проба использует короткий фиксированный диагностический текст.

После неопределённого create (timeout/5xx/обрыв или ответ без проверяемого ID) нельзя слепо повторять POST. Сначала полное чтение и поиск своего marker, выдержка на eventual visibility и диагностика; отсутствие не доказывает, что запись не появилась. Проба оставляет UNKNOWN и при resume без найденной записи больше не создаёт. Product Publisher уже имеет reconciliation/settle window; для08/09 сохраняем этот путь, не заявляя математическое exactly-once без поддержки idempotency сервером.

Перед update повторно проверяются target, bot ownership и marker. В проверенных описаниях PATCH комментария нет подтверждённого CAS-параметра; native version в ответе не доказывает поддержку conditional update. Поэтому не отправляем выдуманный If-Match/version и не обещаем атомарность против ручного конкурентного редактирования. После записи перечитываем результат и source, новый source ставится на пересчёт. Между последней проверкой и HTTP write остаётся окно гонки, как у текущей Jira.

## Ошибки и очередь

| Ответ/событие | Контракт |
|---|---|
| 401/403 без признаков rate limit | Connection blocked, понятная причина; не сжигать retry budget |
| 429 | RateLimited; Retry-After/reset если есть, bounded backoff и jitter; не выдавать за auth failure |
| GET timeout/5xx | Retryable read failure; список не превращается в пустой |
| POST/PATCH timeout/5xx | UNKNOWN outcome; reconciliation перед следующим действием |
| 404 задачи | Цель недоступна; не создавать результат в другой задаче |
| 404 комментария | Перелокация только после подтверждения доступности задачи и нового полного list |
| 409/412 | Повторное чтение, видимый conflict, без слепого повторения stale update |
| 400/422/423/428 | Видимая provider_rejected/locked/precondition диагностика, без бесконечного retry |
| Неполная/циклическая пагинация, неверный JSON, другой target/author | Fail closed; записи нет |

Текущий HttpClient уже классифицирует auth/rate-limit/read/write transport errors; Publisher сохраняет UNKNOWN. Специальная обработка conflict/lock, общий limiter на tenant и карта provider codes проверяются при08/09, не объявлены реализованными только наличием этой таблицы.

## Точки реализации08/09

1. Новый connector: scope/read/prepare, credentials и разрешённый polling либо подтверждённая защита webhook. Подпись Jira нельзя переносить на другие сервисы по предположению.
2. Связующий backend с новым target guard и scoped comment locator; совместимость старых outbox/Jira ID.
3. Provider renderer и полный пагинированный list; безопасный response mapping и author identity probe.
4. Минимальная settings/envelope/worker wiring; backoff/rate limiting и проверка перезапуска.
5. Реальные выделенные цели: create → исправление → тот же comment ID, replay/relink/delete/closed/access failures; квитанции отдельно по площадке. Общая приёмка10 остаётся самостоятельной.

Диагностическая реализация дополнительно требует X-Pagination-Limit Kaiten, проверяет Yandex next cursor по последнему raw id и исчерпывает курсор до пустой страницы при отсутствии Link. Она отклоняет206/переполненные страницы, чужой supplied self, deleted/malformed write replies; PASS возможен только после своего PATCH либо durable update_pending/verified и финальной проверки scope. Это проверка выбранного протокола на stand, не уже подключённые product adapters.
