# Карта знаний и зависимостей (knowledge-1 -> map-2)
Статус: архитектурная валидация, без заявления об уже реализованном UI. Сверяться с `docs/knowledge-module-2026-09-29.md` и исходным кодом: knowledge-1 уже реализован с подтверждением/отзывом, полнотой реестра и immutable snapshot.

## Зачем карта
Не красивая картинка, а **проверяемый индекс влияния изменения**: какие продукты/поля и активные потребители затронуты, какие обязательства действуют на закреплённой версии, кто вправе выпускать/подтверждать, какой evidence обосновывает связь. Карта должна отвечать на вопрос «что будет нарушено, если производитель поменяет значение этого атрибута?».

## Узлы и типизированные связи
Nodes: Domain, DataProduct, Attribute/Concept, ContractVersion, Consumer, ConsumerRequirement/Obligation, ConstitutionVersion, Principal/Role, EventType, ChangeProposal, Decision, Evidence, SemanticMapping, EnvironmentProfile.
Edges: DOMAIN_OWNS_PRODUCT, PRODUCT_HAS_ATTRIBUTE, PRODUCT_HAS_CONTRACT_VERSION, CONSUMER_USES_PRODUCT_OR_ATTRIBUTE, REQUIREMENT_APPLIES_TO_ATTRIBUTE, CONSTITUTION_AUTHORIZES_PRINCIPAL, ATTRIBUTE_DERIVED_FROM, EVENT_UPDATES_PRODUCT, CHANGE_AFFECTS_ATTRIBUTE, DECISION_EVALUATES_CHANGE, DECISION_BASED_ON_EVIDENCE, ATTRIBUTE_MATCHES_ATTRIBUTE (with relation type), SUPERSEDES_VERSION.
Каждая связь: stable IDs, source_domain, source_version, validity range, observed_at, evidence_uri/hash, status (proposed/verified/revoked), access_scope; у проекции `snapshot_id`. Не использовать LLM similarity как эквивалент подтверждённой связи.

## Source of truth vs projection
Домен сохраняет мастер-версию ownership, contract, constitution, consumer requirements и подписанные позиции. Федеративная карта - производная, восстанавливаемая и ограниченная по правам read-model; она НЕ утверждает контракты за домены. Публикация события об изменении запускает обновление materialized projection; наблюдаемая задержка/отставание projection видна пользователю.
Для решения V2 обязательна закреплённая версия локального реестра активных потребителей. Если полнота/актуальность карты не доказана, **нельзя просто брать пустой набор и делать ACCEPT**. Применять явный полный список активных потребителей либо UNKNOWN/NEEDS_REVIEW. Скрывать неполноту в UI запрещено.

## Последовательность изменения
1. Производитель формирует ChangeProposal и закрепляет C_old/C_new, constitution и registry snapshot.
2. Semantic diff вычисляет изменившиеся измерения: meaning/formula, unit/scale, time/window, identity_scope, lineage/source, purpose/consumer_scope.
3. По verified edges идёт traversal от атрибутов к активным consumer requirements. Unknown edge / stale registry -> расширенная проверка или NEEDS_REVIEW.
4. Consumer домены независимо выдают DomainPositionIssued по своим обязательствам.
5. Policy Engine сводит REJECT > NEEDS_REVIEW > ACCEPT с reason codes и evidence; повторно проверяет snapshot на commit.
6. Map materialized view обновляет статусы в результате ReleaseCommitted / ReleaseRejected / ReviewRequested.
7. Журнал хранит provenance, timestamps, hashes и состав входов, replay/revoke воспроизводимы.

## Визуальные представления
A. Dependency map: домены как дорожки, продукты, атрибуты, активные consumer edges; опасные зависимости подсвечены по **вычисленному статусу**, а не по предположению LLM.
B. Change impact: diff старой/новой версии, затронутые потребители и индивидуальные obligation verdicts.
C. Authority map: кому разрешено propose, review, approve, release; отсутствующее полномочие явно отмечено.
D. Evidence drawer: source, version, hash, provenance, validity, reason, confidence (если candidate), human review.
E. Snapshot/freshness: last event offset, lag, completeness flag и предупреждение при частичной карте.

## MVP технологии
На старте PostgreSQL tables + indexes/recursive CTE для графа и API materialized view; не заводить Neo4j только из-за визуализации. UI graph library выбирается после smoke-test размеров 3 домена / 10 продуктов / 30 полей / 15 потребителей. Для среднего размера >1000 элементов применять фильтры и virtualized/list-first представление.
Уже существующий `knowledge-1` не переписывать без gap analysis. Проверить API и источники: привязка consumer requirements, immutable snapshots, revoke/replay, stale checks, concurrency, provenance. Разделить права просмотра разных доменов.

## Логические риски и проверки
- Circular dependency: bounded traversal + visited set, никаких бесконечных обходов.
- Неполные/устаревшие ребра: статус UNKNOWN, не «нет потребителей».
- Конфликт owner: неснимаемая неоднозначность и эскалация вместо самостоятельного назначения.
- Дубликаты событий: идемпотентный merge по stable event ID + version.
- Смена требования между snapshot и commit: abort/recheck.
- Cross-org boundary: видимость только permitted metadata/aggregates, не утечка внутренних ролей/атрибутов.
- Mapping confidence: ранжирование кандидатов; deterministic validation и подтверждение независимы.
- Rejected release: нельзя отображать C_new как действующий contract.
- UI cache: показать freshness/version и не позволять принимать decision из устаревшего графа.

## Тесты acceptance
T1 один producer, два потребителя с разными окнами -> индивидуальные вердикты и REJECT либо review.
T2 подтверждённое преобразование RUB -> kopecks + тесты -> ACCEPT при выполнении всех требований.
T3 неизвестный потребитель -> UNKNOWN/NEEDS_REVIEW, а не ACCEPT.
T4 revoke связи/неполный индекс -> re-evaluation, trace причины.
T5 conflict owner authority -> NEEDS_REVIEW.
T6 duplicate/reordered events -> единственное заключительное решение.
T7 disconnect Consumer B -> независимые локальные операции продолжаются; затронутый выпуск не ACCEPT.
T8 устаревший snapshot -> ABORTED/retry.
T9 access policy forbids viewer -> скрытие чувствительной части graph и evidence.

## Научное позиционирование
Карта - вспомогательный индекс и интерфейс к обязательствам и evidence, не самостоятельный доказанный научный результат и не агент, способный вывести организационные границы из воздуха. Для H1 карта поддерживает поиск затронутых потребителей; для E4 проверяется корректность зависимостей, семантических кандидатов, ответственности и изоляции. Замерять качество графа отдельно от качества V2.
