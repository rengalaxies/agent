# Нагрузка ImpactMap — пачка 05

14.11.2026. **Пачка 05 завершена в заявленном offline-профиле; штатное ограничение 10/100k диагностировано отдельно.**

Профили: текущий авторский пилот на его ВМ, управляемые 5/50k и 10/100k из пачки 04. MODEL OFF, прежняя Python HTTP/API-грамматика. Локальная матрица запускает только один измеряемый процесс за раз; предварительные параллельные baseline-серии не используются для итогового времени.

## Итоговые наблюдения

Подготовка и прогоны проведены отдельно от прохождения штатного масштаба: **5/50k прочитан и прошёл очередь 10 PR с defaults; 10/100k на defaults дал corpus_limit; на явной policy 8MB оба профиля прошли весь измеренный offline-цикл.** Test policy: 2048 файлов / 65536 байт на файл / 8 000 000 байт на корпус / 60 секунд. Product defaults 256 / 65536 / 2 000 000 / 15 секунд сохранены.

Медианы трёх независимых процессов, секунды. Цикл включает core analysis, render и два локальных create/update измерителя 03; чистый `analysis` и вложенные/exclusive stages доступны в raw spans. Это отдельная процедура измерения стадий, а не число публикаций Service.

| Профиль | Repo / непустые Python-строки | Новый index, с | Первый цикл, с | Повторный цикл, с | Max self RSS, МиБ |
|---|---:|---:|---:|---:|---:|
| author-pilot-PR4 | 2 / 27 | 0.079 | 0.121 | 0.116 | 40.5 |
| 10x100k | 10 / 100000 | 4.886 | 15.026 | 15.082 | 97.7 |
| 5x50k | 5 / 50000 | 2.463 | 7.542 | 7.595 | 74.8 |

CPU inclusive для всей измеренной pipeline (index и два цикла), медианы; self и reaped children разделены. Child RSS — lifetime high-water mark child accounting, его нельзя складывать с self как RAM одновременно живого дерева.

| Профиль | Self CPU, с | Child CPU, с | Max child RSS, МиБ |
|---|---:|---:|---:|
| author-pilot-PR4 | 0.135 | 0.099 | 40.5 |
| 10x100k | 31.340 | 2.980 | 5.1 |
| 5x50k | 15.734 | 1.520 | 5.1 |

Все три stage-профиля дали по 3/3 process PASS и совпали с reference без внутренних wrappers. Повтор анализа заново читает и извлекает факты из корпуса, устойчивого cache-ускорения на этих наблюдениях нет. В sparse-корпусах восемь операций и три вызова: это проверка объёма кода при малом графе, а не предел ёмкости произвольного плотного графа.

Очередь: в ячейке **workload wall seconds / число выполненных анализов**; начальный index в это время не входит и измерен отдельным span. Последний столбец — max ожидания до claim в опыте на 10 входных событий. Это конечные burst workloads, не оценка steady-state throughput.

| Профиль и серия | 1 событие | 5 событий | 10 событий | Max wait (10), с |
|---|---:|---:|---:|---:|
| author-pilot-PR4, independent_prs/burst | 0.204 / 1 | 0.880 / 5 | 1.802 / 10 | 1.464 |
| 5x50k, independent_prs/burst | 7.608 / 1 | 38.199 / 5 | 76.689 / 10 | 68.998 |
| 5x50k, head_updates/sequential | 7.748 / 1 | 37.962 / 5 | 75.855 / 10 | 0.019 |
| 5x50k, head_updates/burst | 7.552 / 1 | 7.558 / 1 | 7.899 / 1 | 0.042 |
| 5x50k-default-policy, independent_prs/burst | — | — | 76.718 / 10 | 68.941 |
| 10x100k, independent_prs/burst | 15.275 / 1 | 75.907 / 5 | 152.494 / 10 | 137.150 |
| 10x100k, head_updates/sequential | 15.090 / 1 | 75.801 / 5 | 150.950 / 10 | 0.010 |
| 10x100k, head_updates/burst | 15.106 / 1 | 15.200 / 1 | 15.149 / 1 | 0.040 |

