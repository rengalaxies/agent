# ImpactMap UI: локальные пользователи, сессии и права — A6.2

UI включается явно в HTTP-процессе `agent_service serve`. Без `--ui-config` новые `/ui/...` отсутствуют. Существующие `/status`, `/resources`, `/result`, `/graph` продолжают использовать отдельный operator Bearer; пользовательская cookie их не открывает, а служебный ключ не является UI-login. На действующей ВМ эта версия пока не устанавливалась.

Объём A6.2 — настоящая граница доступа и read-only проекции, страница входа/проверки сессии. Рабочие экраны результатов и операторской панели подключаются в A6.3/A6.4. Прототип на18087 остаётся отдельным авторским макетом; его переключатель роли не заменяет эту авторизацию.

## Условия пилота

Одна установка/организация, один общий corpus scope reviewer/operator. Разных пользователей с разными правами на проекты в одной установке этот режим не поддерживает. Установка должна иметь настоящий CoreAnalyzer/Policy с `read_context` и совпадающими installation/environment. Граница — приложение и его grants, не защита от владельца ОС/произвольной модификации SQLite.

Auth config/DB принадлежат тому же OS-пользователю, что запускает HTTP-процесс и локальные команды; файлы0600, родительская директория без group/world write. Они находятся вне всех analyzed repository roots и отдельно от service.sqlite. Поддержаны POSIX Linux/Mac; Windows UI access в этой пачке не квалифицировался и отклоняется явно.

Развёрнутый UI требует HTTPS через настроенный защищённый reverse proxy, сохраняющий канонический Host. Uvicorn запускается с `proxy_headers=False`: приложение не выводит origin/роль/IP из присланных X-Forwarded заголовков. Настройка TLS/proxy/сервиса и LIVE приёмка остаются отдельной поставкой; пример ниже их не выполняет.

## Настройка и локальные команды

Пример **нового** private config, сохранить0600 под владельцем сервиса:

```json
{
  "database": "/srv/impactmap/private/ui/auth.sqlite",
  "origin": "https://impactmap.example"
}
```

Пути — пример, не установленная конфигурация dm-p1-ui. `origin` задаётся без завершающего `/`, пути, query, userinfo или неоднозначного hostname; database — абсолютный путь. Устанавливать аккаунты следует под тем же OS-пользователем, который будет читать DB. Сетевые провайдеры этими командами не вызываются.

```sh
python -m agent_service.ui_admin --config /etc/impactmap/service.yaml --ui-config /srv/impactmap/private/ui.json --username reviewer --role reviewer create-user
python -m agent_service.ui_admin --config /etc/impactmap/service.yaml --ui-config /srv/impactmap/private/ui.json --username operator --role operator create-user
python -m agent_service serve --config /etc/impactmap/service.yaml --ui-config /srv/impactmap/private/ui.json --host 127.0.0.1 --port 8090
```

Пароль запрашивается дважды через getpass; аргумента с паролем и default account нет. Минимум12 UTF-8 bytes, максимум1024; предпочтителен длинный случайный пароль. Хэш: scrypt N32768/r8/p3, salt16 bytes, derived key32 bytes, maxmem128MiB. Argon2 не добавлялся как новая runtime dependency; выбран один из опубликованных [профилей scrypt OWASP](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html).

Тот же префикс `--config ... --ui-config ... --username ...` поддерживает:

- `set-password` — интерактивный новый пароль;
- `set-role --role reviewer|operator`;
- `disable-user` / `enable-user`;
- `revoke-sessions` — отозвать все сессии пользователя;
- `approve-scope` — явно привязать пользователя к текущим grants/installation/env/service DB. Не выполняется автоматически при изменении policy; disabled-пользователь этим не включается.

Каждое изменение пользователя отзывает старые сессии. Auth DB/её audit не печатаются CLI. Резервное копирование новой auth DB не добавлено автоматически в старый box backup profile; включение в поставку/backup/restore и отзыв сессий после rollback состояния требуют приёмки A6.5. DB содержит хэши паролей и security state, поэтому сохранять с теми же ограничениями доступа.

