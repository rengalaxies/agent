# Управляемые корпуса ImpactMap — пачка 04

14.11.2026. **Подготовка завершена:** шесть детерминированных Git-корпусов проверены существующим core в Python HTTP/API-профиле, MODEL OFF. Генератор v1.0, seed **20261114**. Это контролируемые материалы для разработки и нагрузки; они не добавляются к независимым quality cases пачки 06.

| Профиль | Repo | Python: непустые без начального `#` | Физические строки | Файлы | Байт | Операции / callsites |
|---|---:|---:|---:|---:|---:|---:|
| [5/50k](repos5-lines50k/corpus-manifest.json) | 5 | 50 000 | 50 120 | 110 | 1 268 477 | 8 / 3 |
| [10/100k](repos10-lines100k/corpus-manifest.json) | 10 | 100 000 | 100 225 | 220 | 2 536 458 | 8 / 3 |
| [10/50k](repos10-lines50k/corpus-manifest.json) | 10 | 50 000 | 50 125 | 120 | 1 268 632 | 8 / 3 |
| [5/100k](repos5-lines100k/corpus-manifest.json) | 5 | 100 000 | 100 225 | 215 | 2 536 598 | 8 / 3 |
| [5/50k dense](repos5-lines50k-dense/corpus-manifest.json) | 5 | 50 000 | 50 141 | 110 | 1 269 122 | 8 / 24 |
| [5/1k anchor](repos5-lines1k-anchor/corpus-manifest.json) | 5 | 1 000 | 1 020 | 10 | 25 777 | 8 / 3 |

Числа относятся к pinned `main`, а не сумме всех Git-версий. Строки считаются непосредственно из UTF-8 байтов исходников; это явно определённая метрика, не универсальный семантический SLOC. Filler — обычные арифметические Python-функции, не пустые строки или комментарии. Снимки содержат восемь FastAPI GET-операций `/items/0..7`, прямые `requests`-вызовы и независимый код. Источники не исполнялись. Топология и позиции вызовов записаны генератором до запуска extractor, в отдельном `oracle.json`.

## Оси и сценарии

- Число repo: 5/50k против 10/50k; объём: 5/50k против 5/100k. В обеих сериях фиксированы восемь операций и три активных потребителя из разных repo. Число файлов на оси repo меняется 110 → 120, поэтому чистый overhead одного repo из этих двух наблюдений выделить нельзя.
- Плотность: 5/50k против 5/50k dense, по одному или восьми callsites на каждого из трёх потребителей. Непустые строки, repo и операции фиксированы; меняются состав файлов, физические строки и байты.
- Поток: в каждом manifest две серии `head_updates` и `independent_prs`, каждая с длинами 1/5/10. Первая обновляет head одного PR, вторая использует разные PR ID; сохранены порядок, event ID, base/parent/head SHA. **Это подготовленные входы; очередь и пропускная способность в 04 не запускались.**
- `baseline`: default `page_size` операции 0 уменьшается 100 → 99, ожидаются три `POSSIBLE_TRUNCATION`.
- `new_consumer`: ранее нерелевантный `extension.py` последнего repo начинает вызывать операцию 0; ожидаются четыре находки и полный прежний набор зависимостей плюс новая. Проверяется после отрицательного base-снимка.
- `removed_consumer`: вызов операции 0 в r01 удалён; отношение становится RETRACTED, остальные calls остаются ACTIVE. В dense-варианте проверяются новые строки сохранившихся вызовов.
- `operation_removed`: удаляется операция 0, сохраняются три `OPERATION_REMOVED` с STALE-зависимостями.
- `partial_access`: корень r01 заведомо отсутствует; доступно 4/5 либо 9/10 repo, coverage PARTIAL, gap `commit_unavailable`, ранее известная связь STALE с `source_unavailable`. Это fault injection пути, не проверка отзыва реальных credentials. Oracle описывает полный исходный корпус; неполная обработка остаётся видимой.

## Полученные доказательства

[Индекс](index.json) содержит фактические размеры и хеши файлов. В папке каждого профиля находятся `corpus-manifest.json` (commit/tree SHA всех версий, inventory, limits, policy, streams), `oracle.json` и `verification.json` с результатами чтения и анализа реального Git-корпуса.

Все шесть проверок завершились `verification_passed=true`: совпали все file hashes/размеры/строки, восемь операций, полный набор callsites и ожидаемые находки. Проверены новый потребитель, удаление связи/операции и частичный доступ. Свидетельства каждой публикуемой находки проверены через `get_evidence` по pinned source.

