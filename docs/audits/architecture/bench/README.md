# Скрипты замеров

Скрипты запускают **неизменённое** ядро. На Linux `bench_shim.py` ничего не
делает; на Windows он подменяет только `read_relative` (обычное чтение вместо
`openat` + `O_NOFOLLOW`), проверку режима 0700 каталога состояния и `fcntl.flock`.

Подготовка: рядом со скриптами каталог `core` с экспортом ядра.

```bash
git archive c8cd01d src/agent_graph examples/agent_graph_demo | tar -x -C core
```

| Скрипт | Что делает |
|---|---|
| `gen_corpus.py OUT FILES DEPS NOISE [--version B]` | Детерминированный корпус: поставщик FastAPI на 200 маршрутов, до 7 репозиториев потребителей. Версия B меняет default одного маршрута и переписывает только этот файл |
| `bench_phases.py POLICY STATE GEN` | Фазы в одном процессе: prepare на пустом хранилище, dependencies, evidence, повторный prepare, analyze_change; время обхода, извлечения, JSON и SQLite по отдельности |
| `bench_cli.py RUN_DIR GEN [N]` | Тот же job, что делает worker демо: CLI analyze_change, dependencies и CLI evidence на каждую цитату (первые N, остальные по медиане) |
| `run_series.sh` | Серия по размерам, плотности зависимостей, шуму и трём реальным корпусам |
| `run_cli.sh` | `bench_cli.py` на 10, 100 и 1000 файлах |
| `profile_extract.py POLICY` | cProfile одного `discovery.extract` |
| `summarize.py` | Таблицы из `results/*.jsonl` |
| `proto_incremental.py POLICY EDIT_PATH STEPS` | Прототип ADR-005: кеш извлечения по файлу и три схемы хранения; сверяет граф с полным `extract()` |
| `repro_openapi_ref.py` | Воспроизведение дефекта OpenAPI `$ref` |
| `verify_claims.py REPO` | Проверки жизненного цикла: несвязанная правка, второй участник, второй репозиторий |
| `demo_citations.py` | Число вызовов CLI `evidence` на job демо-сценария |
| `run_tests_shim.py REPO [pattern]` | `tests/graph` на Windows через shim |
| `repin_lock.py SHA PROFILE` | Пересчёт `core.lock.json` из blob-ов Git, а не из рабочего дерева |

Реальные корпуса клонируются в `corpora/` с `--depth 1`: `psf/requests` v2.32.5
(`b25c87d`), `fastapi/fastapi` 0.115.0 (`40e33e4`), `django/django` 5.1
(`373cb30`). Ядро читает их как текст и ничего не исполняет.

Сырые результаты серии 22.10.2026: [results/phases.jsonl](results/phases.jsonl),
[results/cli.jsonl](results/cli.jsonl).
