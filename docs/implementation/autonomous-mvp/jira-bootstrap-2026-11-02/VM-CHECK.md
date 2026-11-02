# Принятый immutable release для оператора

Code SHA: `5fb6484fecff116d005137f0acaaa81d2d25854c`.
Archive SHA256: `d2ef14de92736095f21e06d938b9311647f9e935fd692e982302a72c9e09706d`.
Manifest SHA256: `49477dc1d6576008133c75b5cef761f5c73d70bf3f05971da6b0c3c6ca5c7bd7`.
[Release / published acceptance](https://github.com/rengalaxies/agent/actions/runs/41440998605).
[Архив](https://github.com/rengalaxies/agent/releases/download/agent-service-0.1.0-g5fb6484fecff/agent-service-0.1.0-g5fb6484fecff-linux-x86_64-cp312.tar.gz).
[Published umask077 qualification](https://github.com/rengalaxies/agent/actions/runs/41441279257).
Pin не менялся; target VM NOT_RUN.

# Проверка release5fb на ВМ

#89 слит из проверенного head; исходный дефект7-дневного bootstrap устранён.
Опубликованный архив скачан и проверен: code и manifest соответствуют SHA выше.
Точный итог published install/recovery указан в связанном release workflow.
Новая конфигурация остаётся dry_run/MODEL OFF; target VM, реальные credentials,
качество анализа KAN и операторские действия NOT_RUN. Исходная проверка схемы,
renderer и identities описана в истории #89; она не заменяет новые VM probes.

Путь анализа: startup worker → reconciliation → events/jobs → CoreAnalyzer
без PR → intent/graph impact → DirectorySink. Неполная пагинация и ошибка API
не считаются завершением. Новый manager выполняет полный discovery также для
старых immutable targets; target сохраняет auth/fetch/version semantics.
Предел20 страниц сохранён и явно отказывает при необходимости21-й.

## Подготовка оператором: доступ, секреты, неизменный release

Использовать доверенный восстановленный dm-p1-ui; обновить inventory и пересверить
SSH host fingerprint/доступ, свободный8091, ресурсы и исходное демо. Старый SSH
ключ не добавлен, прошлый publickey отказал; VNC не заменяет файловую доставку.
Базовый backup `/var/backups/m3-preinstall/20261101T174054Z` остаётся только на ВМ;
правильный `static-complete.tar`, не исторический неполный `static.tar`.

Локальный helper из приложенного README:

```bash
python3 '/Users/user/Documents/ChatGPT/ВКР/.private/m3-ssh-20261101/enter-jira-credentials.py'
```

Путь известен из handoff; исходный helper в этой среде не предоставлен и не
проверялся. Он должен принимать JIRA_EMAIL владельца и Jira scoped REST token через
getpass и создавать jira.env0600/O_EXCL. Не вставлять значения в shell arguments,
history, чат, PR или артефакты; Actions secrets обратно не получать. PEM доставить
из существующего доверенного локального источника отдельно. Оператор переносит
PEM и jira.env по подтверждённому защищённому каналу и собирает root0600
`/etc/agent-service/secrets.env`, сохраняя прежние значения при их наличии:
`GITHUB_APP_PRIVATE_KEY_PATH`, `GITHUB_WEBHOOK_SECRET`, `JIRA_EMAIL`,
`JIRA_API_TOKEN`, `JIRA_WEBHOOK_SECRET`. Webhook secrets обязательны даже при dry_run;
сгенерировать на хосте, не регистрировать webhooks у провайдеров. Статус-токен
сгенерирует box. PEM box.configure переведёт в root:agent-service0640; каталог
должен позволять service user чтение. Не использовать `source secrets.env`.

Следующие команды рассчитаны на bash/root-capable sudo, Ubuntu24.04/python3.12.
Войти в защищённый операторский каталог, где уже лежат скачанный архив,
приложенный candidate и два файла этого runbook (`VM-CHECK.md`, `vm_check.py`).
Helper находится вне release и не меняет установленный код.

```bash
umask 077
NAME=agent-service-0.1.0-g5fb6484fecff-linux-x86_64-cp312
ARCHIVE="$PWD/$NAME.tar.gz"
CANDIDATE="$PWD/box.candidate.yaml"
CHECK="$PWD/vm_check.py"
NEW="/opt/agent-service/releases/$NAME"
EVIDENCE="$PWD/vm-evidence"
mkdir -p "$EVIDENCE"
printf '%s  %s\n' d2ef14de92736095f21e06d938b9311647f9e935fd692e982302a72c9e09706d "$ARCHIVE" | sha256sum -c -
tar -xzf "$ARCHIVE"
printf '%s  %s\n' 49477dc1d6576008133c75b5cef761f5c73d70bf3f05971da6b0c3c6ca5c7bd7 "$PWD/$NAME/manifest.json" | sha256sum -c -
python3 "$PWD/$NAME/app/tools/agent_service/box/release.py" verify "$PWD/$NAME"
sudo ss -ltnp 'sport = :8091'
sudo python3 "$PWD/$NAME/box" plan --config "$CANDIDATE" --json > "$EVIDENCE/plan.json"
```

У verify: commit=полный5fb648…, status=VERIFIED. У plan problems=[] и
exit0. Bootstrap plan может **stage-ить** проверенный release/venv: это не service
install и не запуск worker. Повторно проверить staged tree:

```bash
sudo python3 "$NEW/app/tools/agent_service/box/release.py" verify "$NEW"
sudo "$NEW/venv/bin/python" -I -B "$CHECK" api --release "$NEW" --box-config "$CANDIDATE" > "$EVIDENCE/api-before.json"
```

Helper возвращает exit0/ok=true только при active owner identity, KAN, правах,
точной App/installation, ровно двух selected private repo, numeric bot,
читаемых main и **нуле открытых PR** в обоих repo. Он отдельно листает весь KAN
без updated-window, выводит только ID/key/updated и хеши существующих комментариев;
текст задач/комментариев и credentials не выводит. Его App token — отдельный,
в finally он отзывается. Это API READ PASS, не анализ. Если credential/API/scope
отказали — остановиться, не расширять права автоматически.

## Install → identities/doctor → dry_run

Для нового release5fb первоначальный дефект исправлен. После published acceptance оператор выполняет согласованную проверку dry_run-контура:

```bash
sudo /bin/sh -c 'umask 077; exec /usr/bin/python3 "$@"' sh "$NEW/box" install --config "$CANDIDATE" --json > "$EVIDENCE/install.json"
sudo /usr/local/sbin/agent-service-box status --json > "$EVIDENCE/status.json"
sudo /usr/local/sbin/agent-service-box doctor --json > "$EVIDENCE/doctor.json"
sudo systemctl cat agent-service.service
sudo systemctl show agent-service.service -p MainPID -p ActiveState -p SubState
sudo journalctl -u agent-service -u agent-service-sync --no-pager -n 100
```

Exit install:0 готово;2 процесс есть, сценарий NOT_READY — разбирать причины;1 отказ.
Status: manager/invoked_cli/release/loaded.commit/state_identity.writer соответствуют
release5fb и manifest hash; process/scenario READY; recovery.pending=null;
profile6/core_digest/constitution совпадают с manifest; sources CURRENT, queue без
ошибок. ExecStart должен вести в **новый guard**, PID совпадать с loaded.json.
Не засчитывать один /healthz. Doctor проверяет search/read, не /myself или качество.

Install **уже запускает единственный worker**. При старте worker сам делает
reconcile и обрабатывает очередь; webhooks/PR для этого не нужны. Не запускать
`python -m agent_service reconcile` параллельно: эта команда также выполняет
run_until_idle и стала бы вторым worker. Не вставлять synthetic events/не менять
Jira updated/checkpoints, чтобы скрыть ограничение7д.

После опустошения очереди (status), в пределах согласованного окна15мин. Если job ещё QUEUED/RUNNING/ANALYZED, дождаться DONE и повторить read-only results, не запускать второй worker:

```bash
sudo "$NEW/venv/bin/python" -I -B "$CHECK" results --release "$NEW" > "$EVIDENCE/results-before-restart.json"
sudo "$NEW/venv/bin/python" -I -B "$CHECK" api --release "$NEW" > "$EVIDENCE/api-after.json"
python3 - "$EVIDENCE/api-before.json" "$EVIDENCE/api-after.json" <<'PY'
import json,sys
before,after=[json.load(open(p)) for p in sys.argv[1:]]
assert before['ok'] and after['ok']
assert before['jira_comment_sha256']==after['jira_comment_sha256'], 'Jira comments changed'
print('NO_EXTERNAL_JIRA_COMMENT_CHANGE')
PY
```

Results helper открывает SQLite только `mode=ro`, не создаёт ServiceStore/worker.
Требует KAN-1..3: текущая generation имеет job DONE, результат Jira проходит штатную contract/request validation (job_id/attempt, event, installation/environment),
profile6/code_version release5fb, актуальную семантическую version из свежего GET,
`jira_without_diff`, model=null/model_calls0 и актуальный локальный DirectorySink JSON в `dry-run/jira/`: id, marker, generation, doc digest и queue receipt совпадают.
Также требует отсутствия GitHub PR resources. `existing_issues_missing` или
`analysis_missing:KAN-N` — FAIL, не успех чтения API. Старая отсутствующая в БД задача на новом release5fb должна быть обнаружена полным обходом; пропуск — FAIL, не повод менять саму задачу. В текущих KAN-1..3 может не оказаться старой задачи:
для проверки старых задач дополнительно использовать локальную регрессию из #89, не изменять Jira timestamps.

Качество проверить **локально на ВМ** по текстам трёх задач и result/DirectorySink,
не выгружая БД: явный orders GET /orders должен давать обоснованный путь к Reporting
при наличии соответствующего кода; неясная задача — честный intent_unclear/ABSTAINED;
named contract change без операции — candidates/PARTIAL. Проверить evidence и
неизвестные, requirement_unknown при отсутствии требования. Не требовать USEFUL
от всех трёх и не объявлять любой DONE качественным. Не называть preliminary
hypothesis доказанной поломкой. В этом задании реальные тексты задач не читались.

## Restart → backup/restore → rollback/re-upgrade

При неизменных API/branches/основе анализа обычный restart не должен открывать
новые поколения; сравниваются IDs/version/generation/статусы в helper output:

```bash
sudo systemctl restart agent-service.service
sudo /usr/local/sbin/agent-service-box status --json > "$EVIDENCE/status-after-restart.json"
sudo "$NEW/venv/bin/python" -I -B "$CHECK" results --release "$NEW" > "$EVIDENCE/results-after-restart.json"
cmp "$EVIDENCE/results-before-restart.json" "$EVIDENCE/results-after-restart.json"
sudo /usr/local/sbin/agent-service-box backup --label dryrun-before-restore --json > "$EVIDENCE/backup.json"
sudo /usr/local/sbin/agent-service-box backups --json > "$EVIDENCE/backups.json"
RESTORE_NAME=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["name"])' "$EVIDENCE/backup.json")
sudo /usr/local/sbin/agent-service-box restore "$RESTORE_NAME" --json > "$EVIDENCE/restore.json"
sudo /usr/local/sbin/agent-service-box status --json > "$EVIDENCE/status-after-restore.json"
sudo /usr/local/sbin/agent-service-box doctor --json > "$EVIDENCE/doctor-after-restore.json"
```

Дождаться READY и завершения очереди, затем:

```bash
sudo "$NEW/venv/bin/python" -I -B "$CHECK" results --release "$NEW" > "$EVIDENCE/results-after-restore.json"
sudo "$NEW/venv/bin/python" -I -B "$CHECK" api --release "$NEW" > "$EVIDENCE/api-after-restore.json"
python3 - "$EVIDENCE/api-before.json" "$EVIDENCE/api-after-restore.json" <<'PYCODE'
import json,sys
before,after=[json.load(open(p)) for p in sys.argv[1:]]
assert before['jira_comment_sha256']==after['jira_comment_sha256']
print('NO_EXTERNAL_JIRA_COMMENT_CHANGE')
PYCODE
```

External
comment hashes прежние, локальные comment IDs прежние, результаты актуальные.
После restore новое поколение для повторного анализа допустимо; после обычного
restart — нет. Проверить matching writer/manifest/config/schema/counts в backup,
safety backup и guard checkpoint. Не удалять backup/config/state markers.

**На fresh install предыдущего установленного service нет; rollback — NOT_APPLICABLE.** Честный downgrade
тогда NOT_APPLICABLE/NOT_RUN: нужны staged/verified старый release, его bindings
и valid matching pre-update backup от реальной предыдущей установки. Backup
старого демо не является backup release14e; не устанавливать14e ради создания
доказательства, не менять pin. При наличии этих prerequisites точные команды:

```bash
OLD=agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312
sudo /bin/sh -c 'umask 077; exec /usr/bin/python3 "$@"' sh "$NEW/box" rollback --to "$OLD" --json > "$EVIDENCE/rollback.json"
sudo /usr/local/sbin/agent-service-box status --json > "$EVIDENCE/status-old.json"
sudo /usr/local/sbin/agent-service-box doctor --json > "$EVIDENCE/doctor-old.json"
sudo /bin/sh -c 'umask 077; exec /usr/bin/python3 "$@"' sh "$NEW/box" update --config "$CANDIDATE" --json > "$EVIDENCE/re-upgrade.json"
sudo /usr/local/sbin/agent-service-box status --json > "$EVIDENCE/status-re-upgraded.json"
sudo /usr/local/sbin/agent-service-box doctor --json > "$EVIDENCE/doctor-re-upgraded.json"
```

После downgrade manager/invoked CLI/wrapper/timers/guard остаются 5fb; loaded service
и state writer становятся14e/profile4. Из-за несовместимых semantics нужен
restored_backup, не code-only switch. После re-upgrade снова 5fb/profile6,
актуальные результаты, прежние resource/comment IDs. Проверку `vm_check.py results`
выполнять на 5fb, не на14e: helper намеренно требует 5fb. Самостоятельный bootstrap старого immutable target не меняется. Однако исправленный
manager выполняет полный Jira discovery при recovery и для старого target; архив
не патчится, auth/fetch/semantic version принадлежат его коду.

Если matching backup отсутствует/повреждён — отказ до stop/start, не обходить.
При hold повторить **ту же** restore/rollback-команду. Возврат safety copy только
новым manager и только когда она существует:

```bash
sudo /usr/local/sbin/agent-service-box rollback --abort --json
```

API/source отказ может удержать publisher и при abort. Исправить доступ, не
удалять `.box-state.json`, `.box-recovery.json`, `.restore.json` и не запускать
старые box/launch напрямую. Во время hold не продолжать обычным install.
Все отчёты/БД/private backups остаются на ВМ. После каждого шага сравнить исходное
демо: loopback80=200,8080=200,18081=401 как baseline;401 не доказывает login UI.
Reboot только оператором после проверки автозапуска и гарантированного повторного
входа; он этим исполнителем не выполнялся.


## Дополнение #89: полный обход и проверка отказов

#89 слит, новый immutable release5fb выпущен из merge SHA. Команды и helper
закреплены на новом archive/manifest; pin не менялся. Published acceptance
зафиксирована в итогах release workflow, ВМ остаётся NOT_RUN.

- Bootstrap без checkpoint читает все страницы настроенных проектов до явного
  `isLast=true`. Ошибка HTTP503 на следующей странице, неверный JSON/issue shape,
  пропавший/повторный token, `isLast=false` без token и противоречивый terminal
  ответ не продвигают Jira checkpoint. Накопленный частичный список не применяется.
- Сохраняется существующий предел20 страниц по100 запросу: двадцатая терминальная
  страница допустима; необходимость21-й — явный отказ `reconcile_listing_incomplete`.
  Это предел квалифицированного объёма, не бесконечный обход. Для проекта больше
  этого объёма bootstrap/recovery остаются заблокированы; не считать их завершёнными.
- Повтор после API repair/прерывания начинает полный обход с первой страницы.
  При остановке после записи части synthetic events или snapshots уже записанные
  версии coalesce-ятся; новые jobs/comment IDs для них не размножаются.
- Recovery выполняет весь listing/fetch до применения snapshots. Ошибка также во
  **второй** provider reconciliation или при получении актуальных Git refs/графа
  оставляет preflight незавершённым. `box_recovery` не записывается; guard не
  переходит к publisher. Сохранённый ранее свежий граф не маскирует новый API отказ.
- Повтор preflight после reopen, но до completion checkpoint, не открывает ещё
  одно поколение для уже QUEUED/RUNNING работы. При том же завершённом token
  обычный повтор/restart также не порождает новые поколения. Комментарии не
  публикуются из preflight; фактический worker обрабатывает очередь после guard.

Проверки в `test_jira_listing_recovery.py`: настоящие HTTP pages (5 старых задач,
3 страницы), restart/idempotence, HTTP503 в pagination/fetch/второй сверке/graph
read, границы20/21, malformed responses, durable interruption до checkpoint и
**4 subprocess SIGKILL** — bootstrap/preflight × pagination/первая durable запись.
Проверки helper используют настоящие build/ServiceStore/DirectorySink producer
и отклоняют stale/tampered sink, неполный контракт и результат другого request.
Это локальные регрессии, не доступ к реальной Jira или целевой ВМ.

Fresh install запускает worker уже внутри install. Во время работающего сервиса
параллельный `python -m agent_service reconcile` **запрещён**: он запускает второй
цикл обработки. Для наблюдения использовать только status/doctor/read-only helper.
Rollback без предыдущего установленного сервиса, его bindings и matching backup
— **NOT_APPLICABLE**, не попытка запустить старый manager и не замена restore.


Проверена также граница **старого target**: manager-owned Jira discovery не
вызывает старый7д-метод для полного списка. Четыре сценария (успех+повтор,
HTTP503 на второй странице+retry, malformed partial page+retry, отказ API во второй сверке+retry) выполнены
в свежих interpreter с реальными модулями/SQLite queue/коннекторами скачанных
immutable14e и234. Module paths проверены под соответствующим archive/app;
архивы и PROFILE не менялись, worker/publisher не запускались. Новый recovery CI
повторяет эту матрицу с published14e и exact candidate до прежнего systemd
lifecycle acceptance. Ограничение20 страниц и точные критерии завершения
применяются ко всем этим manager recovery targets.


## Дополнение #91: App Git и restrictive umask

Новый immutable release5fb содержит исправления App Git password (raw installation
token без HTTP Bearer prefix) и staging/config parent traversal. Предыдущий
release292 остаётся неизменённым. Проверка App использует реальный HTTPS Git
clone/fetch с synthetic token exchange; LIVE App credentials этим не доказаны.

После install под umask077 проверить от фактического service user:

```bash
sudo -u agent-service test -x /opt/agent-service
sudo -u agent-service test -x /opt/agent-service/releases
sudo -u agent-service test -x /etc/agent-service
sudo /bin/sh -c 'test "$(stat -c %a /etc/agent-service/secrets.env)" = 600'
```

Published-asset acceptance и отдельный umask077 qualification фиксируются в итогах
выпуска. Root-private acceptance reports читаются под root; их права не ослаблять.
На target VM ничего не выполнялось, deployment pin не меняется этим документом.
