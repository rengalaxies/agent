# Живой путь Jira + Bitbucket + Confluence — 08.11.2026

PASS на существующей Cloud.ru dm-p1-ui,82.202.141.50, release a02ffa7854dcc38cecc7fe5c5317466059926cd9, model OFF.

Обычный постоянный worker с polling60s, без ручного reconcile и синтетического webhook.
Открытый [Orders PR4](https://bitbucket.org/rengalaxies/agent-pilot-orders/pull-requests/4),
[Jira KAN-9/comment10046](https://rengalaxies.atlassian.net/browse/KAN-9?focusedCommentId=10046),
явно связанная [Confluence360725v4](https://rengalaxies.atlassian.net/wiki/spaces/OOP/pages/360725).
Main не менялся; PR оставлен открытым и не слит.

| Этап | Фактический результат |
|---|---|
| Переименовать GET/orders/summary в /orders/statistics | Commit b5a401cc87127546222a12b6e6aceab7a72d4145 |
| Автоматический анализ | Generation7,DONE,USEFUL,OPERATION_REMOVED,reporting/client.py:14 |
| Публикация | Тот же comment10046, предупреждение и документацияv4;72.437s от timestamp коммита |
| Вернуть прежний маршрут | Commit01b6ebfa4cefb633f9606b2bded4f2e00c3be96d |
| Автоматический пересчёт | Generation8,DONE,ABSTAINED/no_supported_delta,findings=[] |
| Обновление вывода | Тот же comment10046, прежнее предупреждение снято;75.761s от timestamp коммита |

Jira comment IDs до/после:[10013,10046], новых комментариев нет. SHA256 восстановленного
api.py совпал с исходным файлом head773000a30670. История содержит оба тестовых коммита;
force-push и удаления истории не было. Источники Git CURRENT. Для удалённой операции
dependency_freshness=STALE относится к сохранённому пути из base, отсутствующему в head;
это не подмена свежести Git и не заявленная актуальная связь в исправленном коде.

Задержки — два наблюдения по timestamp Bitbucket commit и Jira updated, не SLA,
не замер времени человека и не статистика качества. Интеграционные тесты поведения
сервисов не запускались. Confluence прочитана и процитирована с версией; смысловое
соответствие требований коду отдельно не проверялось. Независимая человеческая оценка
и переносимость на другой проект этой пачкой не закрыты.

Доказательства:[impact.json](impact.json),[corrected.json](corrected.json).
Скриншоты фактического Jira UI сохранены локально:/tmp/pilot-chain-impact.png,
/tmp/pilot-chain-corrected.png. Полный необрезанный результат анализа остаётся в БД worker.

## Повторение на защите (5–7 минут)

1. Открыть KAN-9 и её ссылку на текущую Confluence (после контрольного теста — v6); показать потребителя Reporting client.py:14.
2. Открыть api.py именно в ветке KAN-9-summary-to-statistics, не main.
3. Заменить только строку маршрута /orders/summary на /orders/statistics и сделать commit с KAN-9.
4. Дождаться штатного polling и обновить Jira. Показать операцию, Reporting, место вызова,
   действие для проверки и ограничения. Обычно это занимает около1–2минут в данном прогоне;
   при задержке проверять приватный status/журнал, не запускать второй worker/reconcile.
5. Вернуть маршрут /orders/summary отдельным commit. Дождаться пересчёта.
6. Показать тот же комментарий с сообщением о снятом прежнем предупреждении;
   отсутствие находок не выдавать за подтверждённую совместимость.
7. Оставить ветку в восстановленном состоянии и PR открытым. Не включать Pipelines,
   платные ресурсы или модель ради этого сценария.

Текущая версия документа после [контроля обновления](../confluence-version-2026-11-09/README.md) — v6; исходный текст восстановлен. Указанияv4 выше относятся к историческому первому прогону.
