# A6.3 — рабочие результаты ImpactMap, 16.11.2026

Статус: SOURCE / LOCAL VERIFICATION. Общий прогон и его ограничения фиксируются отдельно ниже. База `b0c4104`, read model `02378f8`, workbench `dd738ec`, review fixes `5d3502d`. Установленный worker и реальные трекеры этой пачкой не изменялись. Это подэтап A6 сверх исходных14 основных и A1–A5.

## Результат

Рабочий workbench доступен при включённой A6.2 UI auth: `/ui/changes` и `/ui/result?resource_id=...`. После настоящего входа браузер получает scoped, server-rendered HTML через `/ui/api/view`. Список и выбранный результат читаются в одной SQLite-транзакции. Сохранены JSON API A6.2 и отдельный Bearer-доступ к диагностике. Полная [инструкция включения](../impactmap-ui-access.md).

- Последние100 разрешённых ресурсов; поиск только в загруженном списке. В каждой строке источник, поколение, анализ, актуальность, публикация и время UTC. Ограничение сканирования1000 кандидатов сообщается всем одинаково; наличие скрытых строк не раскрывается. `has_more` подтверждает только найденную дополнительную разрешённую строку.
- Независимые состояния задания, актуальности сохранённого анализа и публикации. Новый FAILED не скрывает старый STALE; CLOSED, PARTIAL, ABSTAINED, неизвестные коды и incompatible не превращаются в общий успех. Поколение результата, текущее поколение и доставленное поколение различаются.
- Изменение операции, наблюдение о потребителе, факты, гипотезы, неизвестное, пробелы и рекомендуемые проверки читаются из сохранённого контракта. Владелец команды отображается из TeamEntity. Предварительный Jira-результат без diff прямо помечается предварительным.
- Потребитель → relationship → evidence и finding → evidence ведут к своим числовым внутренним якорям. Основание сохраняет repository/path/commit/blob/SHA-256/строки и отдельные provenance/sufficiency/freshness. Никакого чтения случайного пути/HEAD, произвольной внешней ссылки или выдуманного quote. Недоступность фрагмента явно указана.
- Ручное обновление и opt-in30s GET только видимой страницы; по умолчанию polling выключен. Переход к якорю не перечитывает результат и не уводит фокус на h1. Устаревший ответ навигации отвергается по revision; pagehide/hidden/expiry очищают приватное содержимое и таймеры.
- Выход подтверждается сервером. Два одновременно видимых документа получают credential-free same-origin BroadcastChannel-сигнал и очищаются. JS не получает cookie/session token/service Bearer; CSRF остаётся в памяти модуля. Сигнал не содержит пользователя, области доступа или ключей.
- Дизайн варианта2: мягкая зелёная навигация,3 колонки, компактный шрифт14px и desktop h128px/mobile h123px;44px controls. Операторские страницы пока честно показывают «A6.4», reviewer403 проверяется сервером.

## Воспроизводимость

Из корня репозитория; существующий venv содержит extras `api,test-api`:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.:tests:tools \
  /path/to/venv/bin/python -m unittest \
  tests.service.test_ui_auth tests.service.test_ui_admin \
  tests.service.test_ui_api tests.service.test_ui_scope \
  tests.service.test_ui_views tests.service.test_diagnostics -q
```

Изолированный browser stand, только loopback:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.:tests:tools \
  /path/to/venv/bin/python docs/operations/a6-3-2026-11-16/reproduce/serve.py
```

Временные имена `qa-reader`/`qa-owner`, случайный пароль — только в игнорируемом mode0600 `work/a6-3/private/credentials.json`; не default product accounts. При завершении сервер удаляет credentials и временные обе БД. Никаких реальных API-ключей, connector calls или worker loops. Дополнительный `--idle 10` существует только у QA-стенда; production auth20min idle/8h absolute не меняется.

Семь граничных ситуаций seeded через настоящие ServiceStore/receipt/completion APIs. Восьмой пример — действительный сохранённый CoreAnalyzer output из audit A6.0, namespace заменён на `author-fixture/qa`, выдано авторское scope receipt тестовой установки. Это не независимый эталон и не LIVE Jira-цикл. Ни raw snapshot, ни publisher document не выдаются UI.

## Проверки

