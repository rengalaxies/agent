# Будущая LIVE-приёмка — сейчас NOT_RUN / BLOCKED

Только два выделенных private pilot-repo и согласованный Jira test project.
MODEL OFF. Сначала owner/M3 действия из OWNER-AND-M3.md, App/Jira identity probes,
настоящий HTTPS и установка согласованного exact release SHA. Детерминированный режим
должен быть явно назван в пользовательском комментарии. Не запускать ручной анализ
вместо проверки автономной доставки. Приёмка после подготовки не закрывается CI.

1. Сохранить manifest/archive SHA256, installed code SHA, loaded process/release/core
   identity и extractor profile; `/status`/doctor, приватный `/graph`, журналы sync/timer.
   Установка на CI не считается установленной M3. Подтвердить реальные repo IDs и main
   pins из prepared.json; Git mirror read и branch API должны согласоваться.
2. Создать настоящую Jira-задачу с label `agent-pilot-m2`, summary
   `Orders: reduce GET /orders default page_size from 100 to 20`, description с явным
   условием нашего теста R-pilot-export-all (60 ID). Это не факт о клиенте. Сервис сам
   публикует preliminary influence/limitations. Сохранить URL/key, semantic digest,
   issue updated timestamp отдельно, Jira event identifier и request/result ID.
3. Создать PR в **agent-pilot-orders**, base `main`, head `pilot-page-limit`, title
   `<НАСТОЯЩИЙ_JIRA_KEY> Orders: reduce GET /orders default page_size 100 to 20`.
   Не придумывать ключ. Head branch из prepared.json, base проверяется API в момент
   сценария. Найденная static связь Reporting и POSSIBLE_TRUNCATION не являются
   выполненным тестом: сервис должен оставить test_executed=false. Отдельно исполнить
   authored runtime harness и записать его результат как LOCAL/fixture execution.
4. Сохранить PR comment ID/URL, author, base/head, Jira links и проверяемые
   repository@commit:path#line / evidence. Обновить **тот же** PR fast-forward:
   push `pilot-restored` в `pilot-page-limit`. Это descendant, force-push не нужен.
   Сервис обновляет существующий комментарий; старый риск не остаётся текущим.
   Исторический результат/старый head сохраняются только как история.
5. Redeliver настоящие GitHub App deliveries в UI, записать старый/new delivery ID,
   number of events/jobs/POST и один текущий comment ID. Для Jira выяснить реальную
   возможность redelivery: обычное update не является повтором того же события.
   Если точную Jira redelivery получить нельзя — подпункт NOT_RUN, не подделывать её.
   Отдельно проверить порядок запоздалого события и новый head актуальным API fetch.
6. Создать нейтральный `pilot-docs-only` PR и задачу `Document GET /orders pagination`
   без service scope: Reporting и Orders оба декларируют маршрут, уверенный target
   не выбирается. Отдельная задача `GET /orders changes page size` без service scope
   проверяет ambiguity; documentation wording не заменяет этот отдельный контроль.
7. Собственные GitHub issue_comment и Jira comment события должны реально поступить.
   Сохранить signed delivery ID и bot login/accountId, затем показать отсутствие новых
   analyses/comments из них. Простое отсутствие событий не доказывает отсутствие цикла.
8. Управляемый API отказ — только тестовый доступ/App/egress proxy, заранее остановив
   другие действия с тем же credential. Сохранить настоящий status/request ID, видимое
   pause/failure/notice, bounded retry и восстановление/reconciliation. Если отозван
   private key, access token может жить до expiry: не называть его немедленным 401.
   Не вызывать rate limit production. Если реальный отказ не контролируется — NOT_RUN.
9. После принятия задания перезапустить единственный test worker по M3 runbook.
   Сверить durable event/job, author+marker adoption и отсутствие второго POST.
   Для потерянного события временно отключить **только test webhook**, изменить head,
   дождаться reconciliation, вернуть webhook. Записать реальный таймер/восстановление.
10. Гонка GET → изменение внешней версии → POST/PATCH → GET: провести через согласованную
    test delay/trace, сохранить порядок, время видимости старого тела, stale notice и
    новый result. Повторить с post-check API error и restart. БД/API не атомарны;
    при API/worker outage жёсткой границы устаревания нет. Без трассы LIVE race NOT_RUN.

Для каждого пункта заполнить live-record.json: уровень LOCAL/CI/LIVE, PASS/FAIL/NOT_RUN,
полные SHA и URLs, request/event ID, semantic version/base/head, фактические действия.
Не назначать фиктивные человеческие минуты. DONE M2 требует реального Jira → связанный
PR → обновлённый результат, duplicates/new head/API error/self-loop; любое существенное
отсутствие остаётся PARTIAL/BLOCKED. Независимая M4/клиентская полезность сюда не входят.

## Очистка

Остановить test worker и отключить только test webhook; сохранить проверенные evidence
без секретов и read-only state/history backup. Закрыть созданные pilot PR, пометить/закрыть
созданные Jira-задачи по label/записанным IDs, удалить только собственные bot comments
при согласованной политике хранения. Для Jira Delete own comments требуется отдельное
право оператора, worker его не получает ради cleanup. Не удалять неизвестные задачи,
main branches, App или repos автоматически. Удаление/архивирование всего контура —
отдельное явное решение владельца после сохранения доказательств. Отозвать test token/key
и App installation access, если контур больше не нужен. Не снимать доступ с production.

Откат M3 — её backup/update/rollback/restore runbook, одним оператором; SQLite restore
не отменяет внешние комментарии и не обещает транзакции между системами.
