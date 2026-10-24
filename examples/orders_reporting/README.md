# Git-стенд Orders/Reporting

Общий пример всех пачек (раздел 5 задания). `stand.py` создаёт пять
Git-репозиториев plumbing-командами с фиксированными автором и датой, поэтому
SHA коммитов одинаковы на любой машине и при любом запуске. Checkout не
выполняется, hooks и фильтры при сборке не участвуют.

```bash
python examples/orders_reporting/stand.py /tmp/orders-stand
```

Команда печатает карту коммитов и пишет в каталог `repos/<имя>`,
`commits.json`, `ownership.json` и `jira-ORD-12.json`.

| Репозиторий | Ветка | Что проверяет |
|---|---|---|
| orders | `main` | `GET /orders`, `page_size` по умолчанию 100 |
| orders | `pr-7` | PR меняет default на 20 |
| orders | `readme-only` | правка README не даёт delta и не обесценивает память |
| orders | `unclassified` | меняется тело операции, default прежний: неизвестный тип изменения |
| orders | `removed` | операция удалена |
| orders | `hazards` | symlink, submodule, LFS pointer, бинарный и слишком большой файл, текст с prompt injection |
| reporting | `main` | читает одну страницу без `page_size`; `requirements.md` требует полной выгрузки |
| archive | `main` | читает все страницы курсором: корректная пагинация |
| billing | `main` | свой `GET /orders` в файле с тем же именем `api.py` |
| audit | `main` | вызывает `GET /orders` у billing, не у orders |

`Stand.policy()` даёт конфигурацию ядра в режиме `snapshot: git`,
`Stand.revisions(orders="pr-7")` — закреплённую карту коммитов всех читаемых
репозиториев. Ожидаемые исходы для PR `main → pr-7`: у reporting
`POSSIBLE_TRUNCATION` с требованием `reporting-complete`, у archive
`RECHECK_REQUIRED` с `CURSOR_LOOP_OBSERVED`, audit потребителем orders не
считается. Эти исходы закреплены в `tests/graph/test_git_sources.py`.

`ownership.json` — пример installation mapping для пачки 3: у audit владельца
нет, ответ должен показать «команда не определена». `jira-ORD-12.json` —
задача «Уменьшить стандартный размер страницы Orders со 100 до 20» для пачки 4.
Runtime-наблюдения для стенда готовит пачка 3.

Стенд синтетический. Он проверяет механизм и согласованность пачек, но не
качество на данных компании.
