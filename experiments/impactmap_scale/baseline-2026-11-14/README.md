# Пачка 03 — исходный baseline ImpactMap

14.11.2026, Москва. **DONE в объёме измерений текущего корпуса.** Доказанная ёмкость 5/50k и 10/100k, p95, качество, время человека и коммерческая польза не установлены.

## Вход и воспроизведение

Основная итоговая серия: **3 отдельных процесса на существующей Cloud.ru ВМ**, в каждом новая временная SQLite и два анализа (первый после initial_index и warm repeat). Анализатор — установленный Python/core через `/opt/agent-bitbucket/current/app`; замеры — текущий инструмент с SHA256 `c6de3d9cabc1f43661775187c6d4a3f7f8434852187dec8b9a265ebcbb14e9cf`. Git-база разработки инструмента — `48cd1fba1365fe6e2e4c34e3cb9a185b47d0e5dd`; отдельный commit документов не является runtime SHA.

Фиксированные входы: [input-pins.json](input-pins.json). Orders base `5d405f22a0d919dd395fa02339c9170de20a89f7`, head `01b6ebfa4cefb633f9606b2bded4f2e00c3be96d`; Reporting `6ebf07174eb9ef4018a98ccf14da1cb94b6a69e3`. Corpus — текущий **авторский** пилот, не независимый внешний проект. Исправленный PR4 не содержит поддержанной разницы: все результаты `ABSTAINED/no_supported_delta`, deltas=0, findings=0. Это сохранённый исход, не повод заменить PR ради положительного предупреждения.

