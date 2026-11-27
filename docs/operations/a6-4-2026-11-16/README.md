# A6.4 — операторская панель ImpactMap

Технические проверки16.11.2026; финализация17.11.2026. SOURCE / LOCAL VERIFICATION. База `cee0b49`; read model `7b8c91d`, экраны `f1287c8`, исправления ревью `e96798d`. Установленный worker и реальные трекеры не менялись. Это подэтап A6, исходные14 основных и A1–A5 не перенумерованы.

## Что работает

- `/ui/operations`: последние100 допущенных ресурсов, состояния текущих заданий, отдельный старый анализ, до10 допущенных outbox-намерений на ресурс, ошибки и безопасный следующий шаг при UNKNOWN/SENDING. Счётчики относятся только к показанной выборке, не ко всей очереди. Worker честно «не наблюдалось»: heartbeat не реализован, HTTP liveness не заменяет доступ к источникам.
- `/ui/connections`: текущие allowlisted metadata загруженного ServiceConfig, репозитории/runtime IDs разрешённой области, сохранённые пробелы анализа, intake inventory timestamp, отдельные Jira/Kaiten/Яндекс, явные привязки и конфликты. Настроенный маршрут, совпавший snapshot и старая инвентаризация не объявляются успешной API-пробой. Яндекс без конфигурации — NOT_CONNECTED.
- Серверный403 для reviewer на обоих JSON и HTML маршрутах; роль не переключается в браузере. No-store/same-origin/session/CSRF остаются из A6.2. Перезапуск, повтор, публикация, probes и редактирование bindings/keys из UI не предлагаются.
- GET читает один SQLite snapshot. Raw notice detail, snapshot, publisher document, marker, HTTP receipt, URL/пути/secret env references конфигурации не сериализуются. Сервисный Bearer не попадает в браузер. Unknown строки причин заменяются на UNKNOWN, без произвольного сообщения ошибки.
- Body14px, h1 desktop28px/mobile23px,44px controls. В операторских разделах боковой список изменений скрыт; из очереди/привязки есть переход к защищённому результату.

## Исправления и граница происхождения

Независимое source review `cee0b49..f1287c8`:0 Critical,3 Important,2 Minor. Один fix-pass `e96798d`:

1. Legacy notices не имеют подтверждения старой области. Добавлена отдельная bounded таблица `ui_notice_observations` с canonical scope receipt и отдельным счётчиком; Service/Publisher пишут и очищают наблюдения в текущей области policy. Старые данные не backfill-ятся и не используются как scoped counts. Оригинальная legacy notices/история/Bearer status сохранены. Таблица создаётся аддитивно, максимум10000 scoped observations; credentials и error detail в ней отсутствуют.
2. Outbox проверяет receipt поколения в SQL **до** LIMIT10; чужие поколения не вытесняют разрешённые. Неавторизованный `published_generation` из операторского JSON удалён.
3. Kaiten binding требует обе настроенные UUID — workspace и repository. Для нескольких Jira-целей после сужения проектов показывается CONFLICT с разрешёнными ключами; запрещённые target IDs не выдаются.

Дополнительно исправлены две ранее обнаруженные ошибки:

- Валидный сохранённый анализ после смены поколения ошибочно становился incompatible, потому что очередь меняет lifecycle reason. Diagnostics теперь допускает **только** известные причины отзыва у SUPERSEDED старого/закрытого поколения, продолжая строго проверять контракт; произвольное несовпадение отвергается. `analysis.reason` при этом относится к сохранённому контракту, текущая ошибка задания остаётся отдельно. Это осознанное изменение смысла поля после revocation, не ослабление scope checks.
- После сетевого отказа logout и hidden→visible восстановление кнопки повторного выхода работает на workbench и session page. Возвращается только выход/ошибка, приватное содержимое не восстанавливается. Browser harness сначала показал RED, затем GREEN и подтверждённый повторный выход.

## Верификация

