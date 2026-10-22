# Закрытая установка HTTP-демо на dm-p1-ui, 22 октября 2026

**Результат: установлено и принято на целевой ВМ.** Backend слушает только
`127.0.0.1:18081`. Доступ проверен Chromium через существующий SSH-доступ dmadmin.
Реальная LLM выключена. Новые облачные ресурсы, DNS, TLS и публичный vhost не создавались.
Последняя read-only проверка: 09:30 UTC / 12:30 МСК; службы приложения, наблюдения
и прежний Nginx active, sandbox-контейнеров нет. Подготовлен показ A без runtime/check.

## Интеграция и происхождение поставки

| Объект | Зафиксированное значение |
|---|---|
| Исходный проверенный head PR36 | `6a2bf834b985dd4471dbfae29a0307077665d1ce` |
| Отдельно закреплённое ядро | `a9385c565d5471698da62987b226dcff4cbdea86` |
| Принятый head PR36 после дополнения | `7dda2bf7c54fb56507179f568195d1c3a9471fd4` |
| **main / исходники установленного приложения** | **`ca6b9cfff0e278fbf3503c308741e4ac96524645`** |
| OCI manifest / установленный Docker image ID | `sha256:dc39a66df73ffedac92539067b5fbb4166c71102cff188ebd9f708a69d3f5820` |
| Docker config digest, проверенный при сборке | `sha256:c5c7e57594fcc5eccc776fa4eacd2122211c326d058f40c142053f0e00624451` |
| SHA256 переданного `image.tar.gz` | `5985cff138e57b33a98753832c9a2242e899135083c7412acceef2f3862e16e3` |

