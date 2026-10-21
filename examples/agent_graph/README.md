# Исполняемый этап HTTP requests

Отдельный пакет `agent_graph`, Python 3.12 + уже существующий pydantic.
Режим: явный запрос, локальные снимки, одна доверенная учетная запись ОС.
SQLite сохраняет версии и предложения; сервис, фоновый worker и MCP не нужны.
Внешний coding agent вызывает CLI subprocess и получает JSON. Он меняет код
и выполняет тесты в собственной рабочей среде, с собственными правами.

```bash
PYTHONPATH=src python -m unittest discover -s tests/graph -v
PYTHONPATH=src python examples/agent_graph/demo.py
PYTHONPATH=src python examples/agent_graph/evaluate.py --output /tmp/graph-component.json
PYTHONPATH=src python examples/agent_graph/bootstrap.py --directory /tmp/graph-example
PYTHONPATH=src python -m agent_graph \
  --policy /tmp/graph-example/operator-policy.json --state /tmp/graph-example/state \
  prepare_context --task 'Limit Orders default page size to 100'
```

`/tmp/graph-example` должен быть новым каталогом. Ответ содержит `context_id`.
С теми же `--policy` и `--state` доступны команды:

| Команда | Вход | Результат |
|---|---|---|
| `prepare_context --task TEXT [--operation ID]` | Разрешенный корпус и задача | Контекст до планирования; связи, требования, пробелы |
| `dependencies --context ID [--operation ID]` | ID контекста | Те же разрешенные данные и новая оценка свежести |
| `evidence --context ID --input citation.json` | Source ID, строки и точная цитата | Версия, путь, digest и проверенный фрагмент |
| `analyze_change --context BASE_CONTEXT_ID` | Предыдущий контекст и текущее содержимое корней | Новая версия контекста, сравнение объявлений base/head, findings и черновики |
| `propose --context ID --input proposal.json` | Структурированная находка с цитатами | Неутвержденный кандидат либо явно разрешенная human correction |
| `report_check --input check.json` | Context ID, candidate/artifact digests, команда, exit code, цитаты | Только `EXTERNAL_REPORTED`; модуль не удостоверял запуск |
| `investigate --context ID` | Действующий ModelConfig в policy | Ограниченное исследование моделью, записи кандидатов и журнал расходов |

В анализе основания старой декларации разрешаются через `base_context_id`,
а актуальных потребителей/head - через `context_used_id`. Source ID и digest
указывают неизменяемые bytes. `revision` - метка оператора; соответствие этой
метки Git commit автоматически не удостоверяется. Для исходников использовать
закрепленные копии, а существенные различия проверять по digest.

Для анализа заменить в копии `corpus/orders/api.py` default `page_size` с
`None` на `100`, затем вызвать `analyze_change` с исходным ID. `demo.py`
делает это воспроизводимо, затем исправляет Reporting и добавляет новый вызов
в ранее нерелевантный Health. Анализ читает AST; FastAPI/requests из fixture
не устанавливаются и исходники не исполняются. `store.read_orders` в примере
не реализован: вывод условен относительно поведения helper, не production факт.

Грамматика: module-level `import requests [as alias]`, `from requests import get`
и аналоги, литеральный `requests.request(method, url)`, literal URL или
конкатенация с однократно присвоенной module constant. Изменяемые/shadowed
имена, kwargs/динамический params, Session и распознанные неподдержанные
HTTP-клиенты дают пробел. Произвольный wrapper может остаться вне обнаружения;
`COMPLETE_WITHIN_PROFILE` относится к этой грамматике, не ко всем Python-вызовам.
Более глубокий анализ потоков, runtime и доказательство полного обхода страниц
не реализованы. `CURSOR_LOOP_OBSERVED` остается синтаксическим наблюдением.

Операции поставщика: простые `from fastapi import FastAPI`, `app = FastAPI()`,
декораторы маршрутов верхнеуровневых функций; OpenAPI JSON без разрешения `$ref`.
Identity: установка, среда, service, method, path template; явное соответствие
адресов задает оператор. Literal route приоритетнее шаблона; неоднозначность
дает gap. Один page_size default/удаление операции - поддержанный diff; общий
анализ семантики Python и изменение helper без такого объявления не реализованы.
Несогласованность OpenAPI и кода не разрешается выбором удобного default.

Источник содержит repository, revision и digest фактических bytes. Любое
изменение inventory, включая новый/удаленный файл, меняет basis. Каждое
`prepare_context` пока повторно сканирует разрешенные файлы дважды и строит
новый граф; чтение сохраненного контекста переиспользует результат, но проверка
свежести также читает corpus. Это корректная простая инвалидация, не готовый
инкрементальный индекс. Поля затрат явно учитывают проходы. Нет расписания и
обещания мгновенной актуальности. Двойная сверка не является атомарным снимком
нескольких репозиториев; для стабильной проверки использовать immutable копии.

`Policy` хранится вне анализируемого корпуса и считается доверенной настройкой
оператора. Capabilities отдельно разрешают maintain, read_context, propose,
report_check и correct. Это не SSO и не защита от владельца той же учетной записи
ОС, который может поменять policy или прочитать SQLite напрямую. Разные read
grants/установка/среда не могут читать один cached view через API. После изменения
доверия/области нужен новый context; автоматического переноса старых approvals нет.

Предложения с точными цитатами проверяются по scope, текущему basis и head.
Идентичное повторение идемпотентно; конфликтующие утверждения сохраняются вместе.
Только trusted capability `correct` может отметить исправление; модель не может.
Исправления сохраняются в overlay и истории после пересборки, но не переписывают
автоматически наблюдения парсера или доверенные нормы. При новом basis они STALE.
Для утверждения нового требования оператор обновляет доверенный источник и
его digest в policy. Цитата подтверждает происхождение, не истинность пересказа.

Форматы: [машиночитаемые схемы](../../schemas/agent-graph-1.json),
[реализация](../../src/agent_graph), [решения, затраты и угрозы](../../docs/agent-graph-implementation-2026-10-21.md),
[локальная модель / корпоративный сервис](../../infra/agent_graph/README.md).
Граф не выдает ACCEPT/REJECT, не исполняет предложенные проверки и не отправляет
черновики. JSON - машинный контракт; `--format markdown` - текстовое представление
для человека, не новый UI. UI и независимая v4-серия еще требуют работы.
