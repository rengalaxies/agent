# Пачка08 — адаптер Kaiten и реальные проверки API

15.11.2026. **AC08 закрыты в изолированном cloud-профиле.** [Настоящие Bitbucket Cloud/Kaiten, Linux restart и lifecycle, все квитанции и ограничения](cloud-2026-11-15/README.md). Далее сохранён отчёт реализации/гибрида14.11. Яндекс Трекер отложен владельцем до решения вопроса доступа.

## Что поставлено

- Опциональный mode `bitbucket.mode=kaiten_delivery`: текущий Bitbucket Git/core connector обёрнут контекстом карточки, существующие CoreAnalyzer/ServiceStore/Publisher публикуют результат через новый backend. Jira/GitHub сохраняют прежние режимы.
- Явный config binding immutable Bitbucket PR resource ID→card ID; allowlist board IDs. Без угадывания карточек по похожему тексту. Tenant входит в task/comment identity. Native IDs строковые, lookup от старого backend/target устаревает без редактирования старой карточки.
- Kaiten v1: чтение карточки и полной пагинации комментариев; GET users/current проверяет bot до записи; POST/PATCH текстового результата с readback. Limit применяется по X-Pagination-Limit, без полного списка запись запрещена. Voice/transcription rows без optional deleted поддерживаются, неверный тип deleted отклоняется.
- Полная semantic version до UI truncation, без comment metadata. Контекст title/description ограничен20k для attachments, сокращение помечается gap. Ядро пока не интерпретирует описание Kaiten как доказательство требований/совместимости — это контекст и основание пересчёта.
- Русский bounded renderer ≤4096 символов вместе с единственным доверенным marker. Сокращение явно указано; полное structured result остаётся в SQLite outbox. Для диагностики использовать защищённый локальный state/status, отдельного публичного URL к полному отчёту пока нет.
- Writes связаны с **конкретным sending intent**, его generation/version и lease; повторная проверка после preflight непосредственно перед write. Старое поколение не разрешается совпадением latest source с latest DB. Внешнего CAS против последней гонки provider не предоставляет; короткое окно между последней проверкой и запросом остаётся.
- 404/archive/deleted/condition2–3/move off-board делают ресурс недоступным без остановки прочих PR. Auth/rate/transport ошибки идут через текущую очередь; local limiter10requests/s на экземпляр connection. Это не глобальный лимитер нескольких процессов/установок.
- Невалидный/слишком большой 2xx write response или неподтверждённый публичным чтением результат остаётся UNKNOWN; POST не повторяется вслепую. Используется текущий Publisher settle/reconciliation, без обещания exactly-once при произвольно долгой невидимости записи.

## Реальное рабочее пространство

Владелец создал аккаунт, указал rengalaxies.kaiten.ru и сам вошёл во встроенном браузере. После отдельного явного согласия создан API-ключ. Значение не выводилось в чат/логи/Git, файл mode0600 в ignored work/batch08/private; доступ наследует права тестовой учётной записи, ограничение board в клиенте не является серверным scope токена.

Создана доска **ImpactMap — интеграционные тесты**, board1982649, space941235; выделенная карточка74759475. Исходные учебные доски/карточки не удалялись и не редактировались. Дополнительная колонка «Проверка ImpactMap» создана при настройке доски. Рабочая карточка: https://rengalaxies.kaiten.ru/space/941235/lists/card/74759475.

Первый Python TLS-вызов не прошёл из-за отсутствующего default CA bundle. Использован уже установленный certifi через SSL_CERT_FILE, проверка TLS и отказ от redirects сохранены. Глобальные настройки системы/venv не менялись.

## Доказательства и границы

[API-проба](api-probe-receipt.json): `REAL_API/PASS`, POST → PATCH того же comment93785697 → два readback, generation2. Эта квитанция закрывает живой Kaiten API-пункт07; Яндекс-пункт07 остаётся NOT_RUN. Историческая приёмка07 в коммите0bcde4e отражает состояние до появления аккаунта.

[Гибридная квитанция](hybrid-receipt.json): **авторский локальный Bitbucket HTTP stand + настоящие Git snapshots/CoreAnalyzer/ServiceStore/Publisher + настоящий Kaiten API**. Первый head дал USEFUL/POSSIBLE_TRUNCATION; исправленный head восстановил исходное API и дал ABSTAINED/no_supported_delta. Native comment93785713 обновился на месте. Один комментарий на marker; повторные reconcile и реконструкция Service/ServiceStore в том же процессе не создали дубль/новое поколение. MODEL OFF. Диагностический API-comment и продуктовый result-comment имеют разные markers/назначения; всего на карточке два ожидаемых комментария.

Первая попытка hybrid driver остановилась **после успешной доставки** из-за неверного ожидания состояния ANALYZED вместо DONE. Queue/Git/marker не сбрасывались; продолжение проверило прежний source и использовало тот же SQLite. First steps=[] в итоговой квитанции означает resume уже доставленного первого этапа; первый фактический анализ/публикация сохранены в durable queue/history. Не выбиралась лучшая попытка. [Точный использованный driver](hybrid-driver-used.py) — журнал конкретного запуска, не универсальный установщик: содержит имена private файлов, требует test fixtures и отказывается продолжать на несовпадающем head. Не сбрасывать его output после неизвестной записи.

На14.11 настоящий cloud PR и OS restart ещё не были выполнены;15.11 они пройдены отдельно (см. cloud-отчёт). Установка release не выполнялась; live401/403 и lifecycle описаны отдельно от injected429/5xx. Не приписывать локальному Bitbucket stand статус cloud E2E. Три последовательных цикла всех трекеров — будущая10. Тесты с401/403/429/5xx/обрывом выполнены локально, не искусственным повреждением аккаунта поставщика.

## Конфигурация

К существующей Bitbucket/core конфигурации добавить:

```json
{
  "publication": "dry_run",
  "bitbucket": {"mode": "kaiten_delivery", "...": "существующие workspace/repository/auth настройки"},
  "kaiten": {
    "base_url": "https://rengalaxies.kaiten.ru",
    "board_ids": ["1982649"],
    "bot_id": "1000388",
    "token_env": "IM_KAITEN_TOKEN",
    "bindings": {"bitbucket:<workspace-uuid>/<repo-uuid>#<pr-number>": "74759475"}
  }
}
```

Это **фрагмент**, placeholder `...` не входит в schema. Для реального source нужны существующие разрешённые Bitbucket настройки, локальные pinned mirrors и core policy. Одновременные jira/github/confluence в kaiten_delivery не разрешены. `dry_run` пишет только DirectorySink; `live` включает Kaiten backend. Сначала проверять dry-run, потом использовать выделенный pilot PR. Secret читается один раз при build, отсутствие обнаруживается до запуска worker. Allow_loopback_http — только тестовые стенды.

## Проверки и следующий шаг

[Лог тестов](tests.log), [ревью](review.md), [приёмка](acceptance.json), [план](../../superpowers/plans/2026-11-14-impactmap-batch08-kaiten.md).

Cloud gate пройден15.11: PR5, change→fix→replay и Linux SIGKILL/recovery. Следующий integration gate — Яндекс07/09 при появлении доступа, затем общий release/приёмка10. Существующий установленный runtime не менялся. Независимая оценка06 не закрыта этим прогоном.
