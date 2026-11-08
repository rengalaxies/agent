# Демо-MVP: проверенные сценарии и границы — 08.11.2026

Рабочий LIVE-пилот Jira + Bitbucket + явно связанный Confluence на dm-p1-ui.
Сервис agent-bitbucket, UID995, loopback8092, polling60с, model OFF.
Фактический установленный code SHA: `c4053c6d4a959ff4d0e159c3cb1913fae87f25fb`.
Исходный agent-service5fb и демо сохранены. Это не приёмка полного MVP.

## Единая матрица

PASS означает выполнение именно указанного ожидания в указанной среде.
EXPECTED_REJECTION — проверенный отказ публикации, не успешная интеграция.
NOT_RUN нельзя включать в число пройденных проверок. Набор авторский, маленький:
процент точности/FP/FN и человеческая польза по нему не выводятся.

| ID | Сценарий | Ожидание | Факт | Вердикт / среда | Доказательство |
| --- | --- | --- | --- | --- | --- |
| Q1 | Переименование используемого API | Найти потребителя старого маршрута | USEFUL; OPERATION_REMOVED; Reporting client.py:14; comment10046 | PASS; Cloud.ru, постоянный LIVE | [JSON](../bitbucket-worker-2026-11-04/vm-new-pr-2026-11-07/vm-analysis.json) |
| Q2 | Исправление того же PR | Снять предупреждение в том же комментарии | ABSTAINED/no_supported_delta; findings0; generation2; тот же10046 | PASS; Cloud.ru, постоянный LIVE | [JSON](../bitbucket-worker-2026-11-04/vm-new-pr-2026-11-07/restored-verification.json) |
| Q3 | Правка README без API-изменения | Не выдать API delta | ABSTAINED/no_supported_delta; findings0 | PASS; Локальный worker с реальным Bitbucket-кодом | [JSON](../bitbucket-worker-2026-11-04/docs-control-live.json) |
| Q4 | PR без Jira-ключа | Не писать в случайную задачу | PR3: FAILED intent exactly_one_linked_jira_required; comment_id=null | EXPECTED_REJECTION; Cloud.ru, постоянный LIVE | [JSON](../bitbucket-worker-2026-11-04/vm-persistent-live-2026-11-07/acceptance.json) |
| D1 | Изменение явно связанной Confluence-страницы | Автоматически обновить прежний комментарий | v3→v4; comment10011; 51.88с observation; manual reconcile0 | PASS; Cloud.ru, постоянный LIVE | [JSON](../bitbucket-worker-2026-11-04/vm-persistent-live-2026-11-07/acceptance.json) |
| D2 | Удаление ссылки из описания Jira | Убрать старый документационный контекст | Контекст удалён, старый текст не использован; тот же10046 | PASS; Cloud.ru, постоянный LIVE | [JSON](../reliability-2026-11-08/links.json) |
| D3 | Недоступная страница Confluence | Явно сообщить недоступность без cached текста | Реальный missing-page ответ → UNAVAILABLE; старый текст отсутствует | PASS; Cloud.ru, постоянный LIVE | [JSON](../reliability-2026-11-08/links.json) |
| D4 | Возврат исходной ссылки | Вернуть актуальный контекст без дубля | Исходное описание восстановлено; один marker/comment10046 | PASS; Cloud.ru, постоянный LIVE | [JSON](../reliability-2026-11-08/links.json) |
| R1 | Контролируемый transport-fault исходящих API | Показать ошибку и восстановиться, не менять Jira старым результатом | reconcile_failed; health200 только liveness; body unchanged; fault снят | PASS; Cloud.ru; unit-scoped proxy fault, не падение провайдера | [JSON](../reliability-2026-11-08/outage.json) |
| R2 | Restart LIVE-worker | Сохранить native receipts и очередь | Новый PID/checkpoint; те же ресурсы и комментарии | PASS; Cloud.ru | [JSON](../bitbucket-worker-2026-11-04/vm-persistent-live-2026-11-07/acceptance.json) |
| R3 | Восстановление очереди и графа | Поднять matching state из backup с сохранением идентичности | Active queue+core реально заменены из backup; counters/IDs/generations совпали | PASS; Cloud.ru; same code/config, не whole-VM disaster recovery | [JSON](../reliability-2026-11-08/production-restore.json) |
| R4 | Reboot хоста | Автозапуск сервисов и демо, сохранение state | Boot ID сменился; оба сервиса/демо вернулись; очередь сохранена | PASS; Cloud.ru; HTTP18081=401 ожидаем | [JSON](../reliability-2026-11-08/reboot-verification.json) |
| R5 | Ротация истекающих credentials | Пережить отзыв старых, API/Git работают с новыми | Новые токены до08.11.2027; три старых отозваны; post-reboot API/Git PASS | PASS; Mac + два сервиса на Cloud.ru | [JSON](../reliability-2026-11-08/tokens-after-reboot.json) |
| N1 | Полное падение провайдера,429,неоднозначная запись | Не публиковать неподтверждённое; восстановиться без дублей | На target в этой серии не выполнялось | NOT_RUN; Будущая fault acceptance | — |
| N2 | Code update/rollback отдельного Bitbucket-контура | Проверить смену release и matching state contract | На target не выполнялось; первая установка не имеет предыдущего Bitbucket-релиза | NOT_RUN; CI recovery не заменяет target acceptance | — |
| N3 | Независимая оценка качества и пользы | Измерить FP/FN, понятность, действия и полный труд | Авторские кейсы; usefulness_confirmed=false; человеческие метрики отсутствуют | NOT_RUN; Нужен независимый участник | — |