Для **изолированного локального** теста допустим явный `allow_insecure_loopback: true` и `origin: http://127.0.0.1:PORT`. Тогда serve требует bind127.0.0.1, middleware отклоняет нелокального peer, а cookies имеют отдельные loopback-имена. Это не настройка публичной установки. Не доверять X-Forwarded-For при проверке loopback.

## Сессии и HTTP

Session token — случайные32 bytes; в SQLite только SHA256 token. Production cookie `__Host-impactmap_session`, Secure/HttpOnly/SameSite=Strict/Path=/, без Domain. Absolute lifetime8h, idle20min, сервер проверяет актуальную версию пользователя/role/scope при каждом UI API request. Пароль/роль/отключение/CLI revoke прекращают прежние сессии; cookie/query/Bearer не выбирают роль.

Вход: `GET /ui/api/csrf` создаёт отдельную одноразовую pre-session с5min TTL, затем JSON `POST /ui/api/login` требует её cookie, точный Origin и X-CSRF-Token. Session fixation исключена новым token и удалением предъявленного прежнего token. Ошибки входа одинаковы для неизвестного/неверного/disabled пользователя. Durable rolling limit5 попыток/15min для username+peer и60/min на peer, до2 KDF одновременно в процессе. За reverse proxy без forwarded trust peer общий: лимит строже, это известная граница одного частного пилота, не масштабирование публичного login сервиса.

`GET /ui/api/me` возвращает username/role/installation/env, CSRF для выхода, absolute/effective deadline и относительный TTL. Клиент не кладёт эти значения в localStorage/URL. Relative TTL минус roundtrip защищает очистку экрана от неверных часов клиента; по expiry/pagehide данные убираются, при возвращении вкладки сессия перепроверяется, фонового polling нет. Stale async ответ не восстанавливает очищенный экран. `POST /ui/api/logout` требует session CSRF;403 не означает успешный выход. При межвкладочной ротации выполняется один read-me/retry с новым CSRF, затем показывается ошибка, если сервер не подтвердил отзыв.

Все UI responses, включая401/403/404/405, no-store/nosniff/no-referrer и CSP без inline scripts. CORS не включён. Неверный Host421; cross-site/неверный Origin403; слишком большой login body413 (4KiB); невалидный JSON400 без эха входа; throttle429. Служебные секреты, cookies, password hashes, arbitrary snapshots и HTTP receipts в проекции не входят. Разрешённый исходник сам может содержать чувствительные литералы; это не универсальный secret scanner.

## Область результатов

Перед analyze queue сохраняет trusted scope receipt из валидного построенного AnalysisRequest, с проверкой lease/current generation. Это не assertion модели и не поле raw output. Receipt включает installation/environment/view/repositories/runtime sources и привязку request/event/resource version. Grants пользователя также привязаны к расположению service DB; перенос/изменение read grants требует явного approve-scope.

`GET /ui/api/resources?limit=1..100` и `GET /ui/api/result?resource_id=...` требуют receipt текущего поколения и выбранного сохранённого анализа. Чужой/missing scope, чужой output или неизвестный ID дают одинаковый404; список не выдаёт такие строки/их счётчики. Исторические результаты без receipts не backfill-ятся предположением о нынешних правах. Новое поколение до построения request, provider failure до этого шага и legacy job могут пока отсутствовать в UI-проекции. Это ограничение явно названо `coverage=STAMPED_SCOPE_ONLY`, а не «влияния нет».

Анализ возвращается в curated `analysis.result`, не произвольном `raw`/publisher document; job/freshness/publication независимы. FAILED нового поколения может показывать старый STALE, только если обе области доказаны. Incompatible payload скрыт. Чтение не вызывает connectors/reconcile/retry/publish и не меняет service DB; auth store меняет last_seen/session state отдельно.

Reviewer получает403 на `/ui/api/operations` и `/ui/api/connections`. Operator допускается, но эти endpoints честно возвращают `available=false` с причиной pending A6.4; старый admin-wide `/status` не проксируется. Полная история, source quote endpoint и connections/bindings metadata потребуют следующей реализации и отдельных grants checks.

[Проверка, ограничения и артефакты](a6-2-2026-11-16/README.md).


## A6.3: рабочие результаты

