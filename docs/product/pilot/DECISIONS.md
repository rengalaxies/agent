# Решения по автономному выпуску

24.10.2026. Направление и восемь слайдов согласованы владельцем. Параметры
адаптеров уточняются по первому контуру, не выдаются за готовые возможности.

| ID | Решение | Проверка |
|---|---|---|
| A1 | Автономный B2B-сервис из коробки, без постоянного инженера | Учитывать ручные минуты установки и эксплуатации |
| A2 | Нет постоянных оператора и разметчика | Производственная выдача не ждёт человека |
| A3 | Jira и PR — два входа в один анализ | Намерение в Jira; уточнение по diff в PR |
| A4 | Граф кода и одного runtime-источника доступен агенту и людям | Источник, версия/окно, статус, свежесть каждой связи |
| A5 | Открытая модель проходит квалификацию | Qwen 0/3 — остановка action-протокола, не доказанная семантическая неспособность |
| A6 | Конституция закреплена и исполняется инструментами/валидаторами | Одного промпта недостаточно |
| A7 | Первичные доступы выдаёт владелец источников | Агент не получает права из текста задач и репозитория |
| A8 | Один обновляемый результат на задачу/PR | Дедупликация, ограничение частоты, восстановление очереди |
| A9 | Нет нового согласования или блокировки выпуска | Частичный результат/отказ по deadline |
| A10 | Коробка включает установку, проверку, обновление/возврат; Cloud.ru — один адаптер создания ВМ | Старые workflow не объявляются готовым installer |
| A11 | Нет автоматической правки кода, универсального доступа и редактора онтологии | Не нужны для первого сквозного сценария |
| A12 | Восемь слайдов, граф, альтернативы, «сейчас / план» | Подробности квалификации в технических материалах |
| A13 | Новый сценарий оценивается отдельно | Исторический критерий 20% не переписывается |

## Как учтены аудиты

| Источник | Решение |
|---|---|
| #44: Python, основания, Git-версии, память, диагностика | Сохранить; реализовывать по сквозным пачкам |
| #44: точная последовательность перестройки демо | Не принимать автоматически; приоритет у автономного сценария |
| #48: сравнение с альтернативами и узкий первый сценарий | Сохранить; не объявлять альтернативы неспособными к проверяемым ответам |
| #48: остановить модельные работы и поставку | Пересмотрено владельцем: модель и коробка входят в гипотезу после квалификации |
| Прежний #47: ручной шестинедельный пилот | Отклонено как предложение продукта; сохранено в архиве |
| #45 / #46 | Слиты 24.10.2026, не равны готовности MVP |

Параметры контура: Git-хостинг, Jira Cloud/Data Center, источник трасс/логов,
идентичности сервисов, endpoint/версия модели, ресурсные/стоимостные лимиты,
право публикации. Они задаются при установке, не постоянным оператором.

## Confluence scope agreed with owner — 2026-11-07

The first Confluence integration reads only pages explicitly linked in the
Jira issue description. Supported content is page text and ordinary tables.
It does not follow child pages, links within a page, search results or attachments.
Images, diagrams, embedded documents and attachment text are outside this scope.
The result must identify skipped material and gaps that affect the conclusion.

Each used requirement retains its page URL, page identity, version, section
and supporting text. Access failures, unavailable pages, unsupported content,
truncated retrieval and conflicting requirements must remain explicit.
A page describes a documented requirement; it does not establish runtime
compatibility. Page content cannot expand source access or tool permissions.

Acceptance requires: explicit-link selection, no link traversal, text/table
extraction, version-bound evidence, access-denied handling, image/attachment
exclusion and a Jira result with source references. Connector implementation
and live qualification are pending.
