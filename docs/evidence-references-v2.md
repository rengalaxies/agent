# Evidence references: отдельное продолжение PR №31

Изменение устраняет повторный набор цитат моделью. `read_source` в опциональном
протоколе `evidence-refs-v2` возвращает текст и `evidence_ref`; модель в `propose`
передаёт типизированную направленную зависимость и список полученных ссылок.
Доверенный код разрешает ссылки в точные `Citation` снимка и вызывает неизменённые
`Graph.get_evidence` и `Graph.propose`. Результат по-прежнему только
`UNAPPROVED_CANDIDATE`, без разрешения выпуска или подтверждения runtime.

## Два отдельных барьера

1. `EvidenceSession.resolve` заново проверяет `read_context`, текущие grants,
   subject/view, текущий head, TTL и basis. Receipt появляется только после
   разрешённого чтения и связывает session ID, context/snapshot ID, basis, файл
   (repository/path/revision/source ID/SHA256), диапазон и digest точного текста.
   Произвольный ID, ID другой сессии, отзыв scope/прав и устаревший снимок отклоняются.
   Знание ID не позволяет открыть другую сессию, файл или расширить диапазон.
2. `dependency_sufficiency` независимо проверяет конкретный typed claim:
   consumer repository **и** service, provider service, направление, method/path,
   покрытие callsite и объявления провайдера. Используется существующий статический
   профиль ядра `http-requests-2` и его разрешение URL через operator addresses.
   Совпадение `/orders` у Orders и Status не означает идентичность сервисов.
   Одни точные, но нерелевантные строки дают `INSUFFICIENT`, а не принятую связь.

`assess` возвращает раздельные `provenance` и `sufficiency`; после отказа первого
барьера второй получает `NOT_ASSESSED`. Для Python требуется покрытие декораторов
маршрута и объявления функции, для OpenAPI — полного документа, а для consumer —
точного вызова. Диапазоны можно объединять, но пробелы в покрытии не разрешены.
Неподдерживаемая грамматика означает недостаточность доказательства в этом профиле,
а не отсутствие зависимости. Отдельное доказательство произвольных семантических
гипотез, wrappers/dynamic URL и бизнес-требований в этот минимальный протокол не входит.

Пример **только тестового** предложения после двух разрешённых чтений:

```json
{
  "claim": {
    "consumer_repository": "reporting",
    "consumer_service": "reporting",
    "provider_service": "orders",
    "method": "GET",
    "path_template": "/orders"
  },
  "evidence_refs": ["ID_FROM_CALLSITE_READ", "ID_FROM_PROVIDER_READ"]
}
```

Эти placeholder IDs не действуют. Свободного `statement`, `key` и поля `quote` в v2
нет: доверенный код строит statement/key из проверенного claim, чтобы одобренная
структура не прикрывала противоположное утверждение в прозе. Исторические модельные
цитаты не нормализуются, не исправляются и не преобразуются в ссылки.

## Совместимость и миграция с PR №28

Основание отдельной ветки — head PR №28
`f1c4546725e759ffc06ca0281f7103132dbcfe73`. PR нацелен на его ветку
`docs/useful-graph-open-questions`, чтобы ревью содержало только добавление v2.
Ветка PR №28 не изменяется. Это предложение интерфейса для согласования, не заявление
о принятии ядра или полученном согласии его автора.

- `Graph.get_evidence`, `Graph.propose`, `Citation`, `Proposal`, SQL schema и старые
  записи не изменены. `Graph.propose` v1 проверяет происхождение, но сам по себе **не**
  является новым семантическим барьером. V2 должен проходить через `EvidenceSession.propose`.
- Новый optional `ModelConfig.protocol` по умолчанию `quotes-v1`; `ModelReply` и
  `model_action_schema()` без аргумента сохраняют прежний контракт. Только явное
  `protocol="evidence-refs-v2"` включает `ReferenceReply`/новый prompt/read/propose.
- Сначала обновить ядро и клиента. Затем сменить protocol/configuration_id и начать
  **новый** investigate с новым контекстом/сессией. Не продолжать историю v1 внутри v2.
  При откате убрать новое поле policy/config и начать новый v1 investigate.
- Receipts живут в доверенном process-local объекте; session ID нельзя предъявить
  для восстановления сессии. После перезапуска нужно снова разрешённо прочитать
  файлы. Persisted proposals сохраняют обычные точные citations; v2 report сохраняет
  metadata чтений, ссылки, typed claims и раздельные оценки для аудита. Сохранённый
  audit ID не становится полномочием для следующего процесса.
- Report получает поле `protocol`, v2 события — `evidence_read`, `reference_proposals`
  и `evidence_assessments`. Потребители отчётов должны допускать добавочные поля.
- Сохраняются private Store, operator-owned Policy, лимиты корпуса/строк/предложений,
  source-transfer consent, endpoint allowlist, token/cost reserves и запрет модельной
  human correction. Как и PR №28, это один доверенный OS user, не изоляция SaaS tenants.

## Офлайн-проверки и границы результата

`tests/graph/test_evidence_refs.py` содержит явно обозначенные scripted positive
proposals на синтетических данных. Проверяются корректная ссылка; выдуманный ID;
чужая сессия; права/subject/scope; изменённый, superseded, expired/unavailable снимок;
неверный диапазон; изменённые metadata; точное нерелевантное основание; неверные
направление/service/method/path; недостаточное покрытие обеих сторон; сохранённые
Reporting, Export E и Status decoy.

`tests/graph/fixtures/pr31/provenance.json` фиксирует source PR/SHA и SHA256
байтовых копий выбранных исторических reports/dialogues/corpus. Оригиналы PR №31
не изменяются. В regression v1 меняются только source IDs для тестового namespace;
quote/range/claim исторических ответов остаются исходными и по-прежнему отвергаются.
Сценарий с новыми scripted references — **другой, явно тестовый** ввод, не исправленный
или успешный исторический ответ модели.

Ссылки устраняют ошибки копирования кавычек/отступов в **новом** протоколе. Неправильный
read range, выдуманная ссылка, нехватка доказательств, неверное направление/сервис,
ошибка JSON/action, timeout/лимит шагов и неподдерживаемая грамматика остаются
возможными отказами. Их нельзя устранить выдачей более широких полномочий или
автозаменой цитат. Качество реальных моделей после изменения пока не измерялось.

Следующий эксперимент и команды воспроизведения: [план](../experiments/evidence_refs_v2/README.md).
Новых модельных вызовов нет; закрытый пакет PR №31, secrets/vars и ВМ не изменяются.

## Дополнение технического ревью и runner

Отдельная ветка поверх SHA `4354ef613e187e4244984b9ad09e0672792b0714` добавляет
optional `ModelConfig.token_parameter` (default `max_tokens`; runner явно выбирает
`max_completion_tokens`), absolute `deadline_epoch` у ChatModel/investigate и
trusted-only `admission_check` у Graph/Store/EvidenceSession.propose. Отсутствие
новых аргументов сохраняет старый путь; JSON модели не содержит callbacks/deadlines.
Admission guard проверяется внутри транзакции, чтобы поздний insert откатился.
Потребителю собственного Store, включающему deadline, нужно поддержать optional
`admission_check`; старый вызов без deadline не передаёт этот новый keyword.

Статические оценки явно помечены STATIC_PROFILE_ONLY; недостаточность не означает
доказанное отсутствие зависимости. Независимые синтетические controls используют
другие repository/service IDs, filenames, POST, host/port/base path и побайтно
одинаковый provider decoy. Они не переименовывают исторические ответы моделей.
