# Измерения и масштаб ImpactMap

Пачка 03: [исходный baseline 14.11.2026](baseline-2026-11-14/README.md).

Пачка 04: [управляемые Git-корпуса 5/50k и 10/100k, дополнительные оси и проверки](corpora/README.md). Подготовка завершена.

Пачка 05: [нагрузочные прогоны, очередь и канонические факты](results/README.md). Проверки проведены; штатный corpus_limit на 10/100k сохранён отдельно от PASS с explicit test policy.

Воспроизводимый локальный development-прогон на существующем детерминированном Orders/Reporting:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.benchmark_impactmap --output work/benchmark-new --repeats 3
```

Для собственного разрешённого корпуса передать `--manifest PATH`: формат `impactmap-benchmark-input-1` с policy, полными `base_revisions`/`head_revisions`, `provider_repository`, `pr_id` и одним из явных provenance (`author_fixture`, `author_pilot_on_vm`, `author_pilot_snapshot`, `authorized_external`, `controlled_generated`). Policy требует Git pins и MODEL OFF. Корни репозиториев — абсолютные локальные пути. Manifest может содержать приватные пути, поэтому сохраняется только в private-подкаталоге output, не в публикуемых метриках. Источники только читаются; новые SQLite и локальные комментарии находятся в output/private. Существующий output не перезаписывается.

Файлы результата: `manifest.json`, `measurements.jsonl`, `spans.csv`, `summary.json`. Каталог `private/` и весь `work/` не добавлять в Git. Публиковать только числовые/агрегированные артефакты после проверки. Сравнение семантики исключает только явно перечисленные временные metadata, не findings/claims/evidence/freshness status. Любой сбой, пропуск, PARTIAL и gap виден в сыром наблюдении; `all_semantics_equal` означает совпадение с reference, а не успешный анализ или точность продукта.

Текущий Cloud.ru-пилот можно измерить **на его ВМ** без выгрузки исходников:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python experiments/impactmap_scale/run_pilot_vm_benchmark.py --ssh-config /Users/user/Documents/ChatGPT/ВКР/.private/m3-ssh-20261101/config --pins-from experiments/impactmap_scale/baseline-2026-11-14/input-pins.json --output work/pilot-benchmark-new --repeats 3
```

Это узкий операторский helper существующего стенда dm-p1-ui/PR4, с текущими путями `/etc/agent-bitbucket` и `/opt/agent-bitbucket/current`. Он отправляет код инструмента по SSH, читает mirror refs и сохранённый snapshot PR4, создаёт изолированное временное состояние и возвращает только метрики/SHA. Он не копирует source/Git objects/конфиги и не вызывает installed worker reconcile или публикацию трекера. Требует существующий SSH-профиль и права чтения на стенде; credentials в репозиторий не включаются. Без --pins-from helper читает текущий PR4 и при нескольких PR4 явно отказывает; с --pins-from использует сохранённые base/head, а не текущее состояние задачи; при смене pins во время серии отмечает `input_pins_changed` вместо незаметного объединения разных входов.

## Как читать стадии

- `initial_index`: первая сборка графа на свежем SQLite/process. Это не холодный OS cache.
- `first_analysis`: первый PR-анализ **после** этой индексации, request settings, render и локальные create/update.
- `warm_repeat`: повтор с теми же pins и сохранённым SQLite в том же процессе.
- Внутри: `collect` (local Git verification/read), `extract`, `graph_sync`, собственное время `analysis`, `render`, `local_publication_create/update`, `inventory_metrics` (накладные расходы счётчиков), `canonical_facts`.

JSON/CSV содержат span_id/parent_id/depth. `wall_s` и CPU — включающие вложенные стадии; складывать их для total нельзя. `exclusive_*` вычитает непосредственных детей. User/system CPU Python и reaped Git children разделены. `ru_maxrss` — накопленный high-water mark процесса с его начала, в bytes после нормализации macOS/Linux; child peak не суммируется с Python peak и не выдаётся за суммарную RAM дерева процессов. Импорты и наблюдатель влияют на process peak. Вызовы счётчиков строк выделены в inventory_metrics, прочие накладные расходы wrappers не вычитаются.

`python_physical_lines` включает все строки `.py`; `python_nonblank_noncomment_lines` исключает пустые и начинающиеся с `#`, но включает docstrings/продолжения. Это прозрачный физический счётчик, не logical SLOC. `text_lines` включает все принятые текстовые исходники, включая Markdown/JSON. `files_read` — реально принятые sources, `inventory_entries` — инвентарные записи, доступность репозиториев определяется наличием проверенного tree. Публикуются gaps/coverage, не только размер.

SSH roundtrip записан отдельно: включает удалённую работу и не является чистой сетью. HTTP/API получение, polling, очередь и внешняя Jira-публикация не выполняются. Local DirectorySink не моделирует задержку tracker API. Три повтора — наблюдения воспроизводимости, p95/SLA и предел масштаба не установлены.

04 добавит новые scale-корпуса и manifest; 05 — нагрузочные серии. Существующий пятирепозиторный author fixture содержит лишь десятки строк и не является профилем 5/50k. Качество/покупатели проверяются отдельными пачками.