**22 queue cases PASS, 96 анализов, 122 уникальных доставок и 122 повторных.** В каждой серии доля ожидаемых успешных анализов 1.0, все нужные поколения опубликованы, ожидающих/failed jobs и intents нет, комментарий один на ресурс; очередь переоткрыта без повторной работы. Head burst объединяет обновления и анализирует последнюю версию один раз. Pilot-очередь принимает ожидаемое ABSTAINED/0, scale — USEFUL/3. Ошибки и пропуски не заменены этим статусом PASS: каждый per-generation verdict сохраняется. Все 80 локальных выполненных job также независимо сверены по result snapshot SHA с замороженными streams; безопасные карты лежат в `executed-job-pins.json` каждого случая.

Канонические факты full/event совпали во всех проверенных конечных состояниях: на каждом scale-профиле baseline 11, new consumer 12, removed consumer 10, operation removed 7; у пилота base/head по 5. Для удаления операции сохранены PARTIAL и ровно три unmapped_call при доступности всех sources; equality не превращает этот статус в COMPLETE. Никаких равенств пустой и сохранённой STALE-истории при недоступном источнике не заявлено.

Default collector отдельно:

| Профиль | Весь корпус, байт | Принято файлов / байт | Доля байт | Доля анализа | Исход |
|---|---:|---:|---:|---:|---|
| 5x50k | 1268477 | 110 / 1268477 | 100.00% | 0 | readable |
| 10x100k | 2536458 | 173 / 1995087 | 78.66% | 0 | corpus_limit |

При corpus_limit collector не возвращает частичный context, поэтому анализ и findings для него не выдаются. Доля чтения считает принятые UTF-8 source bytes до отказа; это не доля успешно проанализированного кода. В successful scale-контекстах все repo/файлы доступны, coverage COMPLETE_WITHIN_PROFILE, кроме явно указанного удаления операции.

Установленный рабочий диапазон ограничен проверенными точками: 5 repo/50k/110 файлов/1.27MB с проверкой очереди 10 PR на штатных лимитах и 10 repo/100k/220 файлов/2.54MB с test policy. Предел default по байтам — 2MB, дополнительно действуют file/count/scan budgets. Предел в SLOC не выведен; поведение более крупных или иных по плотности/грамматике проектов не установлено. Поднимать defaults или оптимизировать граф/очередь без обнаруженного отказа и эксплуатационного SLO оснований не получено. Выявленные ограничения сохранены и обходятся только явной тестовой конфигурацией.

[Сводка](summary.json), [команды и результаты всех локальных случаев](progress.json), [среда/версии](execution.json), [ревью и исправленный false-PASS](review.md), [72 теста](logs/tests-final.log), [приёмка/хеши](acceptance.json). Сырые данные лежат в подпапках PROFILE-baseline / PROFILE-equality / PROFILE-family-delivery-N; pilot-stage и pilot-load сохранены отдельно. Предварительные параллельные baseline исключены из итоговых чисел и отмечены в [SUPERSEDED](superseded-observations.json). Текстовые line endings при публикации нормализованы, числовые наблюдения не менялись.

Следующая пачка — 06: независимые кейсы и два реальных эксперта по протоколу 02. Эти контролируемые нагрузки не заменяют такой эталон. Нагрузочный PASS не доказывает precision/recall, бизнес-пользу, p95, HTTP latency, восстановление после сбоя сервера или производственную установку.

## Метод

PASS означает завершение опыта с ожидаемым результатом, корректной публикацией и явным coverage. Новый порог latency/SLO по полученным числам не вводился.

