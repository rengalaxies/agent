# Пачка07: API и общий контракт

14.11.2026. **TECHNICAL_PREPARATION; LIVE_NOT_RUN.** Общий контракт, карта официальных API и исполнимая диагностическая проба подготовлены. Полный AC07 остаётся открыт: обновление результата пока не проверено на реальных tenant API обоих трекеров.

- [ADR: identity, версии, marker, ошибки, границы08/09](../../adr/001-tracker-publication.md).
- [Карта API, ссылки и синтетические примеры](api-map.md).
- [План и журнал](../../superpowers/plans/2026-11-14-impactmap-batch07-trackers.md).
- Код: src/agent_service/connectors/{base,tracker_contract}.py; tools/agent_service/tracker_api_probe.py; tests/service/test_tracker_{contract,api_probe}.py.

## Что выполняет проба

Это короткий text-only протокол к выделенной задаче: GET задачи с проверкой immutable ID и allowlisted board/queue → полный пагинированный список → POST одного диагностического комментария → перечитывание → PATCH **того же** native ID → два перечитывания и проверка единственного своего marker/bot автора. Resume успешной пробы повторяет чтение, без новой записи.

Журнал probe.json создаётся **до** первой записи, pending-write сохраняется с fsync файла, atomic replace и fsync каталога; создание новых output-каталогов синхронизируется через их родителей. Один output одновременно закрыт flock. Marker уникален для журнала; в нём хранятся non-secret config hash, scoped identity, фаза/результат, коды операций. Task description, token и provider error bodies не сохраняются. Для каждого трекера отдельный output. Это диагностический комментарий, он остаётся на тестовой задаче; удаления/изменения чужих комментариев нет.

Если POST закончился таймаутом или процесс прервался, повторить **с тем же output/config**. Найденный собственный marker позволяет продолжить; отсутствие оставляет create_outcome_unresolved и не приводит к повторному POST. Не удалять/не сбрасывать журнал и не переключать output ради повтора неизвестного create. После PATCH с неизвестным исходом повторное чтение подтверждает состояние; повторный PATCH при необходимости идёт только к прежнему собственному ID. Проба не заменяет продуктовую очередь/backoff и не выполняет автоматические сетевые повторы.

В LOCAL_HTTP режиме библиотечный client указывает на127.0.0.1, используется синтетический token. CLI принимает только закреплённые HTTPS SaaS origins, redirects запрещены существующим HttpClient; returned Link проверяется по host/path/курсорным параметрам, передаётся только реконструированный query. Self-hosted/прокси endpoints требуют отдельного решения, не включены молча.

## Запуск на настоящих выделенных целях

Нужны разрешённая тестовая карточка Kaiten и задача в отдельной очереди Яндекс Трекера, native bot IDs, scope IDs и токены чтения/создания/редактирования своих комментариев. В config нет секретов; token хранится в указанной env-переменной. Не передавать секреты в чат, Git или аргумент командной строки. Примеры содержат placeholders и не являются настроенными доступами.

1. Скопировать kaiten-config.example.json или yandex-config.example.json в ignored/private файл, указать свои реальные immutable task/scope/bot/tenant IDs. Yandex auth_scheme выбирается отдельно от org_header; для IAM — Bearer, для OAuth — OAuth; org_header соответствует типу организации.
2. Через существующий безопасный способ загрузить token в env. Не печатать его и не вставлять в shell history.
3. Сначала read-only (default), проверить scope. После подготовки этой же выделенной цели запустить с --write. Runtime/VM не меняются.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.agent_service.tracker_api_probe --config work/private-kaiten-probe.json --output work/batch07/kaiten-live
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.agent_service.tracker_api_probe --config work/private-kaiten-probe.json --output work/batch07/kaiten-live --write
```

Для Яндекса заменить config/output отдельными путями. Здесь python — существующий app venv; новых зависимостей нет. Повторять с прежним output, не создавать новый run для неизвестной записи. Exit1: FAIL/UNKNOWN, смотреть non-secret локальный журнал; exit0 READ_ONLY не равен успешной записи. Read-only после неизвестной записи сохраняет UNKNOWN и возвращает exit1; старый write outcome не заменяется успешным чтением. PASS с environment=REAL_API подтверждает только этот короткий маршрут на этой цели; не весь e2e08/09/10.

## Что проверено и что требуется

| AC07 | Доказательство / статус |
|---|---|
| Карта чтения/комментариев/доступа обоих API | DOCS_VERIFIED, api-map.md с первичными источниками |
| Общие task/comment identity, version/marker/retry | Код, ADR и unit tests; runtime Jira ID не мигрировали |
| Тестовые примеры create/update | Локальный настоящий HTTP stand с authored responses, LOCAL_HTTP; не сервис поставщика |
| Jira продолжает работать | Профильные регрессии; production стенд в07 не трогали и live не перепроверяли |
| Выбранный способ обновления подтверждён API-пробой | **LIVE_NOT_RUN для обоих провайдеров**, нужны реальные доступы/цели |

Проверены имена файлов в .private с исключением venv/dependencies и имена текущих env-переменных на kaiten/yandex/tracker, а также project config file inventory. Настроенных целевых credentials/config не обнаружено. Затем владелец прямо подтвердил: «Доступов нет, аккаунты пока тоже не создавал». Аккаунты не создавались, секреты не запрашивались в тексте чата. Ни одного tenant HTTP-запроса/комментария не выполнено. Для закрытия live AC нужен путь к private config и способ безопасной подачи token для каждого трекера. Не требуется отправлять сам token в чат.

Новые providers не подключены в service settings/envelope/worker. На следующем этапе можно реализовывать локальный адаптер08 по контракту, но полный live AC07/08 останется открытым до доступа. Это не завершает независимую оценку06.

## Локальные квитанции

[kaiten-local-proof.json](kaiten-local-proof.json) и [yandex_tracker-local-proof.json](yandex_tracker-local-proof.json): настоящие HTTP-запросы только к авторскому localhost stand, по4 посторонних комментария, page size2, POST→PATCH→повтор без записи; ровно1 свой комментарий. Это не API поставщиков. В трассах заголовки исключены, все тексты/ID синтетические.

[Ревью и исправления](review.md), [лог финальных тестов](tests.log), [приёмка](acceptance.json). Fsync-тест проверяет порядок системных вызовов; реальная потеря питания не моделировалась. Case lock — на один output, а не глобальная блокировка всех возможных ручных запусков.