[Noise invariance](noise-invariance.json): каждый из четырёх больших sparse-профилей совпал с anchor по всем трём находкам, callsite-позициям и repository/path/phase/строкам/хешам цитат. Сравнение допускается только при PASS обоих полных oracle-checks и ожидаемом числе находок 3. Исключены идентификаторы commit/source/receipt, меняющиеся из-за нерелевантного кода. Это сохранение контролируемого смысла находок, не оценка precision/recall или гарантия для произвольного Python.

**Штатный предел остаётся видимым.** [Отдельный probe](default-limit-observations.json) на финальных pinned sources: 5/50k прочитан с product defaults; 10/100k дал `corpus_limit`, поскольку 2 536 458 > 2 000 000 байт. Здесь коллекция, а не измерение производительности. Основные проверки 04 использовали явную test policy: 2048 файлов, 65536 байт/файл, 8 000 000 байт/корпус, 60 секунд. Defaults продукта (256 / 65536 / 2 000 000 / 15 секунд) и `src/` не изменены. PASS подготовки 100k не означает поддержку этого размера штатной конфигурацией.

[Журнал тестов](logs/tests-final.log): **54 tests, OK** (12 новых, benchmark/VM helper и graph/Git регрессии). [Ревью и исправления](review.md); [среда, исходная версия и core hashes](execution.json); [приёмка и контрольные суммы](acceptance.json). [Предварительные серии](superseded-observations.json) помечены SUPERSEDED и не являются итоговой приёмкой.

## Воспроизведение

Из корня checkout, Python с установленными зависимостями проекта. Здесь использован существующий `/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python`; ниже `python` означает этот интерпретатор:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.prepare_impactmap_corpora --suite --verify --output work/batch04/corpora-new --seed 20261114
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m unittest tests.performance.test_scale_corpora tests.performance.test_benchmark_impactmap tests.performance.test_benchmark_vm tests.graph.test_graph_store tests.graph.test_git_sources -v
```

Output должен быть новым. Генерация с тем же seed/параметрами/версией даёт те же деревья и commits независимо от каталога; маленький path-independence/seed regression входит в тесты. SHA самого генератора также сохранён. Git plumbing — существующий `examples/orders_reporting/stand.py`, его hash есть в execution metadata.

Финальные локальные данные находятся в **`work/batch04/corpora-v1/`**. Git objects, исходники, SQLite и абсолютный `benchmark-input.json` остаются в ignored `work/`. Публичные папки выше содержат только portable metadata и доказательства; они сами не являются Git-корпусом. При переносе сначала создать корпус рецептом, затем вызвать `load_benchmark_input(new_root, scenario)` для разрешения новых абсолютных roots. Oracle никогда не передаётся analyzer.

Для перепроверки noise на вновь созданной паре:

```python
from tools.prepare_impactmap_corpora import verify_corpus, verify_noise_pair
# Новые каталоги состояния; оба oracle-check должны быть PASS, ожидается 3 находки.
a = verify_corpus('work/batch04/corpora-new/repos5-lines1k-anchor', 'work/noise-anchor-check')
b = verify_corpus('work/batch04/corpora-new/repos10-lines100k', 'work/noise-large-check')
n = verify_noise_pair('work/batch04/corpora-new/repos5-lines1k-anchor',
                      'work/batch04/corpora-new/repos10-lines100k', 'work/noise-compare')
assert a['verification_passed'] and b['verification_passed']
assert n['same_located_findings'] and n['finding_count'] == 3
```

## Передача в пачку 05

Следующий шаг — холодная индексация, повторный анализ, CPU/память, очередь 1/5/10 и диагностированный предел на текущем, 5/50k и 10/100k. Вход baseline уже совместим с измерителем 03:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python -m tools.benchmark_impactmap --manifest work/batch04/corpora-v1/repos5-lines50k/benchmark-input.json --output work/batch05/run-new --repeats 3
```

Эта команда здесь **не запускалась**; она не исполняет очередь. Прогоны 05 должны отдельно сохранять effective limits, failures/gaps/coverage, full/incremental canonical equality при одинаковом полном входе и явное различие пустой истории с сохранённой STALE-историей при недоступном источнике. Нельзя выдавать такой исторический контекст за расхождение алгоритмов. Время/p95, ресурсы, рабочий предел и независимое качество в 04 NOT_RUN.
