# Повторный polling Bitbucket — контроль09.11.2026

PASS на целевой Cloud.ru dm-p1-ui, release a02ffa7854dcc38cecc7fe5c5317466059926cd9.
Проверка read-only; код, PR, Jira, Confluence и конфигурация не менялись.
Штатный worker не останавливался и не перезапускался; второй reconcile не запускался.

За157.76s наблюдения зафиксированы два последовательных успешных продвижения
reconcile:bitbucket checkpoint:1794171621.958433→1794171689.568698→1794171757.648074.
Проверяемый ресурс: Orders PR4, native comment identity jira:10023|10046.
Неизменны resource version, generation10, published_generation10 и comment_digest;
счётчики этого ресурса events8/jobs10/intents17/history88 не выросли. PID60331
сохранён, notices пусты. Через настоящую Jira API подтверждены неизменность тела
комментария10046, его updated timestamp и списка комментариев[10013,10046].
Новых событий/задач/публикаций для неизменного PR и дублей Jira не возникло.

Доказательства:[verification.json](verification.json).
Это квалификация повторного обнаружения неизменного ресурса через polling.
Bitbucket connector работает polling-only; replay webhook, повторная доставка
внешнего event_id и восстановление после неопределённого результата HTTP create
этой пачкой НЕ проверялись. Не объявлять их PASS на основании этого наблюдения.
