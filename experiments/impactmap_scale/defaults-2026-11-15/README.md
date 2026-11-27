# ImpactMap05: рабочие defaults8МБ

15.11.2026. Код `fd3dbc3` расширяет defaults до **8 000 000 байт /2048 записей inventory /60 секунд на один сбор**. Предел одного файла65 536 байт и верхние валидационные границы прежние. Explicit operator values сохраняются; новый source не переписывает старые policy-файлы или установленный runtime. Static profile9/output2.2 сохранены, core fingerprint изменён. MODEL OFF; внешние API/ключи/ВМ не использовались, поставки нет.

Это профиль для уже испытанного sparse-пилота10 репозиториев / около100 тыс. строк. Он не доказывает работоспособность произвольного8MB-проекта, production SLO или качество на независимых данных. [Настройка, смысл счётчиков и переход](../../../docs/operations/analysis-limits.md).

## Изменения

- Отсутствующий `limits` и пропущенные поля теперь материализуют8MB/2048/60. Явный прежний набор2MB/256/15 сохраняется. В ServiceConfig очередь имеет собственные `limits`; настройки корпуса находятся в графовой Policy по `core.policy_path`.
- Corpus/file-count/inventory/time abort возвращает существующий FAILED/budget_exhausted с безопасным сообщением о настроенном пределе. Короткий русский комментарий сохраняет диагноз. Это не отсутствие влияния, не исправление прежних рисков и не успешный частичный анализ.
- Отдельный collector не сохраняет частичный context после глобального abort. Oversize-файл остаётся file_limit/PARTIAL по прежним правилам; недоступный repo также не становится полным покрытием. Unknown exception text/path/source не выводится. Transient retry/model gates не менялись.
- В Git `max_files` не равен числу всех gaps или файлов на диске: часть пропусков внутри GitReader не входит в inventory. Byte budget может учитывать размер blob, который затем будет пропущен как LFS/binary. Эти существующие особенности разъяснены в инструкции, механика не переписана.

## Приёмка actual defaults

[Campaign](campaign.json) загружает прежние pinned corpus manifests, **удаляет `policy.limits` из новых входов**, проверяет материализованные defaults и запускает стандартный benchmark. Общий валидатор Policy материализует их перед CoreAnalyzer; отдельные сервисные тесты также проверяют конструктор CoreAnalyzer с отсутствующим/частичным блоком. Это не оставленная в manifest именованная test policy. Публичные копии входов без roots — в [stages](stages/); полные исходные inputs с hashes остаются private.

| Корпус | Workers | Индексация | Первый анализ | Повтор |
|---|---:|---:|---:|---:|
| 5 / 50k | 1 | 2.652 | 8.141 | 8.134 |
| 10 / 100k | 3 | 5.153 | 16.117 | 16.151 |

Время — измеренные секунды, для5/50k одно наблюдение, для10/100k медиана трёх независимых worker-процессов. В каждом новая application state, initial index, first/warm и reference без instrumentation. Выполнение последовательное, OS caches/внешняя нагрузка не контролировались. Таблица не является production p95 или доказательством ускорения. CPU self/children и lifetime ru_maxrss — [metrics.json](metrics.json); RSS не stage-local и не сумма одновременно живущего дерева процессов.

В каждом из4 workers instrumented/reference результаты и canonical facts совпали. Оба корпуса имеют8 операций/3 calls,110/220 файлов и50k/100k строк (около1.27/2.54MB). Coverage всех выполненных контекстов полная в разрешённом статическом профиле. Это синтетический sparse-корпус с filler-кодом. С прежней явно настроенной8MB серией из removal-2026-11-15 совпадают canonical facts, result summaries и полные semantic output hashes положительных сценариев; [точное сравнение](prior-version-comparison.json). Новая диагностика отказов, напротив, намеренно изменилась.

Очередь проверена после timing, одним worker и настоящими часами, на локальном transport/DirectorySink:

- 5 независимых PR на5/50k: каждый выполненный результат проверен,5 комментариев, duplicate replay/reopen без дополнительных комментариев.
- 10 обновлений одного PR burst на10/100k: coalesce до одного анализа актуального head, один комментарий, replay/reopen.

Все ожидаемые поколения учтены, не только последний успешный head. Это конечные bounded workloads, не steady-state capacity и не реальные Bitbucket/Kaiten/Jira/API задержки. [Queue/controls](acceptance/), [raw spans и metadata](stages/).

Отдельный [raw per-file control](acceptance/per-file-control.json) проверен в WORKTREE и pinned Git: файл65 537 байт пропущен, остальной граф сохранён, PARTIAL/file_limit. Различие inventory этих режимов отражено в receipt.

Контроли сохранены раздельно: explicit legacy2MB на10/100k по-прежнему даёт corpus_limit/analysis_fraction0;9/10 доступных репозиториев даёт PARTIAL/commit_unavailable; actual default на140 одинаковых Git blobs по60 000 байт (добавлено8.4MB) даёт FAILED/budget_exhausted и видимый лимит8 000 000 байт, без сохранённого частичного context. Сжатие/повторное использование blob не обходят логический byte budget. Это авторский технический fixture, не новый independent case.

## Проверки и границы

Graph302,performance75,service104 — GREEN. Focused12 дополнительно включает фактический8.4MB refusal (этот тест добавлен после загрузки основной service suite); counts пересекаются. [Сохранённые запуски и сбои по именам](tests.json), [логи](logs/). Initial RED, ошибки первоначального test fixture/import и промежуточный failed run сохранены. После исправления fixture исходный CoreAnalyzer изca81bfb отдельно воспроизвёл неправильный internal_error на настоящем pinned Git вводе; текущие tests GREEN. Production source не откатывался ради теста.

Общий project CI в этой пачке заново полностью не прогонялся; прежний graph_demo CLI deadline mismatch остаётся открытым release10 пунктом. Проверено перечисленное покрытие, не заявляется общий зелёный CI или установка нового релиза. Fresh review и решения — [review.md](review.md).

Оригинальные manifests/oracles/измерения/evaluation/raw не перезаписывались. [Historical hashes](historical-hashes.json), [private corpus hashes](corpus-hashes.json), [tested sources](source-hashes.json), [артефакты](artifact-hashes.json). Author40 не запускался заново в этой пачке, scorer/normalizer не менялись; прежние TP20/FP0/FN0 относятся к прежней author-серии. Независимая06 остаётся NOT_REGISTERED/NOT_RUN. Replacement binding — следующая техническая задача; Яндекс09 и общая приёмка10 сохраняются.

## Воспроизведение

Использовать checkoutfd3dbc3, прежние private corpora и новые output directories. [Recorded recipes](reproduce/) не скачивают данные, не исполняют анализируемый код и отказываются перезаписывать результаты. Для нового запуска заменить общий `work/batch05-defaults` на новый private root во всех recipes. Source/test suites завершаются до stage timing; во время timing другие проверки не запускать.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python /tmp/run_default_limits_campaign.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python /tmp/capture_default_refusal.py
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:. python /tmp/capture_per_file_control.py
python experiments/impactmap_scale/defaults-2026-11-15/verify_artifacts.py --current-core --private
```

Перед командами recipes скопировать соответствующие recipes из отчёта в указанные /tmp пути. Campaign recipe создаёт новый work root и до записи inputs проверяет отсутствие всех зарезервированных outputs; существующие результаты не перезаписываются. Bootstrap guard добавлен после ревью и не меняет выполненные benchmark-команды. Без флагов verifier проверяет переносимые hashes, metadata и неизменность прежних отчётов; `--current-core` требует точные tested sources, `--private` также проверяет исходные pinned manifests/oracles/implicit input hashes. Он не запускает новый анализ или новые попытки и не заменяет independent review/качество.
