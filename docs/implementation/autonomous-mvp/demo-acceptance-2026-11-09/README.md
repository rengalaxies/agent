# Единая приёмка demo-MVP — 09.11.2026

**Выбранный технический путь принят в ограниченном авторском пилоте. Защита и
коммерческая/командная полезность ещё не приняты.** До19ноября приоритет — репетиция
и материалы показа. Новых функций и модельных вызовов для этого не требуется.

## Продукт и границы показа

Агент сопоставляет поддерживаемые изменения API в PR с вызовами других сервисов,
показывает возможное влияние и места в коде в одном обновляемом Jira-комментарии.
Bitbucket обнаруживается через polling. Confluence читается только по явной ссылке
в Jira: текст и таблицы, без изображений, вложений, обхода дочерних страниц и поиска
по всему workspace. Документация — контекст, а не доказательство соответствия кода
требованиям. Отсутствие находок не означает совместимость; интеграционные тесты
поведения приложений в этих прогонах не запускались. Модель OFF.

## Фактическая приёмочная таблица

| Проверка | Где и результат | Доказательство |
|---|---|---|
| Immutable release: сборка/скачивание/install/recovery | CI exact a02ffa7 PASS; это не установка на Cloud.ru | [run42479463480](https://github.com/rengalaxies/agent/actions/runs/42479463480) |
| Установка и update отдельного worker | Реальная dm-p1-ui, SHA a02ffa7, UID995, loopback8092, config0640/secrets0600, autostart enabled, model OFF | [target rollout](../jira-presentation-2026-11-08/LIVE-ROLLOUT.md) |
| Новый IP и доступ | 82.202.141.50; SSH с прежним pinned key; GitHub/Bitbucket/Jira HTTPS отвечают; старый IP освобождён | [IP recovery](../jira-presentation-2026-11-08/IP-REPLACEMENT.md) |
| Поддерживаемое изменение PR | /orders/summary→/orders/statistics; USEFUL/OPERATION_REMOVED, Reporting client.py:14;72.437s до Jira | [живой цикл](../live-chain-2026-11-08/README.md) |
| Исправление PR | Исходный файл восстановлен; ABSTAINED/no_supported_delta, прежнее предупреждение снято;75.761s | [corrected evidence](../live-chain-2026-11-08/corrected.json) |
| Недоступная документация | Честное «текст не использован», без старойv4; затем точное восстановление описания и документации | [недоступная страница](../confluence-unavailable-2026-11-08/README.md) |
| Confluence меняется без изменения кода | v4→v5→v6 автоматически отражены в том же комментарии; новый текст найден в полном outbox, исходное содержимое восстановлено | [обновление версии](../confluence-version-2026-11-09/README.md) |
| Повторное обнаружение | Два реальных polling-checkpoint продвинулись, resource/очередь/история и Jira body/updated не изменились | [идемпотентный polling](../poll-idempotence-2026-11-09/README.md) |
| Одна публикация и понятный вывод | comment10046 сохраняется, список[10013,10046] без дублей; русский summary, полный документ остаётся в outbox | [live proof](../jira-presentation-2026-11-08/LIVE-VERIFICATION.json) |
| Restart и backup нового релиза | Restart на ВМ PASS; scratch restore114файлов/6SQLite PASS; очередь/комментарий сохранены | [backup и откат](../jira-presentation-2026-11-08/LIVE-ROLLOUT.md) |

Задержки — одиночные фактические наблюдения при polling60s, не SLA и не человеческие
минуты. Два FAILED intents относятся к негативному PR3 без Jira, reason
exactly_one_linked_jira_required; это не два отказа выбранного happy path.

## Текущие точки показа

- [Bitbucket Orders PR4](https://bitbucket.org/rengalaxies/agent-pilot-orders/pull-requests/4), ветка KAN-9-summary-to-statistics, OPEN, не сливать.
- [KAN-9/comment10046](https://rengalaxies.atlassian.net/browse/KAN-9?focusedCommentId=10046).
- [Confluence360725](https://rengalaxies.atlassian.net/wiki/spaces/OOP/pages/360725), сейчас v6 с исходным восстановленным текстом.
- Orders head01b6ebfa4cefb633f9606b2bded4f2e00c3be96d, Reporting6ebf07174eb9ef4018a98ccf14da1cb94b6a69e3.
- Worker: /etc/agent-bitbucket/service.json; current /opt/agent-bitbucket/current;
  state /var/lib/agent-bitbucket/live-acceptance; статус только через приватный SSH-туннель.

Демонстрация начинается и заканчивается восстановленным api.py. История тестовых
коммитов и версий Confluence сохраняется. Main и модель не меняются.

## Открытые зоны — не выдавать за PASS

1. Репетиция владельцем по инструкции, запись и обновлённая презентация — PENDING.
2. Независимый проект, человеческие минуты, сравнение с coding agent, FP/FN и польза
   команде — NOT_MEASURED/NOT_RUN. Owner feedback не равен независимой оценке.
3. Исходный GitHub App/webhook/HTTPS LIVE gate — отдельно не закрыт. Основной GitHub
   коннектор сохранён; Bitbucket polling не выдаётся за GitHub/webhook acceptance.
4. Reboot, production restore и downgrade именно текущего a02ffa7 на целевой ВМ — NOT_RUN.
   Исторические host-reboot/restore c405 описаны в PR102; CI recovery отдельно PASS.
5. Настоящий отзыв прав/истечение token, широкий Confluence outage, внешние webhook
   redelivery и неоднозначный HTTP create не проверялись новыми контрольными пачками.
   Невалидная страница и повторный polling — другие условия.
6. Семантика произвольных изменений/требований, runtime compatibility, изображения и
   неявная документация находятся вне продемонстрированного профиля.

## Следующие две пачки

**Репетиция5–7минут:** владелец проходит [REHEARSAL.md](REHEARSAL.md), проверяем понятность
вывода и фиксируем фактический результат без выдуманной независимости/метрик.
**Материалы защиты:** запись живого прогона и компактные слайды проблема→архитектура→
демо→ограничения; запасные evidence на случай недоступности сети, с явной пометкой записи.

Документы этой приёмки подготовлены в PR104; ранние эксплуатационные доказательства
и пакет участника — PR102. Проверять состояние их интеграции отдельно от установленного
SHA. Данный отчёт не объявляет все M1–M6 DONE.