## Как работает показанная часть

Worker опрашивает Bitbucket, фиксирует PR base/head и снимки двух репозиториев,
обновляет выделенные bare mirrors и строит/использует persistent graph по коду.
Изменённый API сопоставляется с вызовами других сервисов в пределах статического
профиля http-requests-6. Результат содержит commit/path/line и неизвестные.
Jira-цель определяется единственным явным KAN-ключом PR; native comment receipts
сохраняются в очереди. Новый head/документационный контекст вызывает пересчёт
и обновление прежнего комментария. Публикация происходит в Jira, не в Bitbucket PR.

Confluence читается только по явным ссылкам в описании Jira: текст и обычные таблицы,
не более5страниц/4000символов на страницу. Нет обхода дочерних страниц, изображений
или вложений. Смысловое доказательство соответствия требований коду не реализовано.
Включение требования в контекст не делает requirement_unknown подтверждённым.

## Воспроизводимый показ уже выполненного цикла

1. [PR4](https://bitbucket.org/rengalaxies/agent-pilot-orders/pull-requests/4),
   commit dda44a2c: переименование /orders/summary → /orders/statistics.
2. [KAN-9, comment10046](https://rengalaxies.atlassian.net/browse/KAN-9?focusedCommentId=10046):
   результат первого поколения сохранён в Q1 — Reporting client.py:14.
3. Тот же PR, исправляющий commit773000a: исходный маршрут восстановлен.
4. Текущий комментарий — ABSTAINED/no_supported_delta; первое предупреждение
   смотрим в сохранённом JSON/скриншоте, оно уже заменено актуальным результатом.

Не утверждать, что текущий PR по-прежнему показывает ошибку: итоговый diff пуст,
PR открыт и не слит. Повторная интерактивная демонстрация требует нового
согласованного изменения и ожидания polling; historical JSON не выдаётся за live.

## Готовность M1–M6

| Пачка | Текущая граница |
| --- | --- |
| M1 | Model OFF проверен; показ детерминированный, модельный вклад не заявлен |
| M2 | LIVE Jira–Bitbucket polling и same-comment цикл PASS на авторских кейсах; старый GitHub403 и публичный webhook отдельно не закрыты |
| M3 | Отдельная установка, restart, backup/active-state restore, reboot PASS; code update/rollback target NOT_RUN; Bitbucket box renderer отсутствует |
| M4 | Граф двух авторских сервисов и code evidence проверены; независимый проект/полнота охвата не квалифицированы |
| M5 | Человеческие качество/польза/FP/FN/труд NOT_RUN, USEFUL анализатора их не заменяет |
| M6 | Рабочий demo-путь готов; репетиция, резервная запись и итоговые материалы/приёмка ещё нужны |

## Размещение, доступ и откат

Текущая public-free конфигурация: [service.live.json](../bitbucket-worker-2026-11-04/vm-persistent-live-2026-11-07/service.live.json).
Очередь `/var/lib/agent-bitbucket/live-acceptance/service/service.sqlite`, граф рядом
в `core`; историческое имя каталога не означает one-shot режим сейчас.
[Приватный status helper](../bitbucket-worker-2026-11-04/vm-install-2026-11-07/status.py)
запускается на ВМ через pinned SSH и sudo, не печатает Bearer token.
Журналы: `sudo journalctl -u agent-bitbucket -n 100 --no-pager`.
Остановка публикации: `sudo systemctl stop agent-bitbucket`.
Полные границы restore/отката: [Reliability](../reliability-2026-11-08/README.md)
и [LIVE handover](../bitbucket-worker-2026-11-04/vm-persistent-live-2026-11-07/README.md).
Старые backups содержат отозванные credentials: сохранить/применить текущие секреты
до запуска, не стирать native receipts и не подменять LIVE-БД старой dry_run-БД.
Приложенные Python helpers — исторические процедуры с side effects, не unattended
инсталлятор; читать scope/preconditions перед ручным повторением на пилоте.

Следующая продуктовая пачка: независимый прогон нескольких кейсов по этой матрице,
понятность комментария/графа и короткая репетиция к19ноября. Новые интеграции пока
не требуются. Никакого полного PASS для модели, коммерческой пользы или runtime
совместимости по этой матрице не заявлено.