- Три независимых процесса для cold application index + first analysis + warm repeat на каждом stage-профиле. Cold означает новые SQLite/состояние приложения; OS cache не сбрасывается. Reference без внутренних wrappers проверяет неизменность результата и канонических фактов.
- Время: perf_counter, включая overhead измерителя. CPU: self user/system и reaped children отдельно; RSS: process-lifetime high-water mark (отдельно self и children), не stage-local peak, не суммарная память дерева процессов.
- Очередь: настоящий ServiceStore/Service/CoreAnalyzer/Publisher, один worker, штатные scheduling limits и реальное время. Границы транспорта заменены pinned local connector и DirectorySink; HTTP latency/polling и внешняя публикация NOT_RUN.
- Серии 1/5/10: independent PR burst, последовательные обновления одного PR, burst обновлений одного PR. Каждая доставка повторяется с тем же ID. Burst heads ожидаемо coalesce в последнюю версию; это не 10 полноценных анализов. Все выполненные поколения проверяются по статусу, reason, числу находок и gaps; последняя публикация не может скрыть ранний сбой.
- На ВМ проигрываются 1/5/10 независимых resource ID одного закреплённого изменения реального авторского пилота. Это синтетическая нагрузка очереди на его коде, не 16 реальных PR. Известный исправленный PR4 даёт ABSTAINED/no_supported_delta/0; этот результат задан отдельно и не считается USEFUL.
- Full/event equality: новый GraphMaintainer.reconcile против GraphMaintainer.on_code_event в сохраняемой SQLite при одинаковых конечных Git pins. Сравниваются все canonical active facts, включая basis data. История/временные metadata не объявлены равными. Существующий event-путь заново читает код, поэтому слово incremental здесь не означает частичный parsing или ускорение.
- Baseline/new consumer/removed call должны иметь полный source access и точное число фактов. Удаление операции имеет ожидаемые три `unmapped_call`, остаётся PARTIAL; доступ ко всем sources сохранён, точные gaps и факты проверены. Недоступный источник не может пройти этот контроль. Cached STALE history и пустая история при неполном доступе не считаются одинаковыми входами.

`progress.wall_s` для baseline включает все три worker и контрольные reference-запуски; длительности отдельных стадий берутся из spans.

## Воспроизведение

Из корня checkout, существующим Python с зависимостями проекта:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.prepare_impactmap_corpora --suite --verify --output work/batch04/corpora-v1 --seed 20261114
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python experiments/impactmap_scale/results/reproduce_matrix.py
```

Обе команды требуют новых output-каталогов. Если корпуса уже существуют, первую пропустить; для повторного отчёта заменить `base = ...work/batch05/final` в сохранённом рецепте новым каталогом. [Рецепт](reproduce_matrix.py) — точная программа последовательного запуска итоговой локальной матрицы. Состояние, источники и абсолютные входные manifests остаются в ignored work/; в отчёт копируются только безопасные метрики.

Команды отдельного опыта:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.load_impactmap --corpus work/batch04/corpora-v1/repos5-lines50k --output work/check-equality-new --equivalence
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.load_impactmap --corpus work/batch04/corpora-v1/repos10-lines100k --output work/check-defaults-new --probe-defaults
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.load_impactmap --corpus work/batch04/corpora-v1/repos10-lines100k --output work/check-queue-new --queue-size 10 --family independent_prs --delivery burst
```

Default probe 10/100k возвращает код 1 с сохранённым corpus_limit; это ожидаемый отрицательный результат. Прогон на explicit 8MB policy и отказ на product defaults должны быть показаны раздельно.

Пилот измеряется на его ВМ с frozen pins из файла 03 и новым временным состоянием. Возвращаются только метрики и SHA; рабочая очередь не используется:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python experiments/impactmap_scale/run_pilot_vm_benchmark.py --ssh-config /Users/user/Documents/ChatGPT/ВКР/.private/m3-ssh-20261101/config --pins-from experiments/impactmap_scale/baseline-2026-11-14/input-pins.json --output work/pilot-stage-new --repeats 3
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python experiments/impactmap_scale/run_pilot_vm_load.py --ssh-config /Users/user/Documents/ChatGPT/ВКР/.private/m3-ssh-20261101/config --pins-from experiments/impactmap_scale/baseline-2026-11-14/input-pins.json --output work/pilot-load-new
```

У пилота отдельные host/runtime/core hashes и аппаратная среда. Время между ним и локальными корпусами нельзя трактовать как чистый коэффициент роста. SSH roundtrip включает remote execution и не является HTTP latency. Pilot queue cases в одном remote процессе: ru_maxrss — общий накопленный high-water mark, а не независимый peak каждого case.

Отдельная команда проверяет очередь 10 PR для 5/50k с полностью штатными limits: полный offline-цикл на default policy, включая анализ и публикацию. Воспроизведение в новом каталоге:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python experiments/impactmap_scale/results/check_default_queue.py --output work/batch05/default-queue-new
```