- Baseline47/47 PASS; первоначальные views8 RED (модуль отсутствовал), HTTP2 RED (404 вместо workbench/view).
- После source implementation58/58 PASS. Найденные браузером регрессии: скрытая кнопка выхода при404 — RED→GREEN; настоящий KNOWN owner с TeamEntity давал500 — регрессионный test на сохранённом CoreAnalyzer output RED→GREEN.
- Независимое source review `b0c4104..dd738ec`:0 Critical,6 Important; reviewer самостоятельно прошёл35 тестов. Все шесть входят в один fix-pass: hidden-candidate flags, list state/time/source, native anchor, cross-window logout, nullable gap, consumer/finding evidence links. Тесты/браузерная проверка описаны ниже.
- Desktop1440/14px/28px и narrow390/14px/23px без горизонтального overflow, клавиатурный переход к основанию. Браузерные сценарии авторские, не owner acceptance.
- Полный project test command запускается с `TMPDIR=/private/tmp`, PYTHONPATH проекта + временные `test-deps`, объявленный test extra `jsonschema==4.26.0` установлен только в игнорируемом каталоге. Первый sandbox-run1273 tests дал46 failures/360 errors:319 socket PermissionError,38 symlink-path errors,2 missing jsonschema и связанные падения subprocess. Этот запуск не выдаётся за проход. Повтор с разрешёнными local HTTP sockets:1342 tests/900.180s,49 failures/1 error/4 skips. Все50 записей failures/errors — `product.*`; новых UI/core/service failure нет. [Полный список](project-failures.json), [сырой вывод](project-final.log).
- Wheel собирается существующим изолированным build-venv из A6.2;14 UI modules/assets сверяются byte-for-byte. Это wheel исходников, не Linux box release и не установленный сервис.

## Ограничения и следующий шаг

Фрагмент кода внутри UI пока недоступен: показываются точные сохранённые координаты. Полная история/сравнение поколений не загружены. Старые/early-failed результаты без trusted scope receipts скрыты; широкое обратное заполнение не выполняется. Обновление данных пишет только техническое состояние сессии в отдельную auth DB; service SQLite остаётся неизменной.

Следующая **A6.4** — настоящая read-only операторская панель: очередь, notices, состояние источников и трекеров, безопасные metadata/bindings. **A6.5** — Linux packaging/install/restart, HTTPS, auth backup/restore и переход из настоящих комментариев Jira/Kaiten с приёмкой владельцем. Это ещё не поставка UI на ВМ.

Сохраняются обязательства07/09/полной10 по Яндексу и трём трекерам, независимая06 и настоящие интервью01/11. Авторские UI-тесты не доказывают точность, полноту, спрос или экономию времени.


## Финальное source review и границы решения

Все6 Important исправлены в5d3502d одним проходом. Пять Python-regressions наблюдались RED→GREEN (1001 stamped-but-withheld rows, nullable gap, publication/source/time in list, finding refs, per-consumer refs на настоящем сохранённом output). Browser anchor RED:2 лишних GET, фокус h1 и основание далеко внизу; GREEN:0 GET, фокус evidence-0, верх20px. Оба открытых документа были `visibility=visible`; logout broadcast проверен в обоих направлениях между session/workbench. Полный цикл30s polling дал ровно GET me200/view200. Последующие service DB dump hashes unchanged. Expiry10s QA удаляет private/account DOM и возвращает login; console errors отсутствуют.

Отложен один Minor ревью: если logout завершился сетевой ошибкой, затем вкладка скрылась и вернулась, кнопка повторного выхода может исчезнуть. Приватное содержимое уже удалено, серверный выход успехом не объявляется; повторный вход на `/ui/session` позволяет выполнить выход. Доработка восстановления кнопки остаётся для следующего UI-прохода.

Решения по исключённым reviewer границам: (1) HTTPS deployment/реальный переход из трекера/приёмка владельцем — A6.5; цена решения — deployed UI ещё не проверен. (2) Этот оперативный отчёт проверяет автор, отдельно от source review; цена — текст не прошёл независимое ревью. Это не новые ограничения исходной программы, а сохранение согласованных границ.

`result-desktop.jpg`, `result-mobile.jpg`, `core-result-desktop.jpg`, `core-result-mobile.jpg` и `session-expired.jpg` — текущая browser verification. `stale-failed.jpg`, `partial-unknown.jpg`, `evidence.jpg` и before-review traces сохраняют более раннюю стадию A6.3, до финальных исправлений списка/якорей. Все данные авторские; роли получены через настоящую auth, не selector.


## Общий regression gate

Общий набор **не зелёный** на данном Mac/Python3.13:49 failures/1 error,4 skips. Все неуспешные записи относятся к отдельному SQL-профилю `change_completion`, включая executor/verification и зависящие contract/runtime/workflow проверки; единственная ошибка — `test_cached_patch_tamper_is_not_released` (`KeyError: patches`) после отсутствия ожидаемого SQL-результата.

[Baseline diagnostic](product-worker-platform.json): executor.py/sql_worker.py/verification_worker.py byte-identical базеb0c4104. Минимальный SELECT на baseline и current одинаково получает `worker_failed`; оба worker падают до чтения входа на `resource.setrlimit(RLIMIT_AS,256MiB)` с `ValueError: current limit exceeds maximum limit`. Это воспроизводимое исходное ограничение текущей macOS-среды, а не основание отключать защиту worker ради UI-тестов. SQL-профиль этой пачкой не изменён. Отдельный Linux/global-green gate остаётся открытым; повторять весь15-минутный Mac-run без изменения причины не требуется.

Актуальная проверка A6.3:62 focused PASS; полный root-run не выявил неуспешных тестов вне product.*, браузерные AC пройдены в заявленном author-only профиле. Это source/local delivery с явно красным глобальным platform gate, не готовность к merge/deploy всего проекта.