[PR36](https://github.com/rengalaxies/agent/pull/36) слит обычным merge после зелёных
проверок. Его дерево совпадало с принятым head. Работа велась в отдельном checkout;
существующие checkout и их изменения сохранены. AGENTS.md в проверенных каталогах
репозитория/предках отсутствовал; ACCEPTANCE.md и RUNBOOK.md прочитаны.

Целевое ревью охватило Basic auth и server-side viewer scope, Origin, фиксированные
CLI и аргументы, ограничения путей и symlink, очередь/общий flock, версии и immutable
evidence, разделение web/operator, обработку исходников, восстановление и журнал.
Дополнительный независимый review приложения подтвердил отсутствие оставшихся
блокирующих проблем после [PR37](https://github.com/rengalaxies/agent/pull/37):

- Исторический diff refreshed/correction job B/D/E мог ошибочно брать A при пустом
  target_version. Теперь версия извлекается из immutable graph reference и проверяется;
  неизвестная версия отклоняется. На ВМ refreshed B остался B после перехода к E.
- Sandbox получил CPU cap 0.5 на каждый из шести сервисов, включая короткие consumers.
- Добавлены отдельная ручная off-VM поставка и аудит упаковки с exact main SHA.

Регрессии сначала воспроизвели ошибки: history
[39749633615](https://github.com/rengalaxies/agent/actions/runs/39749633615), CPU
[39749868750](https://github.com/rengalaxies/agent/actions/runs/39749868750).
В самом history-тесте затем исправили неверное ожидание имени файла:
B меняет `orders/app.py`, а не `reporting/client.py`; это не потребовало изменения fix.

**CI до merge, отдельно от приёмки ВМ:**

- [HTTP app acceptance 39751605026](https://github.com/rengalaxies/agent/actions/runs/39751605026):
  32 app-теста, Docker/browser acceptance и пять показов, PASS.
- [Core 39751605159](https://github.com/rengalaxies/agent/actions/runs/39751605159): PASS.
- [P1 39751604939](https://github.com/rengalaxies/agent/actions/runs/39751604939): PASS,
  attempt 2. Первый verify упал на гонке удаления Docker `--rm` PostgreSQL после stop;
  обычный rerun failed job прошёл. Обязательные проверки не обходились.

## Сборка, аудит, передача

[Delivery 39752646360](https://github.com/rengalaxies/agent/actions/runs/39752646360)
выполнен на GitHub runner после merge, для exact SHA из таблицы. На ВМ выполнялись
только checksum verification, Docker load и offline-установка готовых hash-locked wheels.
Docker build на ВМ не запускался.

До публикации проверены exact allowlist и SHA256 всех `/app` файлов, отсутствие
лишних app-файлов/ссылок/устройств, non-root user, разрешённые environment names,
имена credential/state-файлов и узкие secret patterns во всех 13 image layers.
Config digest экспортированного архива связан с проверенным image ID.
[image-audit.json](image-audit.json) — PASS. Это статический аудит упаковки,
а не полный vulnerability scan базового Python image.

Artifact `graph-demo-delivery-ca6b9cfff0e278fbf3503c308741e4ac96524645`, ID
`12414521993`, 65,645,257 bytes, retention **1 день**, истекает
`2026-10-23T09:05:29Z`. GitHub artifact digest:
`sha256:4050a23310be605e687b83e69f58905de2cb8e033a15f973c5424584f3faae14`.
Это digest внешнего artifact, он отличается от SHA256 вложенного image archive.
Передача произведена SCP существующим ключом; все [SHA256SUMS](SHA256SUMS) сошлись.

Docker 29/containerd на ВМ показывает OCI manifest ID, тогда как builder audit
показывает config digest. Первая установка остановилась до web start на этом
несовпадении представлений. Перед продолжением проверены descriptor из archive
`index.json`, config hash, все 13 rootfs diff_ids и поля Config: User, Env, Cmd,
Entrypoint, WorkingDir, Labels. [loaded-image.json](loaded-image.json) связывает оба
digest. Замены исходников или образа не было; запуск закреплён по immutable manifest ID.

## Установка и границы полномочий

ВМ до установки: Ubuntu 24.04, 2 vCPU, 3915 MiB MemTotal, swap 0,
Docker 29.1.3 / Compose 2.40.3, root FS около 30 GB / 25 GB свободно,
18081 свободен, Docker containers/images отсутствовали. Ключи и known_hosts не менялись.
dmadmin UID 1000/GID 1002, sudo доступен, членства в docker group нет.

Прежний Nginx active на 80 сохранён. Прежняя `dmrp-ui.service` уже была enabled/failed;
оставлена в том же состоянии. Неизвестные файлы и секреты `/opt/agent-cloud-runtime`
не читались и не удалялись. Резервные копии конфигураций, исходного состояния служб,
портов и пакетов сохранены root-only в:

- `/var/backups/agent-graph-demo/20261022T090733Z` — первая остановленная установка;
- `/var/backups/agent-graph-demo/20261022T090903Z` — завершённая установка и rollback.

Не экспортировать backup archives: они могут содержать неизвестные старые секреты.

| Назначение | Установленный путь / режим |
|---|---|
| App release | `/opt/agent-graph-demo/releases/ca6b9cfff0e278fbf3503c308741e4ac96524645` |
| Активный release | `/opt/agent-graph-demo/current`, symlink на этот release |
| Отдельное ядро | `/opt/agent-graph-demo/cores/a9385c565d5471698da62987b226dcff4cbdea86`, web mount `/core` RO |
| Постоянные данные | `/var/lib/agent-graph-demo/state`, `10001:10001`, 0700 |
| Runtime registry | `/var/lib/agent-graph-demo/runtime`, `root:10001`, 0750; active.json 0640, web RO |
| Web auth/config | `/etc/agent-graph-demo/auth.json`, `web.json`: `root:10001`, 0640 |
| Operator config / release.env | `/etc/agent-graph-demo/`, root:root 0600 |
| Operator password / private test logins | root:root 0600, не входят в image/отчёт/Git |
| Реальные receipts | `/var/lib/agent-graph-demo/receipts`, root-only |

Web SQLite имеет 0644, но родитель state 0700 исключает доступ посторонних пользователей.
Root operator пишет web-журнал через фиксированный helper под UID10001, сохраняя
владение SQLite/WAL; core private store напрямую не читался.

- Web: `10001:10001`, read-only rootfs, cap_drop ALL, NoNewPrivs=1, без Docker socket,
  sudo, cloud credentials и права записи в core/runtime. State writable. Проверено
  из реального web container. Bind **127.0.0.1:18081**, public_mode=false,
  allowed origin только `http://127.0.0.1:18081`.
- Web limits: 1.5 CPU, 768 MiB, 128 PIDs, json-file logs 5m × 2.
- Operator: root-only `/usr/local/sbin/agent-graph-demo-operator`, отдельный offline
  venv, fixed config/CLI, `env -i`; transient systemd scope с CPUQuota=50%,
  MemoryMax=256M, TasksMax=64. Только operator имеет необходимые Docker права.
- Один exact sandbox project на стенд, общий workload.lock и generation CAS.
  Sandbox network internal, ports не опубликованы; restart=no, rootfs RO,
  UID10001, cap_drop ALL/NNP, 0.5 CPU и 64 PIDs на каждый сервис.
  Orders 192 MiB, Status и consumers 128 MiB; logs 5m × 2 на контейнер.
- Один durable worker, максимум один RUNNING и четыре QUEUED, deadline 180 s,
  stdout CLI до 2 MiB. Короткие consumers удаляются, providers удаляются stop/reconcile.
- `agent-graph-demo.service` enabled/active. Drop-in PartOf=docker.service и
  ExecStartPost observation восстанавливает backend после Docker restart.
- Observer timer enabled/active, интервал 60 s, CPUQuota=25%/MemoryMax=128M.
  Он только наблюдает: умерший/неполный sandbox становится UNKNOWN, автоматического
  start/reconcile нет. Реестр старше 120 s также не выдаётся за подтверждённый runtime.

Полные проверенные настройки контейнеров: [target-container-limits.json](target-container-limits.json).
Операционные изменения вне release воспроизводятся в [install.sh](install.sh),
но этот скрипт **не является командой повторного запуска поверх существующей установки**:
он специально отказывается перезаписывать существующий web.json.

## Реальная приёмка целевой ВМ

Все ниже выполнено на **dm-p1-ui**, через локальный SSH tunnel и Chromium UI,
без route mocks и без LLM. Через UI выбирались версии и основания, отдельно root
operator запускал настоящие контейнеры/HTTP consumers и фиксированный oracle.
Пять последовательных полных показов, 20 фактических проверок:

| Версия | Reporting, уникальные ID | Billing | Export | Oracle |
|---|---:|---:|---:|---|
| A | 250 | 250 | — | PASS |
| B | 100, пропущены 101…250 | 250 | — | ожидаемый FAIL |
| D | 250 | 250 | — | PASS |
| E | 250 | 250 | 250 | PASS |

Во всех receipts нет duplicate/unexpected IDs. Health связан со **Status**, а не
Orders при одинаковом `/orders`; реальный health_control отвечает service=Status.
Export обнаружен как новое ребро в E. После каждого показа exact stop оставлял
**0** sandbox-контейнеров. Предложенная B отображалась одновременно с запущенной A,
D с B, E с D. Исторический B, immutable source evidence и diff открывались после E;
история не меняла текущую версию.

Статический анализ остаётся **PARTIAL** (`unknown_http_client` в закреплённом core):
UI пишет «Неполные данные», не выдаёт это за успех. Исходный подготовленный A без
receipt явно показывает «Проверка не выполнялась». Фактический PASS относится к
конкретному запуску/oracle, а не к полноте статического анализа или допуску к релизу.
Receipts имеют origin=operator_runner, graph_status=EXTERNAL_REPORTED,
independently_verified=false: web/core не перепроверяют доверенный root runner.

Доказательства: [target-report.json](target-report.json),
[target-final-verification.json](target-final-verification.json).
В исходном JSON упомянут ранний `target-desktop-E.png`; он был снят до завершения
загрузки evidence и заменён приведённым ниже подтверждённым кадром. Сам старый кадр
в этот пакет не включён. Дополнительная реальная проверка E и остановка Status
задокументированы в [target-final-ui-report.json](target-final-ui-report.json).

- [B: реальные 100/250 и PARTIAL](target-desktop-B.png), [мобильный B](target-mobile-B.png).
- [E: Export, точный исходник, 250/250](target-desktop-E-confirmed.png).
- [Остановлен реальный Status: runtime «Не подтверждено»](target-provider-stop-unknown.png).
  Исторический PASS при этом остаётся историческим, не маскирует UNKNOWN.
- [Подготовленный исходный A без фактической проверки](target-ready-A.png).

### Негативные проверки, очередь и рестарты

[target-extra-report.json](target-extra-report.json):

- Anonymous 401; неверный Origin 403. Scoped viewer читает разрешённую сессию (200),
  чужая сессия и mutation дают 403. Arbitrary path payload — 422.
- Модельный endpoint — 503 model_unavailable, реальных model calls **0**.
- При удерживаемом общем operator lock приняты четыре jobs (202), пятый — 429.
  После освобождения jobs завершились последовательно PARTIAL; peak RUNNING=1,
  интервалы выполнения не пересекаются. Измерение — один atomic readonly SELECT
  web-журнала. Первая версия измерителя опрашивала четыре API отдельно и пересекла
  границу перехода jobs; исправлен измеритель и повторён только узкий queue probe.
  Продукт ради этого не менялся; диагностические jobs/история сохранены.
- Рестарт backend: те же 5 jobs, 4 checks и context hash выбранного показа.
- Реальный restart Docker: backend автоматически вернулся; sandbox с restart=no
  не поднялся, runtime стал UNKNOWN. Явный reconcile, новый run A и stop — PASS;
  история сохранилась. Отдельно остановлен только настоящий Status и подтверждено
  UNKNOWN в полностью загруженном UI, затем explicit reconcile удалил sandbox.
- Вся ВМ **не перезагружалась**. Проверена достаточная для этой установки
  последовательность восстановления службы/контейнеров; reboot не заявляется.

## Измеренные ресурсы

Метрики основной приёмки: 1340 samples за 721 s, медианный интервал 0.535 s,
включая пять показов, queue probe и рестарты. `/proc/meminfo`: used=MemTotal−MemAvailable;
CPU — delta `/proc/stat`, idle+iowait исключены, **100% = обе vCPU ВМ**.
Контейнеры: cgroup v2 memory.current/memory.peak, cpu.stat (100%=одна CPU), memory.events.
Диск — used root filesystem. [monitor.py](monitor.py), [metrics.jsonl](metrics.jsonl),
[analyze_resources.py](analyze_resources.py), [resources.json](resources.json).

| Режим | Пик RAM всей ВМ, MiB | Пик CPU всей ВМ | Used root FS, GiB |
|---|---:|---:|---:|
| Отдельный установившийся покой, 30 s | 625.4 | 55.4% (медиана 0%) | 4.249 |
| Анализ исходников/изменений | 701.7 | 94.4% | 4.248 |
| Реальный runtime/oracle | 782.4 | 91.0% | 4.249 |

Для покоя выполнен отдельный короткий sample без UI/operator actions, observer
оставался включённым; это вся ВМ, поэтому фоновые всплески включены.
[idle-resources.json](idle-resources.json), [measure_idle.py](measure_idle.py).
Основная фаза `idle` включает промежутки между тестами, не считается чистым покоем.

Наблюдённый одновременный memory.current контейнеров при actual — 124.1 MiB;
kernel memory.peak web — 72.4 MiB, крупнейшего наблюдавшегося sandbox container —
32.4 MiB. Наблюдался 101 последовательный container ID, OOM kill **0**.
Свободная память в самом тяжёлом sample — **3133.5 MiB**. Увеличение ВМ не требовалось.

Это **наблюдённые пики**, а не доказательство всех мгновенных максимумов:
39 interruptions при завершении коротких containers/рестартах, очень короткие
consumers могли не попасть в sample; отрицательные CPU intervals при reset counters
исключены. Измеритель добавляет overhead. Kernel peaks относятся к наблюдённым
контейнерам. Поздний повтор E/остановка Status и чистый idle измерены отдельно,
не подмешаны в основной ресурсный ряд.

За основное окно root used вырос с 4.229 до 4.249 GiB (~19.9 MiB).
После установки/приёмки: app/core/venv 34,512,047 bytes, state 2,420,790 bytes,
runtime 253,890 bytes; root FS used 4,562,120,704 bytes, свободно 25,616,977,920 bytes.
State и история автоматически не удаляются. [target-final-survey.txt](target-final-survey.txt).

## Доступ и короткий показ

На Windows PowerShell, отдельное окно оставить открытым:

```powershell
ssh -i "$env:USERPROFILE\.ssh\vkr-cloudru-dm-p1-ui-v2" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -o ExitOnForwardFailure=yes -N -L 127.0.0.1:18081:127.0.0.1:18081 dmadmin@45.151.31.140
```

Адрес: **http://127.0.0.1:18081/**, HTTP Basic user **operator**.
Пароль получить только в своём терминале:

```powershell
ssh -i "$env:USERPROFILE\.ssh\vkr-cloudru-dm-p1-ui-v2" -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes dmadmin@45.151.31.140 "sudo cat /etc/agent-graph-demo/operator-password"
```

Пароль не помещать в URL, скриншоты, history команд с его значением или отчёт.
Во время установки локальный tunnel уже открыт; если порт занят этим tunnel,
использовать его либо закрыть именно его окно/процесс перед повторной командой.
Проверены Basic 401 и authenticated 200, полный Chromium UI через этот путь.

Показ: выбрать сохранённый A `a295a591-7e3d-4088-b325-269de1f9ced4` или «Новый показ»
и «Обследовать исходники». Открыть Health → Status и Reporting → Orders с исходником.
Запустить A оператором, «Получить результаты»; выбрать B и показать proposed B/running A,
затем запустить B и показать Reporting FAIL 100/250. Выбрать D, запустить D, получить 250.
Выбрать E, показать новый Export и evidence, запустить E, получить 250 у всех трёх.
Открыть исторический B и вернуться к текущему E. Отдельно показать PARTIAL/границы.

Operator-команды выполняются в SSH shell dmadmin. UUID брать из текущего показа
в «Техническое состояние и сброс». Ниже удобные функции; это не web API:

```bash
sid=a295a591-7e3d-4088-b325-269de1f9ced4  # заменить, если создан новый показ
generation() {
  sudo python3 -c 'import json; print(json.load(open("/var/lib/agent-graph-demo/runtime/active.json"))["generation"])'
}
run_demo() {
  sudo /usr/local/sbin/agent-graph-demo-operator run --session "$sid" --version "$1" \
    --expected-generation "$(generation)" --check collection \
    --output /var/lib/agent-graph-demo/receipts
}
run_demo A
# После выбора B в UI: run_demo B
# После выбора D в UI: run_demo D
# После выбора E в UI: run_demo E
```

Выбор UI дожидается завершения анализа до operator run. После run нажать
«Получить результаты». Timer может обновить generation между чтением и командой:
conflict безопасен, повторить с новым generation; не отключать CAS.
Новый run предварительно останавливает прежний exact project, не создавая второй.

### Возврат к исходному показу без удаления истории

```bash
sudo /usr/local/sbin/agent-graph-demo-operator stop --session "$sid" \
  --expected-generation "$(generation)"
# Только если runtime UNKNOWN/STARTING вместо RUNNING:
# sudo /usr/local/sbin/agent-graph-demo-operator reconcile --expected-generation "$(generation)"
```

После подтверждённого stop — UI «Техническое состояние и сброс» →
«Сбросить после остановки», затем «Обследовать исходники» для A.
Старые сессии/проверки останутся в истории; активных sandbox-контейнеров не будет.
Либо выбрать уже подготовленный A, не очищая прежний показ.

## Откат установки

В SSH shell:

```bash
sudo bash /var/backups/agent-graph-demo/20261022T090903Z/rollback.sh
```

[rollback.sh](rollback.sh) отключает новый observer timer, останавливает только
точно принадлежащий demo sandbox (или явно reconciles UNKNOWN), затем отключает
новую службу. Сохраняет image, releases, credentials и всю историю. Старые Nginx
и failed dmrp-ui конфигурации не менялись, старую службу откат не запускает.
При ошибке остановки sandbox скрипт прерывается, не выдавая неполный откат за успех.
Этот destructive-to-current-runtime шаг подготовлен, но не выполнен: стенд оставлен доступным.

Возврат того же установленного release после отката:

```bash
sudo systemctl enable --now agent-graph-demo.service agent-graph-demo-observe.timer
```

Ограничения: синтетический corpus/250 ID, статический PARTIAL, доверенный отдельный
root runner, LLM unavailable, только SSH tunnel, без DNS/TLS/public acceptance;
восстановление после полного reboot не проверялось. История требует последующей
явной политики архивирования; auto-purge не включался.

## Содержимое доказательств

`files-sha256.txt` фиксирует байты опубликованных файлов. Кроме перечисленных JSON,
снимков и метрик включены операционные и browser probe scripts для воспроизводимости.
Переносы строк текстовых доказательств приведены к LF, JSON-значения не менялись;
delivery audit и его исходный SHA256 сохранены побайтно.
Они содержат пути безопасного получения credentials в память, но не их значения.
Binary image/wheels, auth/password files, backup archives, private SQLite и полные
environment dumps в этот пакет не входят. Не путать этот отчёт с результатами CI:
целевые доказательства имеют scope TARGET_VM/FINAL_TARGET и реальные session/receipt IDs.
