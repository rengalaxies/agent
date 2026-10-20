# Разбор изменения данных

Решение: REJECT (рекомендация)

## Изменение

```diff
--- producer-before.sql
+++ producer-after.sql
@@ -1 +1 @@
-SELECT user_id, amount FROM transactions ORDER BY user_id;
+SELECT user_id, amount * 100 AS amount FROM transactions ORDER BY user_id;

```

## Затронутые потребители

- retail-offers: владелец retail, требование retail-rub-amount, источник fixture:consumer-confirmation-v1

## Пробелы

- Не обнаружены в предоставленной области; полнота организации неизвестна.

## Следующее действие

Подготовлена совместимая версия рядом с новой. Повторная проверка: ACCEPT.

Файлы: compatibility.sql, compatibility-contract.json, regression-fixture.json.

Владельцу нужно проверить применимость и маршрутизацию потребителей. Автоматического применения нет.

Ожидаемые результаты и подтверждения в демо синтетические. Это не результат пилота.
