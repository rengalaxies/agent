# Пачка 5А: коробка на Linux-ВМ

Задача [#53](https://github.com/rengalaxies/agent/issues/53), первая часть. #53 не
закрывается: Linux-приёмка ещё не прошла, 5Б не начата.

Ветка `claude/objective-feistel-a46433`. Проверки этой сессии выполнены на Windows 11,
Python 3.14.5, Git 2.55. Linux здесь нет: нет Docker, WSL и ВМ. Linux-приёмку делает
workflow `.github/workflows/agent-service-box.yml`, он запустится, когда владелец
откроет PR. До этого ни одна строка ниже не означает «проверено на Linux».

## Состояние

| | Что |
|---|---|
| Реализовано | закреплённый релиз с manifest, единый установщик `box` (plan, install, update, status, doctor, backup, backups, restore, rollback, sync-mirrors), три уровня готовности, Git-зеркала с таймером, ежедневная копия, откат с проверкой схемы, приёмка установленной коробки, Linux-workflow, правки демо-поставки |
| Проверено офлайн (Windows) | 41 unit-тест коробки; 9 из 9 сценариев приёмки на установленном релизе с супервизором `process`; воспроизводимость архива (две сборки дают один sha256); 79 тестов `tests/service` без изменений |
| Проверено на Linux | ничего. Workflow написан, но ещё не запускался |
| Не проверено | systemd-путь целиком (unit, hardening, `Restart=on-failure`, таймеры, пользователь `agent-service`); живые GitHub/Jira; модель; реальная ВМ и её размер; TLS-прокси для webhook; активные минуты человека (есть только оценка) |

## База и порядок PR

Бриф задавал базу 2А и PR против `claude/mvp-2a-core-205322`. Коробка ставит
`agent_service`, а он есть только в ветке 4. Поэтому в эту ветку обычным merge влита
`origin/claude/mvp-4-service-2a` (`dd64229`, она уже содержит 2А и 3). Без неё
CI на PR против 2А было бы нечего устанавливать, кроме старого демо. Вопрос о базе
отправлен координирующей сессии; ответа к моменту отчёта нет.

Предлагаемый стек: 2А → 3 → 4 → 5А, PR этой ветки против `claude/mvp-4-service-2a`:
https://github.com/rengalaxies/agent/compare/claude/mvp-4-service-2a...claude/objective-feistel-a46433

Если координатор оставит PR против 2А, его diff покажет и коммиты 3 и 4. Мои коммиты
трогают только пути строки `mvp-5a-box` и переносятся cherry-pick без конфликтов.

## Коммиты

| Коммит | Что |
|---|---|
| `b98a345` | merge ветки 4 (`dd64229`) |
| `c2f7619` | hash-lock зависимостей релиза |
| `7e46445` | сборка и проверка релиза, bootstrap, точка входа сервиса |
| `85ca1e9` | установщик: фазы, журнал, status/doctor, backup/restore, update/rollback, зеркала |
| `ad5d9a8` | unit-тесты коробки |
| `f8edd29` | стенд и драйвер приёмки установленной коробки, варианты релиза для update |
| `1ff0071` | Linux-workflow |
| `c77262e` | демо: ядро внутри образа, без отдельного checkout |
| `c8df16b` | демо: инструменты без `os.geteuid` на Windows |

## Релиз

Формат: один воспроизводимый архив на коммит и платформу.

```
agent-service-<version>-g<sha12>-<platform>/
  box              установщик (копия tools/agent_service/box/bootstrap.py)
  manifest.json    commit, хеш каждого файла, хеши колёс, версии ядра, конституции и схем
  app/...          blob-ы разрешённых путей, прочитанные из коммита (не из рабочего дерева)
  wheels/*.whl     зависимости, каждая есть в infra/agent_service/requirements.lock
```

В архив входят `src/agent_graph`, `src/agent_service`, `constitutions/agent-service-v1.yaml`,
`schemas/agent-graph-output-2.json`, `examples/orders_reporting` (нужен offline smoke),
`tools/agent_service/box`, `infra/agent_service`. Тесты коробки и всё остальное не входят.
Тег версии ничего не доказывает: идентичность релиза это sha256 архива и commit в
manifest. Два build одного коммита дают байт-в-байт один архив (mtime из времени коммита,
gzip без времени, сортированные записи). Между разными машинами это не обещано: zlib
другой версии может сжать иначе.

Зависимости: 17 пакетов, одна версия и sha256 колеса на каждую платформу
(`linux-x86_64-cp312` для ВМ, `win-amd64-cp314` для машины разработки). На ВМ колёса
распаковываются в venv релиза без pip и без сети, поэтому пакет `python3-venv` не нужен.

### Версия этого отчёта

Собрано локально из `c8df16b` (последний коммит с содержимым релиза) с колёсами
`linux-x86_64-cp312`:

| | |
|---|---|
| release_id | `0.1.0+gc8df16bd1112.linux-x86_64-cp312` |
| архив | `agent-service-0.1.0-gc8df16bd1112-linux-x86_64-cp312.tar.gz`, 8 962 108 байт |
| sha256 архива | `c0273146f3622c0c8d1b77c95f9605ff68686921b24dbbfae359cb113dc8c411` (две сборки совпали) |
| sha256 manifest | `b1c32abad608ba5782b48b5985e64dca57768eec58e23c703e5b6f415f128b0d` |
| commit / tree | `c8df16bd1112d13d9dc097efd76e2bcf96a6b14f` / `03b4e48c7d594c32d500bafc20186b10eb4419a3` |
| файлов app | 66 |
| lock sha256 | `59f6e53fef91326de7c4d1402b28a2967d4ed8bb5bb406a0b93e8c7688fc5586` |

CI собирает релиз из merge-коммита PR, поэтому у него будет другой SHA и другой архив.

### Безопасный manifest (выдержка)

Manifest не содержит секретов, путей машины сборки и времени сборки:

```json
{
  "format": "agent-service-release-1",
  "release_id": "0.1.0+gc8df16bd1112.linux-x86_64-cp312",
  "platform": "linux-x86_64-cp312",
  "python": "3.12",
  "code": {"repository": "github.com/rengalaxies/agent",
           "commit": "c8df16bd1112d13d9dc097efd76e2bcf96a6b14f",
           "tree": "03b4e48c7d594c32d500bafc20186b10eb4419a3",
           "committed_at": "2026-10-25T10:14:21Z"},
  "contracts": {
    "core": {"profile": "http-requests-4", "schema": "agent-graph-1", "output_schema_version": "2.1",
             "core_digest": "e4af17aeae236fb3f1e769ec88808e57774bc58837d3d440dc097e09e81991b7"},
    "constitution": {"path": "constitutions/agent-service-v1.yaml",
                     "version_id": "agent-service-v1.0:100bcad3db9c"},
    "state": {"service_store": {"version": 1, "opens": "equal"},
              "graph_store": {"version": 2, "opens": "older_or_equal"}}
  },
  "dependencies": {"lock": "infra/agent_service/requirements.lock",
                   "lock_sha256": "59f6e53f...", "wheels": {"fastapi-0.141.1-py3-none-any.whl": "bfb91aa2...", "...": "..."}},
  "files": {"app/src/agent_graph/__init__.py": "<sha256>", "...": "..."}
}
```

`contracts` вычисляет сам код при сборке: `agent_graph.core_identity()`,
`agent_graph.constitution.load()`, `output_contracts.SCHEMA_VERSION`, `store.STORE_SCHEMA`,
`agent_service.queue.SCHEMA_VERSION`.

### Какую версию загрузил процесс

`launch.py` (ExecStart unit) перед запуском сервиса сверяет все файлы своего релиза с
manifest, импортирует ядро, сравнивает `core_identity()` с manifest и пишет в
`/var/lib/agent-service/run/loaded.json` релиз, commit, ядро, конституцию и свой PID.
`box status` считает процесс готовым, только если PID из systemd равен PID в этом файле
и релиз и ядро совпадают с активным manifest. Так статус показывает, что загрузил
работающий процесс, а не что лежит на диске.

## Установщик

`tools/agent_service/box/`, точка входа в релизе `./box`, после установки
`/usr/local/sbin/agent-service-box`.

Фазы `install`: validate → release → configure → mirrors → probes → [backup] → graph →
start → smoke → report. Команды и планы задаёт этот код; вывод модели в установке не
участвует.

| Фаза | Что делает | Повторный запуск |
|---|---|---|
| validate | box.yaml, секреты по именам, git ≥ 2.31, systemd, диск, порт; план изменений | без изменений |
| release | сверка релиза с manifest | тот же релиз не раскладывается заново |
| configure | пользователь `agent-service`, каталоги и права, токен `/status`, `service.json` | файлы пишутся только при отличии |
| mirrors | `git clone --mirror` или `fetch`, `policy.json` с вершинами веток | только fetch |
| probes | чтение веток и PR в GitHub, поиск в Jira с настоящими учётными данными | то же |
| backup | только при смене релиза: стоп сервиса, копия `pre-update` | прерванное обновление берёт ту же копию |
| graph | начальный граф по веткам по умолчанию, от пользователя сервиса | идемпотентно (ядро 3) |
| start | unit systemd на точный релиз, запуск или перезапуск, ожидание готовности | работающий нужный процесс не трогается |
| smoke | `agent_service smoke` из установленного релиза | то же |
| report | три уровня готовности, отчёт в `/var/lib/agent-service-box/reports/` | то же |

Журнал `/var/lib/agent-service-box/box.json` хранит активный релиз, историю, точку отката
и фазы текущего запуска. Блокировка не даёт запустить два box сразу.

Код выхода `install`: 0 сценарий готов, 2 сервис работает, но сценарий не готов (причины
напечатаны), 1 установка не завершена.

### Конфигурация одним файлом

`/etc/agent-service/box.yaml` по образцу `infra/agent_service/box.example.yaml`: установка и
окружение, репозитории и сервисы, адреса сервисов, файл ownership, модель и ссылка на её
квалификацию, публикация, конституция (по умолчанию из релиза), свежесть, лимиты, хранение
копий. Значения секретов лежат только в `/etc/agent-service/secrets.env` (root, 600),
box.yaml содержит их имена. Ошибки конфигурации называют поле и не повторяют значение.

### Три уровня готовности

| Уровень | Значит |
|---|---|
| живость | `/healthz` ответил |
| процесс | PID из systemd = PID в `loaded.json`, релиз и ядро из manifest, `/status` принимает токен |
| сценарий | граф не пуст, все источники кода свежие, проверки GitHub/Jira прошли, нет уведомлений сервиса (`connection_unauthorized`, `graph_source_unavailable`, `model_disabled` и др.), smoke прошёл |

HTTP 200 от `/healthz` готовым сценарий не делает. `doctor` дополнительно повторяет
проверки GitHub/Jira с текущими секретами, проверяет конфигурацию и возраст копий и для
каждого кода причины печатает, что сделать, не печатая значений секретов.

### Git-зеркала

Ядро никогда не делает fetch (2А), сервис 4 тоже. Поэтому зеркала ведёт коробка:
клон при установке и `agent-service-sync.timer` каждые `mirror_sync_seconds` (120 с).
Токен GitHub (App или PAT) попадает в git только через `GIT_CONFIG_*` переменные
окружения и только для хоста GitHub. Ошибки git превращаются в коды
(`git_credentials_rejected`, `git_repository_not_found_or_no_access`, `git_host_unreachable`,
`git_branch_not_found`).

### Разделение релиза и состояния, права

Релиз в `/opt/agent-service/releases/<имя>` принадлежит root и только читается.
Состояние в `/var/lib/agent-service` принадлежит `agent-service` (700). Unit:
`User=agent-service`, `ProtectSystem=strict`, `ReadWritePaths=/var/lib/agent-service`,
`PrivateTmp`, `NoNewPrivileges`, без доступа к Docker и инфраструктурным credentials.
Секреты читает systemd из файла root 600. Ключ GitHub App получает группу `agent-service`
и права 640. Чтение SQLite от root может создать `-wal`/`-shm` с владельцем root; box
возвращает их пользователю сервиса перед каждым запуском.

### Backup, restore, update, rollback

Копия: `service.sqlite` (события, задания, publication intent с id комментариев,
append-only история, уведомления, контрольные точки сверки) и `graph.sqlite3` через
online backup API SQLite, плюс box.yaml и сгенерированная конфигурация. Каждая копия
проходит `integrity_check` и записывает sha256 файлов, версии схем и число строк.
Restore проверяет хеши до любых изменений, делает страховочную копию текущего
состояния и после восстановления сверяет число строк. Зеркала, секреты и релиз в копию
не входят.

Путь возврата миграции БД проверяемый и записан в manifest (`contracts.state`):

- очередь сервиса открывается только той же версией схемы (`agent_service.queue`
  бросает `unsupported_state_schema`);
- граф мигрирует только добавлением таблиц и открывается релизом с той же или более
  новой версией (`agent_graph.store._migrate`).

`rollback` читает версии схем из файлов. Совместимо: переключается только релиз,
события и комментарии после обновления остаются. Несовместимо: box восстанавливает копию
`pre-update`, сделанную при уходе с целевого релиза (точка отката из журнала), и
запускает его. При старте сервис сверяется с Jira/GitHub и подтягивает события после
копии; комментарий находится по маркеру и обновляется (publisher 4 ищет маркер перед
каждым create). Откат образа без отката схемы box не выполняет: если подходящей копии
нет, он отказывается и оставляет сервис как был.

`update` сам откатывается на прежний релиз, если новый процесс не стал готовым.

## Приёмка установленной коробки

`tools/agent_service/box/acceptance.py` управляет коробкой так же, как владелец (`./box ...`),
и смотрит на комментарии в стендах. `teststand.py` поднимает Git-стенд Orders/Reporting и
HTTP-стенды GitHub/Jira из `agent_service.stands` и пишет box.yaml и secrets.env для них.
`variants.py` делает из того же коммита релиз C (новая версия, та же схема) и B (схема
очереди 1 → 2 с добавочной миграцией). Все три релиза собираются настоящим `release.py`.

| Сценарий | Что проверяет |
|---|---|
| fresh_install | установка с нуля даёт READY; процесс загрузил ядро и релиз из manifest; сверка при старте сама публикует по одному комментарию на PR и задачу |
| end_to_end_on_installed_release | новый head PR → комментарий с head `pr-7` и `PAGE_DEFAULT_CHANGED 100 -> 20`, тот же комментарий обновлён |
| reinstall_is_idempotent | повторный install: процесс не перезапущен (тот же PID), зеркала только fetch, конфигурация не переписана, граф и комментарии те же, один процесс сервиса |
| interrupted_install_is_finished_by_rerun | установщик убит после configure, в начале mirrors, после graph, после start, в начале smoke; повторный запуск доделывает и пишет `resumed_after` |
| service_killed_comes_back | процесс сервиса убит: systemd перезапускает (на Windows: повторный install) |
| doctor_wrong_credentials | неверный `GITHUB_TOKEN`: doctor выходит с 1, называет `probe:github:...:connection_unauthorized`, значения токена в выводе нет |
| backup_restore | копия, изменение Jira после копии, restore: строки как в копии, изменение возвращается сверкой как обновление того же комментария |
| update_same_schema_then_rollback | A → C с копией pre-update, событие обработано C, откат `release_only` |
| update_schema_change_then_rollback | A → B (схема 2), событие обработано B, откат `restored_backup`, сверка возвращает изменение, комментарий не создан повторно |

Во всех сценариях проверяется, что на PR и на задачу ровно один комментарий сервиса и
каждый создан один раз (счётчик POST в стенде).

### Результат на Windows (супервизор `process`)

Прогон 2026-10-25 10:14–10:18 UTC, релизы A, C, B собраны из `c8df16b` и двух
вариантов от него; свежий стенд и пустой префикс. 9 из 9 PASS:

| Сценарий | Результат | Секунды |
|---|---|---|
| fresh_install | PASS | 22.3 |
| end_to_end_on_installed_release | PASS | 2.1 |
| reinstall_is_idempotent | PASS | 16.7 |
| interrupted_install_is_finished_by_rerun | PASS | 87.8 |
| service_killed_comes_back | PASS | 24.0 |
| doctor_wrong_credentials | PASS | 6.2 |
| backup_restore | PASS | 6.2 |
| update_same_schema_then_rollback | PASS | 28.7 |
| update_schema_change_then_rollback | PASS | 25.3 |

В откате через схему box восстановил копию `pre-update`, сделанную при уходе с A
(`schemas_on_disk: service_store 2`), и сделал страховочную копию `pre-rollback`.

По пути пришлось исправить три дефекта, которые нашла эта приёмка: журнал box читался в
кодировке консоли Windows и молча обнулялся; кодовые источники графа называются `git`, а
не `code`; на Windows `python.exe` venv запускает интерпретатор дочерним процессом, поэтому
`loaded.json` хранит и PID лаунчера.

Это не Linux-приёмка: здесь нет systemd, пользователя сервиса, hardening, таймеров и
`Restart=on-failure`. Супервизор `process` есть только для разработки.

### Linux

`agent-service-box.yml` на `pull_request` (ubuntu-24.04, systemd, `/usr/bin/python3` 3.12):
unit-тесты коробки, две сборки A с `cmp` архивов, сборка C и B, `sha256sum -c`,
`box plan`, затем тот же драйвер приёмки от root через systemd. В summary попадает
таблица сценариев, время установки и RSS сервиса. Артефакт: отчёты установок,
manifest, `acceptance.json`, журнал unit (токен статуса вычищается) и архив релиза A.
Секретов, внешних публикаций и облачных ресурсов нет. Результата пока нет: PR не открыт.

## Время

### Машинное время (замер, Windows, супервизор process)

| Что | Секунды |
|---|---|
| установка с нуля, от `./box install` до отчёта (вместе с раскладкой релиза и venv) | 20.9 |
| из них фазы установщика | 16.3 |
| фазы: validate 0.09, release 0.05, configure 0.01, mirrors 0.98, probes 0.68, graph 1.23, start 3.76, smoke 8.81, report 0.66 | |
| повторный install без изменений | 13.0 |
| update A → C / A → B (с копией и миграцией) | 18.3 / 15.1 |
| все 10 завершённых install в прогоне | 11.5–18.3 |

Больше половины времени установки занимает offline smoke (9 с). Стенд маленький: пять
репозиториев по несколько файлов. Время графа на репозиториях компании не измерено.

На Linux цифры будут в summary workflow. Экстраполировать Windows на Linux не надо.

### Активные минуты человека (оценка, не замер)

| Шаг | Оценка | Комментарий |
|---|---|---|
| GitHub App: создать, права, установить на репозитории, скачать .pem | 10–15 мин | однократная выдача доступа, коробка её не заменяет |
| Jira: учётная запись бота, API token, accountId | 5 мин | однократно |
| скопировать архив на ВМ, `sha256sum -c`, `tar -x` | 2 мин | две команды |
| заполнить box.yaml (около 10 полей), secrets.env (5 строк), ownership.json | 10–15 мин | один файл конфигурации плюс файл секретов |
| `sudo ./box install`, прочитать итог | 1–2 мин | одна команда; при проблеме doctor говорит, что исправить |
| webhook в GitHub App и Jira на адрес TLS-прокси | 5–10 мин | необязательно: без webhook работает сверка раз в 15 минут |

Итого 30–50 минут один раз, из них около 25 минут уходит на выдачу доступов в GitHub и
Jira. После установки регулярных действий нет: зеркала, сверка и ежедневная копия идут по
таймерам. Человека с секундомером не было, поэтому это оценка по числу шагов.

## Демо-поставка (пункты 3 и 4 из batch-2a.md)

- `infra/agent_graph_demo/Dockerfile` копирует `src/agent_graph` и
  `constitutions/agent-service-v1.yaml` того же коммита; `core.lock.json`, `COPY` его и
  монтирование `/core` в `compose.yaml` убраны; `images.json` и README описывают ядро в образе.
- `tools/agent_graph_demo/{accept,configure}.py`: `--core-root` необязателен; без него
  демо работает на своём ядре; отчёт приёмки пишет `agent_graph.core_identity()` вместо
  `core_sha`.
- `inspect_delivery.py` сверяет образ с `src/agent_graph` и конституцией вместо `core.lock.json`.
- `effective_uid()` вместо `os.geteuid()` в `state_access.py`, `runtime_guard.py`,
  `check_packaging.py`. `tests/graph_demo` на Windows: было 7 ошибок из 38, стало 1
  (тест запускает shebang-скрипт напрямую, это не мои пути).
- PyYAML в `infra/agent_graph_demo/requirements.lock` не добавлен: проверено, что веб,
  worker и CLI ядра демо импортируются без него.

Старое демо остаётся отдельной демонстрацией HTTP-графа. Установка продукта одна:
`infra/agent_service` и `box`. Второго процесса установки для сервиса нет; 5Б должна
вызывать этот же `box` на созданной ВМ.

## Что нужно поменять вне путей этой сессии

1. `.github/workflows/agent-graph-demo.yml` (mvp-2a-core): `DEMO_CORE_ROOT` и
   `--core-root "$DEMO_CORE_ROOT"` больше не нужны; без них acceptance работает на
   ядре образа.
2. `docs/agent-graph-demo/RUNBOOK.md`: строки про внешний checkout `18e8b71`,
   `core.lock.json` и монтирование `/core` устарели.
3. `.github/workflows/agent-graph-demo-delivery.yml` всё ещё архивирует `core.tar.gz` из
   `18e8b71`; после этой правки он не нужен.
4. mvp-4-service: событие PR с новым head может прийти раньше, чем таймер зеркал сделает
   fetch (до 120 с). Сейчас это закрывают повторы задания с backoff. Fetch нужного
   репозитория перед анализом сократил бы задержку; коробка для этого готова отдать
   функцию `mirrors.sync`.
5. mvp-4-service: `/status` мог бы сам отдавать `loaded.json`. Сейчас box читает файл с
   диска и сверяет PID.

## Ограничения

- Linux, systemd и hardening не проверены (см. выше).
- Один хост GitHub, одна Jira, одна установка на ВМ. Несколько установок на одной ВМ
  box не поддерживает.
- Webhook снаружи требует TLS-прокси компании; box его не ставит.
- Автоматический откат при неудачном update проверен только косвенно: сценария с
  релизом, который не стартует, в приёмке нет.
- Публикация в живые GitHub/Jira, модель и квалификация 2Б в коробке не проверялись:
  ключей и тестового контура нет.
- Размер ВМ (2 vCPU, 2 ГБ) ориентир; RSS сервиса будет в Linux-summary.

## Как воспроизвести

```bash
python -m pip install --require-hashes -r infra/agent_service/requirements.lock
```

```bash
PYTHONPATH=src:. python -m unittest discover -s tools/agent_service/box/tests -t . -v
```

```bash
python tools/agent_service/box/release.py build --commit HEAD --platform linux-x86_64-cp312 --output dist
```

Приёмка на машине без systemd (как в этом отчёте) идёт с `--prefix <каталог> --supervisor process`;
шаги собраны в workflow.

## Следующий шаг

Владелец открывает PR (база по решению координатора, предложено
`claude/mvp-4-service-2a`). Workflow `agent-service-box` даёт первую Linux-приёмку;
результаты таблицы сценариев переносятся сюда. После этого 5Б вызывает тот же `box`
на ВМ Cloud.ru.
