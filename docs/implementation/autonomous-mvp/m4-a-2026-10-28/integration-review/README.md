# Предметное ревью перед интеграцией — 28.10.2026

Проверен parent #72 `214bec72ccb6df59a29e8d1069eca91202cf5c1e` и исходный diff
от main `d5e25fde5927eca99e574b2ac82be80cd5adfe16`. Модель OFF. Это ревью основного
исполнителя и дополнительные авторские регрессии, не независимый benchmark.
Предыдущие CI/хеши в родительском отчёте относятся к прежнему head; новый CI нужен.

## Дополнительные дефекты: сначала RED, затем исправление

1. `Change README to describe GET /parcels pagination` и русское
   `Изменить документацию: описать GET /parcels` давали explicit API intent.
   [Исходное воспроизведение](docs-edit-before.log): 2 failing subcases; положительный
   контроль с настоящим reduce API PASS. Исправление удаляет из проверки API-action
   только небольшой фиксированный шаблон глагола, прямо направленного на документацию.
   Другой API-action в той же фразе сохраняется. Это не общая модель языка.
2. Legacy proposal с `cited_config=NULL` опирался только на policy view, который не
   содержит extractor profile. После нового context он оставался CURRENT.
   Теперь fallback читает профиль исходного immutable context; другой/неизвестный
   профиль делает знание STALE. Существующая миграция, таблицы и история не удаляются.
   Контроль legacy proposal того же профиля остаётся CURRENT.
3. Persistent graph code bases не содержали профиль и не проверяли его на чтении:
   до первого sync старые основания/связи были CURRENT. Теперь внутренние basis data
   и identity включают профиль; отсутствие/несовпадение даёт STALE с существующим
   `basis_changed`. Новый sync открывает новые основания, закрывает старые и сохраняет
   историю/прежние contexts. Runtime/ownership основания этим не инвалидируются.

[RED до правки для 2–3](profile-migration-before.log): 3 failures.
[Целевой GREEN](integration-targeted.log): 32 PASS, включая существующие persistence,
migration, access/recovery и отрицательные контроли.
[Полный LOCAL набор](full-local-tests.log): **883 PASS**, 222.958 s.
Всего теперь 25 авторских M4-A методов. [Хеши проверенного кода](code-files.json).

## Остальные пункты ревью

Service scope не берётся из соседней операции; неизвестный provider router оставляет
gap и не классифицируется engine как OPERATION_REMOVED. Консервативная binding-проверка
может воздерживаться на допустимом сложном Python; unknown не означает доказанное
отсутствие вызова. Wrapper/динамический URL остаются вне положительной грамматики.
Адреса и approved requirement — явные входы, ожидаемые потребители анализатору не передаются.

## Переход 4 → 5: что реально происходит

- Сразу при чтении старый context STALE (`extractor_profile_changed`), даже для pinned Git.
  Предлагать новое знание на нём нельзя; comparison с ним отклоняется `base_profile_mismatch`.
- Старое знание остаётся читаемым в разрешённом scope, но STALE; прежняя гипотеза не
  становится подтверждённой автоматически. Для актуального основания нужен новый context
  и повторная проверка/новая запись. SUPERSEDED история сохраняет свой статус.
- Graph/view до sync показывает старые code relationships STALE, а не CURRENT.
  После успешного чтения источников sync/reconciliation создаёт новые basis; исчезнувшее
  положительное основание закрывается в истории, gaps остаются ограничением покрытия.
  Недоступный источник не объявляется доказанно пустым.
- worker при старте вызывает reconciliation; код графа пересчитывается также по событиям
  и periodic reconcile (обычно 900 s), после pinning доступных default branches.
- **Внешний уже опубликованный комментарий не пересчитывается одним изменением profile.**
  Очередь coalesces неизменную версию Jira/PR; обычный следующий новый resource version
  вызывает новый анализ. До него старое тело с прежними code/base/head может сохраняться.
  Этот переход не обещает мгновенно обновить внешний API. Queue/connectors не менялись;
  для данной приёмки нужен новый отдельный installation/state без прежних публикаций.
  Для будущего upgrade уже используемой установки отдельно проверить/реализовать
  управляемую reanalysis unchanged resources; не удалять БД или историю как обход.

Scope дополнен `src/agent_graph/{graph_query,graph_store,store}.py` для подтверждённых
пробелов миграции; схемы публичных документов и SQLite не изменились. M3 deployment,
installer, pin/release, credentials и ВМ не менялись. До merge остаются новый зелёный CI
и явное согласование M3 на актуальных heads. Подготовленный release 14e65e8 не обновлён.

## Последний подслучай редактирования документации

`Change README to document GET /parcels page_size 40 -> 3` всё ещё давал explicit intent:
после удаления глагола редактирования документации оставалась числовая стрелка.
[RED](docs-edit-arrow-before.log): 1 failure, контроль реального reduce API PASS.
Минимальное уточнение: только при явном DOCUMENTATION_EDIT числовая стрелка сама
не считается API-action; другой change/reduce глагол сохраняет API intent.
[GREEN](docs-edit-arrow-after.log): 25 новых/существующих intent checks PASS.
Число авторских методов прежнее (25 M4-A), добавлены подслучаи и отрицательный контроль.
Закрытая грамматика не стала общим parser естественного языка.

Подготовительный #73 слит отдельно после CI 861+152 PASS:
main `40768d04bbc13147741c3d9a2308b730b4aa6128`, product code #72 туда не входит.
Два private pilot repo уже заполнены и проверены реальными API/Git; App IDs получены
из UI, bot identity подтверждена API, service App JWT NOT_RUN без PEM. Jira/M3/HTTPS
BLOCKED. #72 подтягивает этот main в свою отдельную ветку, затем проходит новый CI
на итоговом head; ack M3 всё ещё требуется. Поставка release14e/pin не меняется.
