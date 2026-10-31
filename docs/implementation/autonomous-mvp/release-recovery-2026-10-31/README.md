# Обновление и восстановление релизов — 31.10.2026

Работа [#83](https://github.com/rengalaxies/agent/pull/83) от main
`89391a6f7d2526caee15b26b4a71f148c750e051`. MODEL OFF.
Это авторские регрессии и проверка поставки, не независимый benchmark и не проверка пользы.
#83 слит после зелёного exact head `e520c9e401ec2b973f72d702626929518cf878f2`;
accepted main `23412df5e385f11b097d9e67d334d262967ca387`, tree `bd96c449e62ca9fb2679dfab003c125529341ce4`.
[Выпуск agent-service-0.1.0-g23412df5e385](https://github.com/rengalaxies/agent/releases/tag/agent-service-0.1.0-g23412df5e385)
и все три jobs [штатного workflow](https://github.com/rengalaxies/agent/actions/runs/41236132485) PASS.
[Идентичность и доказательство downloaded asset](evidence/PUBLISHED.json).
Target VM / external LIVE / participant — **NOT_RUN**.

## Проблема и воспроизведение

Main 89391a6 сравнивал только service schema 1 / graph schema 2 и выбирал release_only.
На настоящих архивах `release14e → 89391a6/profile6 → release14e` старый writer действительно
запустился: process_ready=true, loaded commit 14e65e8, profile http-requests-4. Это не только
assertion строки mode: сохранена loaded identity реального процесса и выполнена отправка
события локальной Jira. Старый архив не пересобирался и его PROFILE не подменялся.
[Процессное RED](evidence/process-red.json), [unit RED](evidence/unit-red.log).

Прежний опубликованный архив скачан по настоящему public release URL и проверен:

- code `14e65e8affe3b64a9ceb647f537e8af6ff7a1138`;
- archive SHA256 `95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`;
- manifest SHA256 `9fdd6e8aa48e5e09d803840ef262c1c3d57bb01af9c884a690f86a98888533a9`.

Изначальный launcher принадлежит выбранному архиву, а не отдельному системному broker.
Раньше activate также переписывал wrapper и systemd units на старый CLI. Исправление нового
CLI не изменяет старый неизменяемый архив. Прямой вызов старых box/launch остаётся вне защиты.

## Решение и границы

Manifest теперь объявляет recovery protocol 1 и непрозрачный state_semantics:
extractor_profile, graph_schema, output_schema. Порядок строк и номера профилей не используются.
Release-only разрешён при совместимой SQLite schema и равенстве **объявленного** semantic
контракта. Это не универсальное доказательство эквивалентности произвольного кода: автор
семантического изменения обязан изменить контракт. Конституция может изменяться при том же
контракте: существующий basis reconciliation пересчитывает результаты, compatible C→A сохранён.

Неизвестный legacy manifest отказывается. Единственный legacy adapter — точный проверенный
manifest release14e выше. Для его первоначального unlabelled state проверяются сохранённые
profiles; наличие другого профиля не сертифицируется как старый state. При отказе provenance
новый update не перезапускает остановленного старого writer. Старые units/CLI до перехода
на новый manager сами по себе от этого не становятся защищёнными.

`.box-state.json` связывает state с manifest/commit writer и semantic contract. Перед graph
task нового update старый процесс остановлен и сделан pre-update backup. Перезапуск update
проверяет и использует исходную копию. При rollback/restore matching backup должен принадлежать
точному целевому manifest/commit, иметь допустимые schema/semantics и конфигурацию этой установки.
Хеши, SQLite integrity, schema и counts проверяются до замены рабочих файлов.

Базы и state identity меняются через существующий restore journal; добавлен fault между
заменами отдельных файлов. Отдельный `.box-recovery.json` удерживает переход, конфигурацию
и запуск между этапами. Повтор той же команды восстанавливает определённый набор. Ошибка
старта не снимает hold. `rollback --abort` восстанавливает исходный safety backup через тот
же механизм; соответствующий релиз должен оставаться staged и проверенным.

Новый manager сохраняет wrapper, guard и timers после downgrade. Guard проверяет state,
manifest, configuration identity и schema; перед восстановленным publisher выполняет
no-publication preflight **кодом целевого релиза в отдельном interpreter**. Он читает полные
listings и известные ресурсы, проверяет API и локальные Git источники, выполняет reconciliation
и применяет актуальные snapshots до worker. Для release14e есть ограниченный schema-1 adapter
повторного анализа unchanged ресурсов; уже QUEUED/RUNNING новая версия не отзывается.
Долговечный checkpoint предотвращает повторное открытие поколений при обычном restart.

Preflight не вызывает step/run_until_idle/publisher. При его отказе writer не запускается;
systemd может повторять guard, но команда заканчивается ошибкой и останавливает неготовый
процесс. SIGTERM завершает и дожидается preflight; Linux parent-death signal не оставляет
SQLite writer при SIGKILL guard. Другие ОС для этого recovery path не квалифицированы:
guarded preflight отказывает вне Linux. Новый сервис или брокер не добавлялся.

Status различает configured manager, invoked CLI, loaded service и state identity. Во время
recovery или несовпадения writer он не вызывает старый readiness-task, который открывает SQLite.
Такое состояние не объявляется READY. Protocol/backup/source/API ошибки видны по reason codes.

## Доказательства и матрица

| Сценарий | Unit / регрессия | LOCAL processes, source672 | CI |
|---|---|---|---|
| Update14e→новый профиль, backup до нового writer | PASS | PASS + kill после graph/start нового guard/resume | PASS exact head и published234 |
| Откат нового профиля | PASS, неизвестный writer не запускается | PASS matching backup → profile4 | PASS exact head и published234 |
| Совместимый profile/schema, другая constitution | PASS release_only, owner config и counts | NOT_RUN отдельным процессом | PASS existing box C→A |
| Неизвестный legacy/protocol | PASS REFUSED | NOT_RUN отдельным архивом; unit | PASS unit job |
| Missing / corrupt matching backup | PASS до stop/activate | PASS текущий PID сохранён | PASS exact head и published234 |
| Staged / aside / первый DB swap / swapped / before-start | PASS обе БД | PASS пять прерываний и повторы | PASS exact head и published234 |
| Broken start / auto-rollback | PASS hold/abort | NOT_RUN отдельным D archive | PASS existing box D→A |
| Новый head, изменённая Jira, exact redelivery | PASS existing queue/core | PASS прежние IDs и новые версии | PASS exact head и published234 |
| API503 / источник недоступен | PASS status без SQLite task | PASS no writes + NOT_READY | PASS exact head и published234 |
| Restart без новых поколений / re-upgrade | PASS gate/checkpoint | PASS | PASS exact head и published234 |
| Abort safety copy, в том числе повтор отказа | PASS real SQLite/config unit | NOT_RUN с HTTP publishers | PASS unit job |
| SIGTERM/SIGKILL guard не оставляет writer | PASS реальные дочерние SQLite writers | PASS process regression в unit | PASS unit job |

Финальный LOCAL [source672: 6/6 PASS](evidence/guarded-final-acceptance.json) включает
прерывание после открытия graph новым кодом и фактический start supervisor до resume.
Service payload source672, head e520 и accepted main234 совпадает; manifest release IDs различаются.
[CI exact head](evidence/FINAL-CI.json): все пять workflows PASS, 917 core + 152 runner,
71 box и 11 existing installed/systemd scenarios. [Actual-archive CI JSON](evidence/ci-final-acceptance.json).
[Published fresh install/e2e](evidence/published-install-acceptance.json) — 2/2 PASS;
[published14e↔234 recovery](evidence/published-recovery-acceptance.json) — 6/6 PASS.
Последние два ряда — реальные Linux процессы на CI, не целевая ВМ.

Первый завершённый LOCAL цикл использовал candidate
`f100f2c28756c58d370edd2ee138780f6a6b338c`: пять сценариев PASS, два comment IDs сохранены.
[JSON](evidence/local-acceptance.json). Он предшествовал дополнительному review hardening.
Расширенный LOCAL цикл использует `f59e7beaf5356bc9be0f95199015b1d5e6171458`;
все шесть сценариев PASS, включая source failure, exact redelivery и restart без новых поколений.
[Финальный LOCAL JSON](evidence/local-final-acceptance.json),
[полные base/head, Jira revision, comment/event IDs](evidence/local-final-versions.json).
Окончательный CI проверил последний head PR, в том числе поздние guards status/provenance,
повтор abort и owner-config restoration. Эти поздние изменения не приписываются старому LOCAL архиву.
Product freeze после review: `672055e3baece0de67163d3b3c61f3fa7a4dd1da`; последующие файлы отчёта
не меняют service payload. Exact окончательные head/accepted SHA указаны выше, в PR и release evidence.

71 box unit/regression tests без skips; [GREEN](evidence/unit-final-green.log).
917 core/service tests LOCAL PASS; [лог](evidence/full-core-local.log).
152 runner tests LOCAL PASS; [лог](evidence/runner-local.log).
Scripted/model-failure cases в runner-логе — тестовые ответы, не реальные LLM-вызовы.
Ruff F401/F811/F841, Python compile, diff и проверка неизменности pin — PASS.

Отдельный review воспроизвёл две ошибки первого варианта исправления:
reopen отзывал уже queued новую версию ([RED](evidence/adapter-red.log) →
[GREEN](evidence/adapter-green.log)); остановленный guard оставлял дочерний SQLite writer
([RED](evidence/guard-child-red.log) → [GREEN](evidence/guard-child-green.log)). Обе исправлены.
Также RED→GREEN: [повтор --abort и target owner config](evidence/retry-config-red.log)
→ [GREEN](evidence/retry-config-green.log). Release-only сохраняет строки состояния, но выбирает
сохранённый owner box.yaml целевого релиза; повтор незавершённого abort не меняет цель.
Последние проверки interrupted update: [чужой backup RED](evidence/resume-red.log) →
[matching reuse GREEN](evidence/resume-green.log); [reinstall сбрасывал gate RED](evidence/reinstall-gate-red.log)
→ [GREEN](evidence/reinstall-gate-green.log). Наконец, [реальный candidate61 RED](evidence/update-guard-red.json)
после kill графа запускал старый supervisor entry. Теперь новый guard записывается **до** backup/нового
SQLite writer; он не запускает неподходящий state даже при запуске supervisor после прерывания.
Exact recovery CI выполняет kill после graph, start supervisor и resume с исходным backup.
Обычный backup также не приписывает state другого writer старому active release.
Это собственный отдельный проход review, не независимый человеческий approval.

Первые CI отказы не скрыты: 41233052865 — driver строил file://var для root `/`;
41233235097 — timer восстановил переименованный источник во время fault injection;
41233235110 — выбор другого manager требует одного restart и queue status не имеет поля resources.
41233873431 прошёл сам rollback/source/API, затем driver потребовал pydantic от системного
Python для restart; systemd ветка исправлена на stdlib-вызов systemctl.
Драйвер теперь использует корректный URI, удерживает существующий sync-lock при outage и
проверяет идемпотентность последовательных install с одним выбранным manager. Проверки startup,
no-publication, comment IDs и отказов не ослаблены. Финальная приёмка — только зелёный exact head.

## Что не восстанавливается автоматически

Restore откатывает **локальную** очередь/историю к backup. Новые строки после backup остаются
в сохранённом pre-rollback safety backup; автоматического слияния нет. Эти safety copies не
удаляет обычная daily retention; оператор контролирует место и осознанное удаление после приёмки.
Открытые внешние ресурсы, текущие версии Jira/PR и пропущенные доставки восстанавливаются сверкой;
внешние комментарии находятся/обновляются по прежним markers/IDs. Историю удалённых ресурсов,
полную последовательность прошлых webhook payloads и человеческие действия API не возвращает.

Backup сохраняет обе SQLite, state identity, box.yaml, service.json и policy.json. Credentials,
Git mirrors, сами release archives и внешние файлы ownership/custom constitution/model qualification
в него не входят. Их пути есть в config; оператор сохраняет необходимые внешние файлы отдельно.
Manual online backup даёт согласованную копию каждой БД, не распределённую транзакцию всех систем.

Наша БД и внешние API не атомарны. Preflight/read-before-send не устраняет гонку последнего
изменения ресурса после проверки. После restore старое внешнее тело может оставаться до stale
notice/нового результата; при outage окно не ограничено SLA. Существующие pre/post-send проверки
и reconciliation исправляют обнаруженные изменения, но мгновенного восстановления и полноты
недоступной внешней истории здесь не обещается.

## Выпуск и следующий шаг

Выполнен существующий agent-service-release.yml с expected_main_sha=23412df5e385f11b097d9e67d334d262967ca387.
Две byte-identical CI сборки, уникальный ранее несуществовавший tag, download/sha256/manifest,
install-published и recovery-published — PASS. Никакой tag/asset не заменялся.
Архив скачан отдельно исполнителем, прошёл release.py verify и побайтно совпал с **двумя**
независимыми LOCAL сборками accepted main. Скачанный отдельный manifest совпал с архивом.

- Archive SHA256: `af1cf03135628e875d7071b19033f6870254132e02fac3a0e70695d5a898b227`.
- Manifest SHA256: `2e72fe9a66436aca30ff20dafdda216bb4b99d5ea5a76ff19226e23f95e9c5fb`.
- [Downloaded verify](evidence/published-verify.json), [manifest](evidence/published.manifest.json),
  [independent build](evidence/accepted-build.json), [все evidence/artifact IDs](evidence/PUBLISHED.json).

Действия исполнителя через инструменты: собственные worktrees/PR, отдельный self-review,
обычный merge после CI, один workflow dispatch, скачивание/проверка assets и CI artifacts,
завершение локальных стендов. Независимый человек/participant не участвовал; человеческие
минуты NOT_MEASURED. Прямой gh artifact download получил transport403; ZIP загружены через
GitHub Connector и сверены с GitHub artifact digests. Это не ограничение published asset:
его постоянный public release URL скачан и проверен отдельно.

Deployment pin 14e и #71 не менялись. Фактически установленная на ВМ версия **не обследована**.
Service archive не содержит Docker UI image; UI здесь не собирался и не публиковался.

[Поддерживаемые команды и действия M3](HANDOFF-M3.md). Установка на восстановленной ВМ,
reboot, настоящие App/Jira/HTTPS, внешняя M2-приёмка и participant-сессия остаются отдельно.
Человеческое время не измерялось и не оценивалось.