Команда точного повторения исходных pins из корня checkout:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. /Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python experiments/impactmap_scale/run_pilot_vm_benchmark.py --ssh-config /Users/user/Documents/ChatGPT/ВКР/.private/m3-ssh-20261101/config --pins-from experiments/impactmap_scale/baseline-2026-11-14/input-pins.json --output work/batch03/pilot-frozen-new --repeats 3
```

Нужен действующий приватный SSH-профиль и наличие этих commit в разрешённых зеркалах. Команда с `--pins-from` использует сохранённые base/head, не следует сегодняшнему PR. При отсутствии commit она должна явно отказать/вернуть FAILED, а не подменить вход. Фактически эта команда проверена с `--repeats 1`: [отдельный повтор](raw/pilot-frozen-reproduction.summary.json), hashes семантики совпали с основной серией. Основные три процесса вызваны тем же helper без override, когда сохранённый PR содержал ровно эти SHA. Все входные pins совпали между ними.

Основные сырые данные: [JSONL](raw/pilot-final.measurements.jsonl), [все вложенные spans CSV](raw/pilot-final.spans.csv), [summary](raw/pilot-final.summary.json), [крупные стадии CSV](stage-overview.csv), [сводка среды и корпуса](baseline-summary.json). Каждая строка JSONL содержит measured и reference digests, все stage clocks, inventory/coverage и counts. Сырые цифры не заменены одной средней.

## Среда и фактический размер

- ВМ: Linux / x86_64, Python 3.12.3, 2 logical CPU, RAM 4106104832 bytes; pydantic 2.13.4, PyYAML 6.0.3. Это существующий общий стенд; соседняя нагрузка не фиксировалась и не изолировалась.
- Runtime record: `a02ffa7854dcc38cecc7fe5c5317466059926cd9`; core profile `http-requests-6`, digest `76f495463a158f62bcb7644750e073d6e7f53bd736c407f8329627d7841ab49c`. Process record не доказывает пофайловый hash всего service-кода; измеренные модули импортировались из current. Digest ядра совпал с исходной базой 00.
- На один pinned context: **2 configured / 2 available репозитория, 6 принятых файлов, 64 текстовых строк**, из них 3 Python-файла, **40 физических строк Python / 27 непустых строк без начального #**. Docstrings входят в этот физический счётчик; это не logical SLOC. Прочитано 2412 bytes, scan_passes=1.
- Извлечено 3 операций, 2 dependency callsites; persistent graph: 3 declares + 2 calls = **5 отношений**. Inventory entries=6, coverage=COMPLETE_WITHIN_PROFILE, gaps пусты. «Полный внутри профиля» не значит совместимость или глобальную полноту произвольного кода.

Не умножать размер корпуса на число контекстов/повторов: одно и то же содержимое читалось повторно. Другие строки source, исключённые policy, не объявляются проанализированными.

## Основные наблюдения

Секунды, median [min; max] по трём процессам. CPU — отдельно Python user+system и reaped Git children; это не процент CPU. Пик RAM — high-water mark **с начала Python-процесса**, включая импорты/измеритель, не локальный пик стадии.

| Стадия | Wall s: median [min; max] | Python CPU s: median | Git children CPU s: median | Python lifetime peak MiB: max |
|---|---:|---:|---:|---:|
| initial_index | 0.067466 [0.058345; 0.075123] | 0.023126 | 0.010691 | 39.30 |
| first_analysis | 0.115261 [0.112745; 0.125452] | 0.044361 | 0.040091 | 40.43 |
| warm_repeat | 0.128373 [0.106634; 0.133035] | 0.039601 | 0.040502 | 40.55 |
| pipeline | 0.327053 [0.319130; 0.355540] | 0.131521 | 0.091051 | 40.55 |

`pipeline` включает setup, initial_index, оба анализа/render/local create+update, счётчики и canonical-facts check; исключает запуск/импорты Python, SSH и закрытие временного состояния. `first_analysis` уже следует за initial_index. Внутренние `analysis` включают local Git collect/extract/graph sync; для разделения использовать parent_id и exclusive_* в сыром CSV, а не складывать inclusive длительности.

В измерителе есть отдельные `collect`, `extract`, `graph_sync`, `analysis`, `render`, `local_publication_create`, `local_publication_update`, `inventory_metrics`, `canonical_facts`. Line-count observer выделен отдельно; прочий overhead wrappers включён в замер. Child CPU учитывает только завершённых/reaped потомков. Child peak RSS не суммировать с peak Python: общей peak RAM дерева процессов здесь нет.

## Сеть, polling и публикация

Источники читались локально на ВМ из уже имеющихся зеркал. HTTP/API получение, Git fetch, polling и очередь не выполнялись в measured pipeline. Они имеют **NOT_RUN**, не выдуманные нули. SSH roundtrip сохранён отдельно и включает исполнение/импорты/reference/передачу метрик; это не чистая network latency. Публикация — реальный вызов существующего `DirectorySink.create_comment/update_comment` в отдельном временном каталоге, **не** API Jira, не полный Publisher/queue цикл и не замер задержки до пользователя. Confluence и модель не вызывались.

Автоматический approval review отклонил первоначальный вариант копирования Git objects/refs со стенда в локальную work-папку как чувствительный egress. Этот перенос не выполнен. Более безопасный вариант полностью выполнил задачу: инструмент запущен на ВМ, наружу получены агрегаты/хеши. Установка релиза, изменение конфигурации, live queue, комментарии и restart не выполнялись. [Postcheck](postcheck.json): worker active, PID 60331, started_at 2026-11-08T13:58:17.306809+00:00, health live=true, прежний a02ffa7 сохранён.

## Прозрачность измерителя и регрессии

Каждый measured запуск сопоставлен с reference без внутренних wrappers на тех же pins и отдельных SQLite. Проверяется полный нормализованный validated AnalysisResult и `GraphStore.canonical_facts`; исключены только fields `timings`, `checked_at`, `started_at`, `finished_at`, `assessed_at`. Идентификаторы, graph_version, claims/evidence, status/reasons и freshness status не исключаются. Сравнение performed per mode; разные request IDs первого и warm запуска не объявлены одинаковым сырым документом. Все 3/3 основные и отдельный frozen reproduction совпали. Это проверка прозрачности телеметрии, не независимое TP/FP/FN качество.

[Профильные регрессии](regressions-51.log): 51 тест прошёл (новый harness, graph store/Git sources, service core/graph memory). Изначально 10 loopback-тестов блокировались sandbox bind; после разрешённого локального HTTP запуска все 51 прошли, core не исправлялся ради среды. После code review [все 14 тестов инструмента](benchmark-tests-14.log) прошли: вложенные wall/CPU, RSS units, возврат wrappers после ошибки, семантика, missing source, sensitive-source omission, model refusal, отсутствие перезаписи output, JSON/CSV, отказ произвольного provenance, сохранение timeout/launch/parse failure и pin forwarding/drift.

Ревью отдельного агента нашло две P2: произвольный provenance попадал в metadata и timeout терял строку неудачной попытки. Оба дефекта воспроизведены тестами до исправления, исправлены, покрывающие проверки прошли. Дополнительно сохранены явные include/allowed_refs исходной policy и уточнено различие process record/измеренного source. Повторное агентское ревью не выполнялось; итоговые проверки провёл исполнитель. Сам analyzer/service source не менялся.

Предварительные прогоны сохранены для аудита: `raw/pilot-prereview.*` (3 процесса), `raw/pilot-live-reproduction-prereview.*` (1), `raw/author-stand-prereview.*` (1 локальный). Их не объединяли с итоговой серией ради p95 или выбора самого быстрого результата. Итоговый локальный development smoke — `raw/author-stand-final.*`: существующий пяти-repository stand, не 5/50k; source tool hash совпадает с итоговым инструментом. Private inputs/SQLite/source text не копировались в raw/.

## Следующий шаг

Пачка **04**: подготовить 5 repo / около 50k анализируемых строк и 10 / около 100k в том же Python HTTP/API-профиле, считать реальный размер и известные связи, сохранить seed/manifest/SHA и отдельные случаи нового потребителя и неполного доступа. После этого 05 проведёт scale/queue серии и установит границу. Текущий baseline из 40 физических Python-строк показывает точку старта, а не масштабируемость и не продуктовую ценность.

При публикации CSV окончания строк нормализованы в LF для Git; все строки/значения проверены на равенство исходным CSV. Побайтовые исходные файлы прогона остаются в ignored work/batch03; JSONL и числовые наблюдения не изменялись.
