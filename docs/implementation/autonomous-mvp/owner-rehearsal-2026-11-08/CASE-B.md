# Случай B — текущий результат на момент подготовки

Read-only снимок comment10046: 2026-11-08T08:05:06.505627+00:00. Это сохранённый текст,
а [текущую задачу](https://rengalaxies.atlassian.net/browse/KAN-9?focusedCommentId=10046)
можно открыть отдельно. Источник: [preflight.json](preflight.json).

Вывод о влиянии не сделан

No supported behavior change was found; arbitrary semantic changes are not classified.

Что может затронуть

Потребители не названы (no_supported_delta). Это не доказывает отсутствие влияния.



Почему и через какой путь

Путь влияния не построен.



Что проверить

Изменения вне поддерживаемого профиля сервис не классифицирует: их проверяет обычный review.



Неизвестные и свежесть

git:bb.orders: CURRENT, проверено 2026-11-08T07:43:42.335333Z



git:bb.reporting: CURRENT, проверено 2026-11-08T07:43:42.335333Z



Версии

PR rengalaxies/agent-pilot-orders#4: base , head 773000a30670



Связанные задачи Jira: KAN-9



Поколение анализа: 5



code_version: 0.1.0+gc4053c6d4a95.linux-x86_64-cp312



constitution_version: agent-service-v1.0:100bcad3db9c



correlation_id: 307d1f1e624346ecbdf070212694bf64:1



graph_version: graph-8



model: Детерминированный результат (модельный отчёт не представлен)



profile: http-requests-6



schema_version: 2.2



снимок bb.orders (base): 5d405f22a0d9



снимок bb.orders (head): 773000a30670



снимок bb.reporting (consumer): 6ebf07174eb9



Статус: ABSTAINED, код: no_supported_delta



Связанная документация Confluence

Confluence Пилот Orders–Reporting — требования для KAN-8 — версия 4, https://rengalaxies.atlassian.net/wiki/pages/viewpage.action?pageId=360725



Документированные требования; соответствие коду отдельно не подтверждено.



Пилотные требования Orders и Reporting Авторские условия демонстрации прототипа. Ответственный за проверку — участник пилота. Эти требования служат тестовыми данными. Область Сервис Orders предоставляет GET /orders и GET /orders/summary. Reporting использует обе операции. Идентичность Orders — https://orders.pilot.invalid. Отдельная GET /orders сервиса Reporting относится к другому сервису. Требования | ID | Требование | Проверка | R-SUMMARY-AVAILABLE | Orders сохраняет GET /orders/summary, пока Reporting load_summary вызывает её. | Перед удалением найти Reporting client.py и согласовать миграцию вызова. Выполнить интеграционную проверку ответа. | R-EXPORT-COMPLETE | Reporting должен получать полный набор заказов за день. Тестовый набор содержит 60 заказов. Уменьшение страницы со 100 до 20 требует проверки пагинации. | Сравнить полученные IDs с ожидаемыми 60 IDs, проверить отсутствие пропусков и дублей. | R-SCOPE | Одноимённые маршруты разных сервисов различаются по идентичности сервиса. | Изменение Orders не должно приписываться Reporting audit_api.py. | R-DOCS-CONTROL | Правка README без изменения кода операций не создаёт API delta. | Ожидать отсутствие предупреждения об изменении операции. Границы вывода Статический анализ указывает возможное влияние. Подтверждение совместимости требует выполненной проверки. Документация может конфликтовать с кодом — такой конфликт должен быть указан. Модель в текущем пилоте выключена. Связь с задачей Контрольная задача KAN-8, Bitbucket Orders PR2. При исправлении PR восстановление операции должно приводить к пересчёту результата. Контроль актуальности документа CF-POLL-ACCEPTANCE-20261107: при обновлении требования агент должен повторно прочитать связанную страницу и указать её актуальную версию. CF-VM-LIVE-20261107: контроль чтения актуальной документации агентом на Cloud.ru. CF-PERSISTENT-LIVE-20261107: автоматическая проверка актуальности через постоянный worker.



agent-service marker=bbc3df769e4f04d5 digest=346f2db28064c2e0addfc28f21bf3f707289b7f2452b9347dcd08bed0c6d349a generation=5

