# Техническое ревью PR №32 и готовность нового runner

Проверяемый SHA: `4354ef613e187e4244984b9ad09e0672792b0714`. Прочитаны фактический
diff относительно `f1c4546725e759ffc06ca0281f7103132dbcfe73`, contracts/engine/store/
transport, тесты, docs/plan, сохранённые reports/dialogues PR №31. AGENTS.md не найден
в доступных родительских каталогах, checkout и деревьях main/PR28/PR32.

Исходный PR подготовлен в этом же чате. Это повторное техническое ревью с новыми
независимыми контрольными данными, **не внешний независимый approval**. Ни этот
отчёт, ни зелёный CI не являются приёмкой PR №28/32 или разрешением model calls.

## Findings на проверяемом SHA

| ID | Серьёзность | Наблюдение и воспроизведение | Исправление в отдельной ветке |
| --- | --- | --- | --- |
| R1 | P1, блокер запуска | [Транспорт](https://github.com/rengalaxies/agent/blob/4354ef613e187e4244984b9ad09e0672792b0714/src/agent_graph/inference.py#L51) каждый раз создаёт относительный timeout; [investigate](https://github.com/rengalaxies/agent/blob/4354ef613e187e4244984b9ad09e0672792b0714/src/agent_graph/inference.py#L277) не получает общего срока. Rehearsal вычисляет deadline, но не соединён с transport/admission; live runner отсутствовал. Новая SQLite директория не обеспечивает общий счётчик между Actions jobs/reruns. Это известный пробел готовности, не обнаруженный обход авторизации refs. | Реальный runner, фиксированный durable Git ledger, initialize/claim-once, reservation до transport, absolute wall+monotonic bounds в HTTP/investigate/admission, terminal states, no reset/rerun. |
| R2 | P1, несовпадение с планом запуска | [Payload](https://github.com/rengalaxies/agent/blob/4354ef613e187e4244984b9ad09e0672792b0714/src/agent_graph/inference.py#L152) использует max_tokens, тогда как фиксированный Cloud.ru план требует max_completion_tokens. Нельзя выдавать этот код за реализацию плана. Это **не** доказывает неподдержку legacy поля или причину старого timeout. | Optional token_parameter, legacy default сохранён; runner явно выбирает max_completion_tokens для обеих моделей. Локальный HTTP stub проверяет wire payload. |
| R3 | P2, дефект офлайн-прототипа | [simulate_attempt](https://github.com/rengalaxies/agent/blob/4354ef613e187e4244984b9ad09e0672792b0714/tools/prepare_evidence_refs_experiment.py#L98): ошибка срока откатывает transaction, включая last_seen. На исходном коде start=1000, попытка=1000, отказ case_deadline при 1300, затем now=1299 снова даёт SIMULATED_NO_HTTP. | Rehearsal сохраняет stop вне rollback; live ledger фиксирует terminal expiration/clock status. Regression проверяет запрет reopening после отката часов/restart. |

R1/R2/R3 исправлены в изолированной ветке. Новые модельные вызовы для проверки не
выполнялись. End-to-end storage/HTTP в GitHub/Cloud.ru с настоящими credentials
не проверены; вместо них выполнены offline CAS/storage controls и local HTTP stubs.

## Проверенные свойства refs

- Receipt создаётся после разрешённого чтения. Связаны session, subject/view,
  context ID/basis, repository/path/revision/SHA256, source ID и точный range/hash.
  Read/propose capabilities перепроверяются. ID не импортирует чужую сессию и
  не расширяет права; process-local sessions не возобновляются по audit IDs.
- Повторное использование в той же сессии допускается, одинаковое предложение
  идемпотентно. Смена subject/grants/head/basis/TTL/источника запрещает использование.
  Текст разрешается только из snapshot, затем проходит старый exact quote validator.
- V1 quotes/default ModelReply сохранены. Invalid quotes не нормализуются и не
  превращаются в references. Старые historical reports/quotes/ranges не изменены.
- Gate sufficiency сопоставляет directed consumer repository **и** service,
  provider identity через адресный static resolver, method/path и покрытие
  callsite/provider declaration. В нём нет имён Orders/Reporting/Export/Status,
  fixture filenames или oracle. Ограничения grammar не выдаются за отсутствие связи.
- Принятие остаётся UNAPPROVED_CANDIDATE. Parser edges не дополняются предложениями;
  runtime_verified=false. Новые поля STATIC_PROFILE_ONLY и NOT_ESTABLISHED явно
  описывают предел вывода, а не требуют общего семантического доказательства.

Новые synthetic controls используют producer_repo/decoy_repo/batch_repo,
svc_zeta/svc_eta/job_beta, endpoints_alt.py/unrelated_name.py/send_batch.py, POST
/widgets, host:port/base-path. Побайтно одинаковые provider declarations не
позволяют подменить сервис. Проверяются корректный полный span, точный нерелевантный
span в правильном файле, wrong provider/direction, источник, изменённый после
чтения, и unsupported wrapper. Все данные явно тестовые.

## Интеграция без двойного включения ядра

На момент проверки remote refs:

- main: `08a52704269c75d8d78a8fcf4ed8b9f10cf45722`, agent_graph в main отсутствует;
- PR №28: `f1c4546725e759ffc06ca0281f7103132dbcfe73`, open/draft;
- PR №32: `4354ef613e187e4244984b9ad09e0672792b0714`, open/draft, base — ветка №28.

Новая ветка начинается ровно с SHA №32 и содержит только последующие исправления
и runner. Отдельный PR нацелен на `codex/evidence-references`, не меняя ни №28,
ни №32. При переносе брать **только коммиты после 4354ef6**. Порядок интеграции:
сначала однократная приёмка №28; затем retarget №32 на main с проверкой итогового
diff; затем retarget PR runner на принятую базу. Если родители squash/rebase,
переносить только дочерний diff на новый main и сверить его; не cherry-pick всей
истории вместе с ядром второй раз. Автоматическое слияние не выполняется.

Optional интерфейс deadline/metadata/token_parameter и trusted admission_check
описан в docs/evidence-references-v2.md. SQL schema ядра не меняется; старый вызов
без deadline не передаёт новый keyword в пользовательский Store.

## Проверки и следующий запуск

Локально: **115 graph tests PASS**, включая исходные 59 core, сохранённые Reporting,
Export и Status, новые generic controls, HTTP deadline/token/schema stubs, durable
CAS/unknown/budget/rerun/clock/secret-canary tests и scripted серию всех шести случаев.
Ruff 0.17.1 F401/F811/F841 и actionlint 1.7.7 PASS (без shellcheck/pyflakes).
Исторические JSON/corpus fixture SHA256 сохранены. Положительные тестовые данные
не являются результатами реальных моделей; реальный v2 цикл: NOT_RUN.

Протокол требует прочитать все listed sources, включая decoy, до первого propose;
evaluator проверяет покрытие без ожидаемых связей в model payload.
Scripted серия прошла read/read/propose/finish для Reporting/Export и
read/read/read/propose/finish для Status: **26** попыток. Практически рекомендуется
**30 новых**, по 5 на каждую из шести пар, без retries, одинаковые параметры.
21 историческая попытка хранится отдельно от нового score, unknown usage №15
не превращается в 0. Новый денежный/request cap ещё не задан; grant уже подтверждён
и не запрашивается повторно.

[Команды и manual workflow](README.md) готовы. Dispatch возможен после появления
workflow в default branch и интеграции принятого кода; exact main SHA фиксируется
перед initialize/execute. Ни initialize, ни execute сейчас не запускались; accounting
ветка не создавалась. ВМ, платные Cloud.ru ресурсы и secrets/vars не изменены.
