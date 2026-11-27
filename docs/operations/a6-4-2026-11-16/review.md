# Source review A6.4

Диапазон `cee0b49..f1287c8`, независимый reviewer, read-only.0 Critical,3 Important/2 Minor. Все Important исправлены одним проходом `e96798d`; повторного независимого review не заявляем.

| Important | Дефект и RED | Исправление и проверка |
|---|---|---|
| Notice scope |Legacy count kind/subject переходил между grants; `test_legacy_and_old_scope_notices_do_not_authorize_current_counts` RED |Отдельные scope-stamped observations и новые Service/Publisher writers; старые/чужие данные не влияют на counts, новые counts независимы; writer constructor RED→GREEN |
| Outbox scope |LIMIT10 перед проверкой receipts; чужие20 намерений вытесняли своё |Receipt EXISTS до LIMIT; точное сравнение outbox до/после чужих намерений GREEN; published_generation omitted |
| Binding target scope |Игнорировалась workspace UUID; смешанный Jira список терял разрешённую цель |Проверяются workspace+repo UUID; baseline f1287c8 function RED→current GREEN; CONFLICT содержит только разрешённые Jira keys |

Отложены Minor: configured binding без допущенного результата ведёт404; interrupted_during_send/awaiting_listing/resource_missing преобразованы в UNKNOWN. Новые управляющие кнопки, автоматические API-пробы и секретные поля не добавлены.

Reviewer подтвердил: роль проверяется до операторского payload, GET не вызывает коннекторы, конфигурация/inventory не изображают здоровье; ограниченное восстановление stale-contract compatibility согласуется с планом. Declined to judge: реальные browser/wheel/deployed-install проверки. Browser/wheel выполнены автором и сохранены; deployed acceptance остаётся A6.5.
