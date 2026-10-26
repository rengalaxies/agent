# Состояние автономного MVP

Задание владельца от 24.10.2026: пачки 2А, 2Б, 3, 4, 5А, 5Б и 6. Порядок
интеграции `2А → 3 → 4 → 5А → 5Б → 6`, 2Б после 2А. Решения и их причины
записаны в [DECISIONS.md](DECISIONS.md). Подробности каждой пачки лежат в
`batch-N.md`; этот файл держит только сводку и следующий шаг.

Слова в таблицах значат одно и то же везде:

- реализовано: код есть в ветке;
- проверено офлайн: тесты и стенды без внешних систем прошли на указанном коммите;
- проверено live: прошло на настоящей модели, Jira, Git-хостинге или ВМ;
- не проверено: нет доступа или проверка не выполнялась, причина указана.

## Окружение исполнителей

Проверено 24.10.2026 на машине владельца: Windows 11, Git 2.55, Python 3.14.5.
Нет Docker, WSL, Linux VM, `gh`, ключей Cloud.ru, Jira и модели. Linux
проверяется только в GitHub Actions на PR (с 25.10.2026, когда владелец открыл
PR #56–#60); live-проверки ниже помечены как непроверенные. Публичный GitHub
API читается без токена, но ограничен 60 запросами в час на IP; логи заданий
без входа недоступны, публичны только annotations.

## Пачка 1. Сверка принятого контекста

Состояние: исторически завершена. Новые инженерные возможности не реализованы
этой пачкой и остаются открытыми в 2А–6.

Сверка 24.10.2026 (GitHub API и `git fetch`):

- `main` = `9d7480d0ab1ea3ac58fe4ccecc1cc2279bd21bc8`, совпадает с отправной точкой
  задания. После неё в `main` ничего не появилось.
- Открытых PR нет. PR #44–#49 слиты.
- Итоговая задача пачки 1 [#55](https://github.com/rengalaxies/agent/issues/55)
  закрыта. Задачи [#50](https://github.com/rengalaxies/agent/issues/50)–[#54](https://github.com/rengalaxies/agent/issues/54)
  открыты, без комментариев; их тексты совпадают с направлением задания и
  `docs/product/pilot/TRACKING.md`. Последующих решений, заменяющих их, нет.
- Новые ветки после `9d7480d` есть только у параллельных сессий этого задания.
- Ограничения исходного состояния из раздела 2 задания подтверждены по коду:
  `Repository.revision` не проверяется, демо закрепляет ядро
  `18e8b71b39eb6d2368d40ffb3892b9a5cdf2cd70` отдельным checkout, worker вызывает
  CLI на каждую цитату, `analyze_change` знает три вида delta.
- Дополнительно: ядро на исходном `main` не импортируется на Windows
  (`fcntl` в `store.py`, `O_NOFOLLOW`/`dir_fd` в `sources.py`). Отчёт серии
  22.10 уже отмечал это для `Store`.

## Сводка на 26.10.2026

PR #61 слит владельческим разрешением: merge `c64c949e2c3558cbfea0c62922d141355d6684c9`, его
дерево равно проверенной голове `2bfcb78`, на `main` после merge прошёл workflow lint; core,
box и configuration запускаются только на pull request и были зелёными на этой голове.
Реестр: [PR-REGISTER.md](PR-REGISTER.md).

Доступ исполнителя: аккаунт `swan-Dive`, право `write`, `gh` с scopes `repo, workflow`.
`main` без branch protection и rulesets. Среды `cloudru-box-production` и `cloudru-box-review`
созданы владельцем: required reviewers `rengalaxies` и `swan-Dive`, только `main`,
`prevent_self_review` выключен, `can_admins_bypass` включён. Исполнитель не одобряет
развёртывания, которые запустил сам; самоодобрение для `autonomous-mvp-live` к тому же
заблокировано политикой исполнителя.

| Что | Где | Состояние |
|---|---|---|
| Два дефекта продукта из 6-r1 | [#64](https://github.com/rengalaxies/agent/pull/64) | исправлены в `src/agent_service`, регрессии и negative controls; `tests/service` 118 OK (Windows); CI box и core зелёные на `2b096ad`; fingerprint 2Б не изменился (`8d1c1afc`) |
| Ревизия 6-r2 | [#63](https://github.com/rengalaxies/agent/pull/63) | заморожена `cbf0e71`, manifest `45f49527`; held-out 65/65, technical и quality PASS без модели; 6-r1 сохранена с FAIL (`batch-6.md`) |
| 5Б: plan без записи state, публикация релиза | [#62](https://github.com/rengalaxies/agent/pull/62) | recovery только в одобренном apply, `agent-service-release.yml`, сверка квот, инвентаризации и тарифов 261014 (`batch-5b.md`) |
| Серия 2Б | `autonomous-mvp-model.yml` | не выполнена. Transport на `c64c949` (run 40220149802) ждал одобрения среды и отменён до старта: серия требует неподвижной `main`, а #62–#64 ещё сливаются. Учётных веток нет. Серия пойдёт на итоговой `main` |
| Облако | Cloud.ru | ничего не создано; read-only discovery 40266720846: место под 1 IP и 2 vCPU есть |

Порядок дальше: слить #64, затем #63 (содержит #64), затем #62 → итоговая `main` →
серия 2Б transport → development → evaluation-1/2/3 → report с одобрением каждой фазы
владельцем → при QUALIFIED конфигурация `service-model` 6-r2 → публикация релиза и pin →
`lock-test` → `plan` → одобрение конкретного apply.

## Сводка на 25.10.2026, вечер

Стек #56–#60 слит в `main` (`0f0dc02`, реестр в [PR-REGISTER.md](PR-REGISTER.md)).
Итоговая оценка готовности: [READINESS.md](READINESS.md).

Окружение исполнителя этой части: аккаунт GitHub `swan-Dive`, право `write` (не admin),
токен со scopes `repo, workflow`; входит в required reviewers окружения
`autonomous-mvp-live`, `prevent_self_review` выключен, окружение пускает только `main`.
Локально Windows 11, Python 3.14.5, `gh` нет: GitHub API через токен Git credential manager.

### Исправительная пачка, PR #61

Ветка `claude/mvp-recovery-fixes` от `main` `0f0dc02`. Закрывает P1, P1 и P2 ревью #60,
неполный допуск модели и SC2024 ([issue #8](https://github.com/rengalaxies/agent/issues/8)).
Решения D10–D12 в [DECISIONS.md](DECISIONS.md).

| Проверка | Где | Код | Результат |
|---|---|---|---|
| Новые сценарии приёмки на исходной `main` | Windows, `process` | `0f0dc02` | `first_schema_update_then_rollback` FAIL (копия pre-update со схемой 2), `failed_start_rolls_back` FAIL (работает D вместо A), `update_other_constitution_then_rollback` FAIL (загруженная идентичность не та) |
| Новые unit-тесты restore на исходном `state.py` | Windows | `0f0dc02` | 5 из 5 FAIL |
| Приёмка установленной коробки, 11 сценариев | Windows, `process` | `0d02c17` | 11 из 11 PASS |
| `tools/agent_service/box/tests`, `tests/service`, `tools/autonomous_mvp/tests` | Windows | `e4eb7f3` | 46, 98, 80 тестов OK |
| Корпус, эталон, manifest 2b-r1 | Windows | `e4eb7f3` | CHECKED 80; 77 случаев, 0 ошибок; MANIFEST_CURRENT `8d1c1afc…` |
| Linux-приёмка с systemd | [run 40214855779](https://github.com/rengalaxies/agent/actions/runs/40214855779), job 121233664757 | `5f71999` | 11 из 11 PASS, systemd 255 |
| Workflow lint с ShellCheck на PR | [run 40214855713](https://github.com/rengalaxies/agent/actions/runs/40214855713) | `5f71999` | success; SC2024 больше нет |
| Core research regression, P1 regression | runs 40214855723, 40214855791 | `5f71999` | success |

Первый Linux-прогон ([40214160008](https://github.com/rengalaxies/agent/actions/runs/40214160008), `e4eb7f3`) упал на
двух сценариях: проверка порта в `validate` считала занятым порт в TIME_WAIT после
остановленного сервиса. Это прежний дефект, новый сценарий убитого restore его вскрыл.
Исправлено в `5f71999` (SO_REUSEADDR на POSIX).

Граница доказательства: раннер GitHub, а не ВМ заказчика; стенды GitHub/Jira локальные.

## Сводка на 25.10.2026, до слияния стека

Весь стек открыт как PR и зелёный в Linux CI (GitHub Actions, ubuntu). Порядок
слияния: #56 → #57 → #58 → #60; #59 после #57. Live-проверки (модель, Jira,
GitHub App, ВМ) не выполнялись ни для одной пачки.

| Пачка | PR | Ветка, head | База PR | Офлайн | Linux CI | Live |
|---|---|---|---|---|---|---|
| 2А | [#56](https://github.com/rengalaxies/agent/pull/56) | [`claude/mvp-2a-core-205322`](https://github.com/rengalaxies/agent/tree/claude/mvp-2a-core-205322) `09cad7e` | `main` | проверено (Windows) | все задания зелёные; код зелёный с `4d10897`, дальше только документы | для приёмки 2А не требуется |
| 3 | [#57](https://github.com/rengalaxies/agent/pull/57) | [`claude/mvp-3-runtime-2a`](https://github.com/rengalaxies/agent/tree/claude/mvp-3-runtime-2a) `4454347` | 2А | проверено (Windows) | accept, citation-measurement, offline, core зелёные | не проверено: нет runtime-источника клиента |
| 4 | [#58](https://github.com/rengalaxies/agent/pull/58) | [`claude/mvp-4-service-2a`](https://github.com/rengalaxies/agent/tree/claude/mvp-4-service-2a) `339b6d0` | 3 | проверено (Windows) | core: 776 тестов OK, из них 79 `tests/service` (job 121143824127) | не проверено: нет GitHub App, Jira и права публикации |
| 2Б | [#59](https://github.com/rengalaxies/agent/pull/59) | [`claude/mvp-2b-prep-9d9655`](https://github.com/rengalaxies/agent/tree/claude/mvp-2b-prep-9d9655) `95decda` | 3 | проверено (Windows) | verify, core, configuration зелёные | не проверено: ни одного запроса к модели |
| 5А | [#60](https://github.com/rengalaxies/agent/pull/60) | [`claude/objective-feistel-a46433`](https://github.com/rengalaxies/agent/tree/claude/objective-feistel-a46433) `2fe2f41` | 4 | проверено (Windows, супервизор `process`) | установленная коробка с systemd: 9 из 9 сценариев (job 121143981931); accept, verify, configuration, core зелёные | не проверено: нет Linux-ВМ заказчика |
| 5Б, 6 | — | — | — | не начаты | — | — |

Результаты Linux CI для #57–#60 записаны по сообщению координирующей сессии,
которая читала логи прогонов; сессия 2А сама их не открывала. Linux CI — это
раннер GitHub, а не ВМ установки и не живой контур.

Устаревшие ветки: `claude/mvp-3-runtime-1b13b3` и `claude/mvp-4-service-814d77`.

## Пачка 2А. Воспроизводимое ядро и исполняемая конституция

Задача [#50](https://github.com/rengalaxies/agent/issues/50), исполнитель —
сессия `mvp-2a-core`, ветка `claude/mvp-2a-core-205322`. Подробно:
[batch-2a.md](batch-2a.md).

| Что | Состояние |
|---|---|
| Контракты `agent-graph-output 2.0`, `AnalysisResult` из выдачи ядра | реализовано, проверено офлайн (Windows) |
| Git-снимки, безопасное чтение, стенд Orders/Reporting | реализовано, проверено офлайн (Windows) |
| `UNCLASSIFIED_OPERATION_CHANGE`, шум и покрытие, регрессии #45/#46 | реализовано, проверено офлайн (Windows) |
| `actions-v3`, диагностика по слоям, конституция `agent-service-v1`, инструменты, гипотезы | реализовано, проверено офлайн скриптовой моделью и локальным HTTP |
| Без fan-out по цитатам, демо на поставляемом ядре | реализовано, проверено офлайн (Windows): 3 процесса на задание |
| CI: PyYAML в `graph-evidence-refs.yml`, демо без ядра `18e8b71`, тесты 2Б в `core-tests.yml` | реализовано, actionlint 1.7.7 без замечаний; на раннере не запускалось |
| Linux CI по PR [#56](https://github.com/rengalaxies/agent/pull/56) | все четыре workflow зелёные на `4d10897`, включая Docker и браузерную приёмку демо (batch-2a.md, раздел «Linux CI на PR #56») |
| Linux-время и память задания с 200 файлами-потребителями | измерено в прогоне [40174700283](https://github.com/rengalaxies/agent/actions/runs/40174700283) (`bcb502a`): 402 цитаты, 4 процесса и 0,88 с против 405 процессов и 54,5 с; пик около 39 МиБ на процесс (batch-2a.md) |
| Docker-шаг демо-CI | образ демо содержит ядро с `8ac841d`; браузерная приёмка обновлена в `4d10897` |
| Модельный цикл на настоящей модели | не проверено, это 2Б |

Недостающий доступ: нет; слияние #56 за владельцем.

Следующий шаг: слияние #56 владельцем; затем открытые пункты контракта из
таблицы ниже.

### Запросы к контракту 2.0 от других пачек

Часть пачки 3 закрыта её контрактом 2.1 (коммит `0fae0d4` в ветке
`claude/mvp-3-runtime-2a`): runtime-коды
freshness/unknown/gap и `Claim.subject`, при котором факт об операции требует
основания с тем же service/method/route. Версия 2.1 приходит в `main` с PR 3,
поверх PR 2А. Состояние каждого запроса — в последней колонке.

| От | Запрос | Состояние |
|---|---|---|
| 3 | Факт об операции не должен опираться на runtime-основание без маршрута | закрыто в 2.1 через `Claim.subject`; работает, только если субъект задан, кодовое основание не сверяется с операцией |
| 3 | `CallsiteEntity` с `line` меняет ID при вставке строки выше | хранилище пачки 3 использует `graph_store.callsite_id` без строки; в контракте `line` осталась, открыто |
| 3 | Коды `runtime_not_instrumented`, `runtime_route_not_recorded`, `runtime_route_conflict`, `GapCode` `runtime_window_gap` с интервалом, агрегаты sampling/4xx/latency | коды закрыты в 2.1; интервал у `Gap` и агрегаты открыты |
| 4 | `Name` без `/` для `owner/repo`; ключи Jira и изменённые файлы в `PullRequestTrigger`; `updated_at` с `+0000` | открыто; сервис обходит отображением и нормализацией |

### Проверка изменений пачки 3 в файлах 2А

24.10.2026 найден и затем закрыт блокер слияния PR 3. После `c6e5b53`
предложения видны любому view той же установки; достаточность зависимости
зависит и от карты адресов сервисов, поэтому переназначение адреса оставляло
старого кандидата CURRENT. Исправлено в `058f565` (digest адресов и
требований у предложения), перепроверено 2А на `f8781ae`. Подробности — в
разделе пачки 3 ниже.

## Пачка 2Б. Квалификация открытой модели

Отчёт: [batch-2b.md в ветке](https://github.com/rengalaxies/agent/blob/claude/mvp-2b-prep-9d9655/docs/implementation/autonomous-mvp/batch-2b.md),
голова `95decda` (PR [#59](https://github.com/rengalaxies/agent/pull/59), база — ветка 3).

| Что | Состояние |
|---|---|
| Программа `2b-r1`, корпус 1 + 20 + 40 случаев, эталон, manifest с объёмом и стоимостью | реализовано, проверено офлайн |
| Связка с исполнителем 2А (`actions-v3`, `run_investigation`) | реализовано, проверено офлайн: 70 тестов OK без пропусков |
| Dry-run всей программы через тот же код, что в live | проверен: 143 case-runs, вердикт QUALIFIED. Сценарий знает эталон, так что это проверка трубопровода и scorer, не модели |
| Отказ ядра `stale_context` на случаях F05 | найден dry-run на `dde1f90`, исправлен в 2А `b8ee515`; после rebase F05 проходит 9 из 9 |
| Код вердикта влияния в контракте | не нужен: влияние строит `results.change_result` по diff, а не модель |
| Живой прогон модели | не проверено: ни одного запроса |

Недостающий доступ: слияние стека в `main` (workflow запускается только с
default branch), окружение `autonomous-mvp-live` с секретом
`CLOUDRU_FOUNDATION_API_KEY` (наличие не проверено), право записи
`GITHUB_TOKEN` в учётную ветку. Оценка расхода в отчёте 2Б: около 2,1 тыс. ₽,
предел 37,9 тыс. ₽.

Риск для порядка слияния: manifest 2Б хеширует файлы ядра и конституции.
Слияние пачки 3 (новые инструменты `graph_*` в конституции и исполнителе)
меняет их, поэтому после слияния стека manifest нужно пересобрать
(`program.py`) до живого прогона, иначе runner откажется стартовать.

Следующий шаг: живой прогон за владельцем после слияния стека.

## Пачка 3. Граф кода и наблюдаемых вызовов

Отчёт: [batch-3.md в ветке](https://github.com/rengalaxies/agent/blob/claude/mvp-3-runtime-2a/docs/implementation/autonomous-mvp/batch-3.md),
голова `4454347` (PR [#57](https://github.com/rengalaxies/agent/pull/57)); содержание пачки — на `f8781ae`, дальше merge 2А.

| Что | Состояние |
|---|---|
| Постоянный граф `graph_store.py` (store schema 2), стабильные ID мест вызова без номера строки | реализовано, проверено офлайн |
| Предложения и исправления по процитированным основаниям и digest адресов и требований | реализовано, проверено офлайн; блокер закрыт в `058f565` |
| Фильтрация доступа, свежесть, конфликты кода и наблюдений, ownership, graph query | реализовано, проверено офлайн |
| Обновление по событию и периодическая сверка | реализовано; расписание задаёт сервис |
| Просмотр для человека (`graph_view.py`) | реализован, проверен офлайн; хостинг в сервисе не подключён |
| Миграция store v1 → v2 с резервной копией | реализована, проверена на файле v1 |
| Контракт agent-graph-output 2.1 | только добавления; приходит в `main` с PR 3 |
| Инструменты `graph_*` в конституции и исполнителе | реализовано `9a2ac69`; результаты привязаны к scope политики, ID графа не являются evidence refs |
| Утечка: ownership показывал сервис из отозванного репозитория | исправлено `928b167` |
| Подключение к runtime-источнику клиента | не проверено: нет доступа |

Прогоны пачки 3 (Windows): новые тесты `test_graph_store`, `test_graph_query`,
`test_graph_view`, `test_runtime_observations`, `test_output_contracts` OK;
полный `tests/graph` 226, падения совпадают с базой `dde1f90`. Проверка 2А:
слияние `261e165` с головой 2А `62f551a` без конфликтов, `tests/graph` 228 и
`tests/graph_demo` 38 с теми же средовыми падениями.

Блокер слияния закрыт: у предложения хранится digest адресов и требований
процитированных репозиториев, при расхождении оно STALE с
`proposal_basis_differs` (`058f565`, тест
`test_reassigned_address_or_changed_requirement_makes_knowledge_stale`).
Проверено 2А на `f8781ae`: прежнее воспроизведение даёт CURRENT при той же
политике и STALE после переназначения адреса; тесты 2А
(`test_action_diagnostics`, `test_output_contracts`, `test_results`,
`test_git_sources`, 67 тестов) проходят на ветке 3. По отчёту mvp-3 на
`d060b4f`: `tests/graph` 234 и `tests/graph_demo` 38, набор падений тот же,
что на голове 2А.

Недостающий доступ: чтение одного runtime-источника клиента и описание
идентичности вызывающего.

Следующий шаг: слияние #57 после #56. Linux CI на #57 зелёный (accept, citation-measurement, offline, core).

## Пачка 4. Jira и PR без оператора

Отчёт: [batch-4.md в ветке](https://github.com/rengalaxies/agent/blob/claude/mvp-4-service-2a/docs/implementation/autonomous-mvp/batch-4.md),
голова `339b6d0` (PR [#58](https://github.com/rengalaxies/agent/pull/58), база — ветка 3).

| Что | Состояние |
|---|---|
| `EventEnvelope`, `PublicationIntent`, SQLite-очередь одной установки | реализовано, проверено офлайн |
| Коннекторы GitHub и Jira Cloud, один обновляемый комментарий на ресурс | реализовано, проверено на локальных HTTP-стендах |
| Анализ ядром 2А (`CoreAnalyzer`): PR через `analyze_change` + `change_result`, Jira через `preliminary_result` | реализовано, проверено офлайн на Git-стенде Orders/Reporting |
| Сквозной smoke `python -m agent_service smoke` | проходит (Windows) |
| Модельная часть через исполнитель конституции | подключена за флагом `model_qualified`; модель без квалификации не получает вызовов (тест) |
| Живой GitHub App и Jira | не проверено |
| Linux CI | core на #58: 776 тестов OK, из них 79 `tests/service` (job 121143824127); время и память обработки события не измерены |

Прогоны (Windows): `tests/service` 65 тестов OK; полный набор 615 тестов,
список падений совпадает с базой 2А `dde1f90` построчно.

Недостающий доступ: тестовый репозиторий и GitHub App, тестовый проект Jira
Cloud с учётной записью и токеном, публичный HTTPS-адрес для webhook,
разрешение публиковать комментарии в тестовом контуре.

Следующий шаг: взять graph query и `graph_version` из хранилища пачки 3,
синхронизация Git-зеркал перед анализом, живой smoke в тестовом контуре.

## Пачка 5А. Коробка на Linux-ВМ

Отчёт: [batch-5a.md в ветке](https://github.com/rengalaxies/agent/blob/claude/objective-feistel-a46433/docs/implementation/autonomous-mvp/batch-5a.md),
голова `2fe2f41` (PR [#60](https://github.com/rengalaxies/agent/pull/60), база — ветка 4).

| Что | Состояние |
|---|---|
| Закреплённый релиз: архив из blob-ов коммита, hash-lock колёс, manifest с commit, `core_identity`, конституцией и версиями схем | реализовано, проверено офлайн: две сборки дают один sha256 |
| Установщик `./box` (plan, install, update, status, doctor, backup, restore, rollback, sync-mirrors), три уровня готовности | реализовано, 41 unit-тест и 9 из 9 сценариев на установленном релизе (Windows, супервизор `process`) |
| Git-зеркала по таймеру, откат через восстановление копии перед update | реализовано, проверено офлайн |
| Демо-образ с ядром внутри, без `core.lock.json` и `/core` | реализовано; заменяет промежуточную правку 2А `8ac841d` |
| Linux, systemd-путь целиком | проверено в CI на #60: установленная коробка с systemd, 9 из 9 сценариев (job 121143981931) |
| Реальная ВМ, TLS-прокси для webhook, активные минуты человека | не проверено |

Недостающий доступ: Linux-ВМ для живой установки; реальная ВМ, TLS и минуты человека не проверены.

Демо-поставка без отдельного ядра сделана в ветке 5А: `d644405` убирает
`DEMO_CORE_ROOT` и `--core-root` из `agent-graph-demo.yml`, а
`agent-graph-demo-delivery.yml` больше не собирает `core.tar.gz` из `18e8b71`
(ядро и конституция лежат в `release.tar.gz`); `2fe2f41` обновляет RUNBOOK. В
ветке 2А эти workflow остаются как есть: там `accept.py` ещё требует
`--core-root`. При обратном merge конфликт разрешается в пользу 5А.

## Пачка 5Б. Cloud.ru provisioning

PR [#62](https://github.com/rengalaxies/agent/pull/62), ветка `claude/mvp-5b-cloudru`
`61662a1` от `main` `0f0dc02`. Отчёт: `batch-5b.md` в ветке.

| Что | Состояние |
|---|---|
| Топология одной ВМ (`gen-2-4`, SSD 20 GiB, публичный IPv4, SG с SSH только с `/32` владельца), первый запуск тем же `box install` и `box doctor` | реализовано, проверено офлайн: 41 тест, мутационная проверка |
| Inventory, отсутствие дубликатов, adopt, digest плана, TTL, cleanup только своих ресурсов, lock-test | реализовано, проверено на фикстурах; против облака не запускалось |
| Защищённый apply-workflow и офлайн-проверки на PR | `cloudru-box-validate.yml` зелёный на PR (run 40216022168) |
| Смета 30 дней | 2619,68 ₽, с резервом 3274,60 ₽; ставки тарифа из репозитория, SSD и egress не перепроверены |
| Plan против облака, apply, установка на ВМ, сквозное событие | не проверено: нет одобрения плана и подтверждённых прав создания |

Ресурсы не создавались, cleanup не требуется. Ресурсы прежней P1 в проекте живы и
тарифицируются (около 3,7 тыс. ₽ в месяц по оценке 5Б); коробка их не трогает.

## Пачка 6. Решение о готовности

PR [#63](https://github.com/rengalaxies/agent/pull/63), ветка `claude/mvp-6-readiness`
`30da6d4` от `main` `0f0dc02`. Программа `6-r1`, manifest
`6140e378686837750109e0ac79b1287287a5775d7c9db21d4573d62e62dc50f7`, отчёт `batch-6.md` в ветке.

Held-out (60 изменений) прогнан один раз после заморозки, сервис без модели, код
`0f0dc02`, уровни доказательства L1 и L2 (синтетика, локальные HTTP-стенды):
полезный автономный вывод 47/60 = 0,783 [0,664; 0,869]; ворота technical PASS,
quality FAIL (breaking назван как breaking 52/62, верный путь на PR 85/95, уверенный
ответ в Jira вместо отказа 3/20); потерянных, дублирующих и устаревших публикаций 0 из 120;
FP на PR 0/128, на Jira 10/128. Найдены два дефекта продукта: PR не использует runtime-рёбра
изменённой операции, Jira с одним названием сервиса даёт уверенный ответ. Их исправление
требует ревизии `6-r2`. Конфигурация с моделью, живой baseline, минуты человека, L3 и L4
не оценены.