- Baseline62/62 PASS. Operator read model10 RED до реализации; API RED против placeholders. Промежуточные35/36/75 tests PASS.
- До финальных scope fixes широкий service-run485 tests/550.435s, PASS с4 Linux-only skips. После scope fixes:491 tests/574.581s, PASS с4 skips (`service-final.log`). Финальный constructor-stamp path дополнительно проверен профильным107-run; новая Linux-приёмка не заявляется.
- Финальные профильные UI/auth/role/scope/queue/error/connection tests:107 PASS. Узкая промежуточная команда без разрешённых sockets дала20 PermissionError; повтор с localhost-разрешением прошёл, это не скрытые code failures.
- RED→GREEN регрессии: stale compatibility и произвольный mismatch, case-insensitive GitHub mapping, legacy/foreign notice counts, scoped Service/Publisher writers и constructor notice, outbox scope-before-limit, workspace UUID (RED на функции из f1287c8), mixed Jira targets. Полная запись source review — [review.md](review.md).
- Browser1440: body14/h128, scrollWidth1440;390: h123/scrollWidth390, overflow отсутствует. Подтверждены FAILED+STALE с совместимым старым USEFUL, UNKNOWN recovery, source gap, Kaiten ATTENTION и binding CONFLICT, Яндекс NOT_CONNECTED, reviewer direct403 и отсутствие operator links. Read-only30s polling дал только GET me/operations. Дамп service SQLite до/после неизменен; auth DB обновляет техническое состояние сессии отдельно.
- Logout lifecycle тестируется через **явный author-only synthetic visibilitychange harness**, настоящий AuthStore и искусственный503 первого logout. Это проверка клиентской логики; не выдаётся за native OS visibility acceptance. Product package не содержит QA controls/forced error routes. После GREEN обе страницы повторно вышли, private/user fields пусты.
- Wheel собран без новых runtime dependencies;22 runtime modules/assets byte-identical исходникам. Это source wheel, не Linux box release или поставка на ВМ. Все temporary stands остановлены, credentials удалены.

Из корня с существующим venv и разрешёнными локальными sockets:

```sh
TMPDIR=/private/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.:tests:tools \
  /path/to/venv/bin/python -m unittest \
  tests.service.test_ui_auth tests.service.test_ui_admin \
  tests.service.test_ui_operator tests.service.test_ui_api \
  tests.service.test_ui_views tests.service.test_ui_scope \
  tests.service.test_diagnostics tests.service.test_queue \
  tests.service.test_errors tests.service.test_connection -q
```

QA reproducer: `PYTHONPATH=src:.:tests:tools /path/to/venv/bin/python docs/operations/a6-4-2026-11-16/reproduce/serve.py`. Stand127.0.0.1:18090, случайные временные accounts `qa-owner`/`qa-reader`, password только в ignored mode0600 `work/a6-4/private/credentials.json`, удаляется при stop вместе с temp DB. `--fail-logout-first` добавляет отдельные QA lifecycle controls; обычный запуск их не добавляет. Нет настоящих токенов, внешних API или worker loop. Основные кейсы author fixtures; Jira KAN-10 — сохранённый author-run CoreAnalyzer output из A6.0 с явно заменённым namespace, не новый LIVE цикл.

## Что остаётся

Два Minor source review отложены: ссылка из configured binding до первого разрешённого результата может дать404; коды interrupted_during_send/awaiting_listing/resource_missing пока показаны как UNKNOWN. Это не объявляется исправленным.

Решения автора: исправить lifecycle compatibility в diagnostics в пределах A6.4, иначе экран неверно описывает старый анализ; browser/wheel проверить самостоятельно, развёрнутую установку оставить A6.5. Цена границы — независимой runtime/owner acceptance и новой Linux-поставки пока нет. Whole-project1342 root-run из A6.3 остаётся красным в неизменённом SQL-профиле Mac RLIMIT_AS; причины и50 unsuccessful entries сохранены [в A6.3](../a6-3-2026-11-16/README.md). Повтор того15-минутного root-run без изменения причины не запускался; проверен весь относящийся к изменениям service layer.

Следующая **A6.5**: Linux/package/install/restart, HTTPS/private access, auth+service backup/restore, защищённые ссылки из настоящих Jira/Kaiten комментариев и5 сценариев приёмки владельцем/оператором. Отдельный release, без молчаливой замены работающего worker. Реальные аккаунты, ключи и внешние записи этой пачкой не создавались. Яндекс07/09, общий LIVE gate10, независимая06 и интервью01/11 остаются обязательствами.
