# Случай A — сохранённый результат до исправления

Это исторический снимок Jira comment10046 от08.11.2026, поколение1.
Он не является текущим комментарием. Исходный JSON: [vm-analysis](../bitbucket-worker-2026-11-04/vm-new-pr-2026-11-07/vm-analysis.json).

Возможное влияние изменения

1 consumer(s) of the changed operation(s); 1 with a classified risk. Static profile; tests not executed.

Что может затронуть

reporting: команда не определена



Почему и через какой путь

Изменение orders GET /orders/summary: OPERATION_REMOVED None -> None



Находка OPERATION_REMOVED у reporting: вызов bb.reporting:client.py:14, использование SINGLE_REQUEST_OBSERVED, связь STALE, требование не задано



Факт в пределах профиля: reporting calls GET /orders/summary of orders at client.py:14; observed usage SINGLE_REQUEST_OBSERVED. Применимость: Pinned snapshots only; static profile http-requests-6. Неопределённость: LOW. Основания: код bb.reporting@6ebf07174eb9:client.py#L13-16; код bb.reporting@6ebf07174eb9:client.py#L14-14; код bb.orders@5d405f22a0d9:api.py#L14-15



Гипотеза: OPERATION_REMOVED: If the changed declaration governs this call. Применимость: Pinned snapshots only; static profile http-requests-6. Неопределённость: MEDIUM. Основания: код bb.reporting@6ebf07174eb9:client.py#L14-14; код bb.orders@5d405f22a0d9:api.py#L14-15



Путь: reporting -> orders GET /orders/summary. Основания: код bb.reporting@6ebf07174eb9:client.py#L14-14; код bb.orders@5d405f22a0d9:api.py#L14-15



Что проверить

reporting: Exercise the changed operation against this consumer's independent expectations



Неизвестные и свежесть

requirement_unknown (reporting)



owner_unknown (reporting)



пробел unmapped_call bb.reporting:client.py



git:bb.orders: CURRENT, проверено 2026-11-08T07:07:48.300609Z



git:bb.reporting: CURRENT, проверено 2026-11-08T07:07:48.300609Z



Версии

PR rengalaxies/agent-pilot-orders#4: base , head dda44a2c0345



Связанные задачи Jira: KAN-9



Поколение анализа: 1



code_version: 0.1.0+gc4053c6d4a95.linux-x86_64-cp312



constitution_version: agent-service-v1.0:100bcad3db9c



correlation_id: 547a03c25fdc4e7d85bebec933eb2e7f:1



graph_version: graph-5



model: Детерминированный результат (модельный отчёт не представлен)



profile: http-requests-6



schema_version: 2.2



снимок bb.orders (base): 5d405f22a0d9



снимок bb.orders (head): dda44a2c0345



снимок bb.reporting (consumer): 6ebf07174eb9



Статус: USEFUL, код: impact_found_within_profile



Связанная документация Confluence

Confluence Пилот Orders–Reporting — требования для KAN-8 — версия 4, https://rengalaxies.atlassian.net/wiki/pages/viewpage.action?pageId=360725



Документированные требования; соответствие коду отдельно не подтверждено.



Пилотные требования Orders и Reporting Авторские условия демонстрации прототипа. Ответственный за проверку — участник пилота. Эти требования служат тестовыми данными. Область Сервис Orders предоставляет GET /orders и GET /orders/summary. Reporting использует обе операции. Идентичность Orders — https://orders.pilot.invalid. Отдельная GET /orders сервиса Reporting относится к другому сервису. Требования | ID | Требование | Проверка | R-SUMMARY-AVAILABLE | Orders сохраняет GET /orders/summary, пока Reporting load_summary вызывает её. | Перед удалением найти Reporting client.py и согласовать миграцию вызова. Выполнить интеграционную проверку ответа. | R-EXPORT-COMPLETE | Reporting должен получать полный набор заказов за день. Тестовый набор содержит 60 заказов. Уменьшение страницы со 100 до 20 требует проверки пагинации. | Сравнить полученные IDs с ожидаемыми 60 IDs, проверить отсутствие пропусков и дублей. | R-SCOPE | Одноимённые маршруты разных сервисов различаются по идентичности сервиса. | Изменение Orders не должно приписываться Reporting audit_api.py. | R-DOCS-CONTROL | Правка README без изменения кода операций не создаёт API delta. | Ожидать отсутствие предупреждения об изменении операции. Границы вывода Статический анализ указывает возможное влияние. Подтверждение совместимости требует выполненной проверки. Документация может конфликтовать с кодом — такой конфликт должен быть указан. Модель в текущем пилоте выключена. Связь с задачей Контрольная задача KAN-8, Bitbucket Orders PR2. При исправлении PR восстановление операции должно приводить к пересчёту результата. Контроль актуальности документа CF-POLL-ACCEPTANCE-20261107: при обновлении требования агент должен повторно прочитать связанную страницу и указать её актуальную версию. CF-VM-LIVE-20261107: контроль чтения актуальной документации агентом на Cloud.ru. CF-PERSISTENT-LIVE-20261107: автоматическая проверка актуальности через постоянный worker.



agent-service marker=bbc3df769e4f04d5 digest=a372f216d71d3b92dba2934c02cad9272b1ff614a4a826a637d9fc1bd1db6635 generation=1

