# Демо и продуктовая гипотеза: JTBD, CJM, UX, данные

> Исторический план от 13 октября. Текущая продуктовая ставка и статусы после аудита: [пересборка продукта](../product-rebuild-2026-10-16.md). Инфраструктурные действия требуют сверки с актуальным runbook и состоянием среды; этот файл не подтверждает развертывание.

Статус: proposed product discovery track (startup); **не менять** исследовательский E3/E4 без ADR.

## Формулировка ценности (проверять, а не утверждать)
Для Data Product Owner / platform engineer, который меняет производный признак и должен сохранить обязательства нескольких команд, система собирает из версионированных артефактов impact map и доказательства, запрашивает локальные позиции затронутых доменов и объяснимо допускает, блокирует или направляет на review изменение **до публикации**. В отличие от ручной коммуникации, решение трассируемо и воспроизводимо. Факт снижения incident rate/time-to-release пока не установлен.

## JTBD по ролям
- Producer: «Когда меняю расчёт пользовательского признака, хочу до выпуска узнать, кого и почему затронет изменение, чтобы не сломать чужой продукт».
- Consumer: «Когда другой домен меняет продукт, хочу автоматически проверить обязательства своей версии, чтобы не узнавать о нарушении из аналитического инцидента».
- Governance officer: «Когда проверяют спорный допуск, хочу восстановить версии правил, участников и доказательства, чтобы провести аудит».
- Platform team: «Когда подключается новый домен, хочу воспроизвести стандартный безопасный bootstrap по допустимой конституции, без переписывания чужих узлов».

## As-Is CJM (гипотеза; интервью должен подтвердить)
Change requested -> ищут owner и downstream users вручную -> сравнивают schema и документацию -> договариваются в чатах/тикетах -> проводят тесты -> релиз -> иногда находят semantic regression -> rollback/ручной аудит.
Риски: нет полного реестра потребителей; поле сохранило тип, но сменило смысл; ownership размыт; позднее обнаружение; журнал решения фрагментарен. Не выдавать этот CJM за факт организации.

## To-Be CJM
Import verified constitution/contracts/consumer obligations -> propose change -> snapshot + semantic diff -> graph impact -> policy/consumer verdicts -> ACCEPT/REJECT/NEEDS_REVIEW -> evidence + audit -> release/quarantine/escalation -> replay/report.
HITL обязателен при UNKNOWN, конфликте authority, отсутствующем доказательстве, изменении constitution rights. Agent output - предложение, не полномочие на release.

## Минимальный UI (5 экранов)
1. Home/workspace: 3 домена, версии, состояние сети и registry freshness.
2. Map: producer -> data product -> field -> consumers; фильтр домена и «what changed».
3. Change detail: C_old vs C_new, обязательства потребителей, кто затронут и почему.
4. Decision: per-domain verdict + итог + машинные reason codes + human-readable explanation; evidence and lineage.
5. Run history: версия конституции, snapshot, run_id, action log, repeat/reset, экспорт обезличенного evidence JSON.
Не обещать конструктор политики, сложную RBAC-админку, полноценный каталог данных, чат с LLM и production API в MVP.

## Демо за 5 минут
00:00-00:30 — карта трёх доменов: fintech производит `gross_spend_30d`, retail и mobility используют разные обязательства.
00:30-01:30 — producer меняет формулу gross->net при прежнем decimal/type; structural V0 может не заметить смысловой сдвиг.
01:30-02:30 — impact view раскрывает обязательства; V2 выдаёт REJECT для нарушенного required_meaning, показывает доказательства.
02:30-03:30 — сценарий безопасного изменения (корректная миграция валютного масштаба либо безвредное описание) -> ACCEPT.
03:30-04:30 — недоступный consumer / неизвестная версия -> NEEDS_REVIEW, не ложный ACCEPT; показать человеческую эскалацию.
04:30-05:00 — журнал версий/решений и границы: синтетика, prototype, без промышленного SLA.
Важно: не сравнивать V0/V1-ind/V2 на специально подобранном demo как доказательство H1; это иллюстрация, не E3.

## Сценарий на архитектурной схеме вместо живого демо
Два рисунка: deployment diagram (public UI, private domain nodes, event broker, stores, external model API), sequence diagram (producer proposes; snapshot; affected consumers; DomainPositionIssued; deterministic aggregate; commit/quarantine/review). Подготовить один data contract JSON/YAML, три consumer obligations, trace of one decision, десять UI screenshots только после действительного прототипирования (макет пометить MOCK).

## Evidence для product-market validation
Problem interviews -> подтверждение повторяемых событий; solution interview -> корректность workflow и востребованность; pilot -> совместимость с данными и безопасностью; paid discovery -> есть ли владелец бюджета. Вести таблицу hypothesis, evidence, counterevidence, confidence, decision, next test. Нельзя считать интервью «показателями рынка» без сегментации.

## Acceptance до первого внешнего демо
- 3 воспроизводимых синтетических сценария со статусами ACCEPT/REJECT/NEEDS_REVIEW.
- Карта показывает подтверждённые связи и версии; неизвестные связи видны как UNKNOWN.
- Нельзя утечь закрытым evaluation-oracle, model API key или реальными персональными данными.
- Внятное отличие работающего кода от предполагаемых будущих функций.
- Один сценарий записан заранее на случай потери связи; запись/скриншот честно маркированы.
- Отдельный private интервью-протокол и follow-up.