После входа открывается `/ui/changes`. Прямая ссылка `/ui/result?resource_id=...` сохраняет назначение через вход; разрешены только фиксированные same-origin UI paths. ID — точный идентификатор из `/ui/api/resources`, не repo/path/commit для произвольного чтения файла. Старый `/ui/session` сохранён для проверки роли и установки.

`GET /ui/api/view[?resource_id=...]` — authenticated read-only endpoint: escaped HTML fragments `list_html`, `list_note_html`, `result_html` плюс `observed_at` (UTC epoch). Список и выбранный результат читаются в одном snapshot. Неавторизованный/отсутствующий ресурс404, пустой/длиннее512 ID400. Запрос не строит анализ, не вызывает reconcile/connector и не публикует. JSON projections A6.2 остаются доступны.

В списке максимум100 разрешённых результатов; проверка ограничена1000 кандидатами. `scan_budget=1000` — постоянный предел, не измерение числа скрытых ресурсов; `has_more=true` только если найдена дополнительная разрешённая строка. Старое поле `scan_limited` удалено из нового UI projection: оно могло сообщать о количестве скрытых кандидатов. Поиск выполняется только по уже выданным строкам; полный архив не обещается.

Ручное обновление и включаемый пользователем30s refresh выполняют только GET. При скрытии документа, pagehide, expiry или logout приватный DOM очищается и refresh прекращается. Выход в соседние одновременно открытые workbench/session страницы передаётся через BroadcastChannel без credentials; это проверено во встроенном браузере, полная browser matrix остаётся A6.5. Ошибка загрузки ресурса оставляет возможность выйти; ошибка выхода не объявляется успехом.

Основания — точные координаты сохранённого снимка, без встроенного quote или произвольного внешнего URL. Статусы публикации и актуальности не заменяют статус анализа. Настоящий результат CoreAnalyzer и граничные случаи: [отчёт A6.3](a6-3-2026-11-16/README.md). Операционная панель остаётся A6.4; Linux/TLS/auth backup/restore/tracker-linked owner acceptance — A6.5.


## A6.4: операторская панель

`/ui/operations` и `/ui/connections` теперь читают реальные сохранённые данные через role-gated GET API. Safe `OperatorMetadata` строится из загруженного ServiceConfig при обычном CLI запуске автоматически; secret env references, адреса с credentials и пути не копируются. Встраивания, создающие Service напрямую без metadata, получают явное unavailable вместо фиктивной готовности.

Режим только чтения: максимум100 scoped resources/1000 candidates и10 допущенных outbox intents на ресурс; receipts проверяются до LIMIT. Счётчики только этой выборки. Возврат legacy global counts/status в browser не используется. Надписи worker NOT_OBSERVED и connection NOT_CHECKED намеренные: heartbeat/probe из GET не запускаются. Inventory timestamp относится к прошлой успешной инвентаризации, не к текущему доступу к назначению.

Новая аддитивная таблица service DB `ui_notice_observations` хранит canonical receipt, known notice kind/subject/count/times; максимум10000 строк. Service/Publisher при записи передают текущую policy scope, при clear очищают только её scoped observation. Legacy notices остаются для прежней диагностики; UI не backfill-ит их через нынешние grants. До нового подтверждённого наблюдения старое уведомление не показано, и отсутствие строки не подтверждает исправность. Backup/restore должен сохранять всю service DB и отдельную auth DB; новая Linux/restore-приёмка входит в A6.5.

Конфиг Kaiten binding проверяет workspace и repository UUID, затем scope repository ID. Конфликт сохранённого target с configured target виден без раскрытия старого target. Смешанные Jira keys показывают CONFLICT с разрешёнными проектами; запрещённые IDs не выдаются. Названия/числовые IDs — сохранённые metadata, не API permission test. Яндекс без конфигурации NOT_CONNECTED.

При обычной смене поколения сохранённый валидный анализ остаётся STALE, даже если очередь отозвала старое задание и изменила lifecycle reason. Исключение только для известных причин SUPERSEDED старого/закрытого поколения, контракт продолжает валидироваться. Retry logout после сетевого отказа восстанавливает только выход, не operator data. [Полный отчёт A6.4](a6-4-2026-11-16/README.md), включая2 Minor и ограничения.
