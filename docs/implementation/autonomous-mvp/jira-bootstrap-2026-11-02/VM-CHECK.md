# Проверка release234 без доступа исполнителя к ВМ

Вердикт: **блокирует дефект неполного обнаружения существующих Jira-задач**.
В принятом release234 `reconcile_candidates(None)` ищет только `updated >= -10080m`.
Задача без PR, не обновлявшаяся 30 дней и отсутствующая в локальной БД, не ставится
в очередь. Recovery preflight успешно завершается с тем же пропуском, если задачи
нет в восстановленной копии. Уже известные задачи отдельно fetch-ятся и этим
дефектом не затронуты. Проблема воспроизведена; исправление — PR #89. Наличие PR
не исправляет опубликованный release234 и не разрешает менять pin или патчить архив.

Это узкая проверка конфигурации, пути Jira без PR, gateway и recovery. ВМ, install,
реальные service API reads, restart и recovery исполнителем не запускались.
Команды ниже — диагностический сценарий оператора, не зелёный допуск к установке.

## Что проверено без ВМ

- Приложенный `box.candidate.yaml` прошёл BoxConfig и генерацию ServiceConfig
  **кодом скачанного опубликованного архива**. Renderer M2-A из release234 и из
  reference main38 воспроизводят его, кроме согласованных installation_id и
  listen: `agent-pilot-m3-dryrun-20261101`, `127.0.0.1:8091`.
- `publication=dry_run`, модель отсутствует, testing overrides выключены.
  Orders — наблюдаемые PR и источник графа; Reporting — читаемый источник графа.
  Requirements и `https://orders.pilot.invalid` совпадают с M2-A; последний —
  идентификатор анализа, не endpoint для проверки доступности.
- App5515659 / installation176298402 совпадают с registry и owner UI.
  Bot `rengalaxies-agent-pilot[bot]`, numeric349497413 подтверждён API evidence.
  Сам App-auth не подтверждён этим аудитом: прошлый probe отказал до сети.
- Jira gateway/cloudId/KAN и accountId `712020:8948567f-20f5-4c20-8e4c-7f9ed30b5732`
  совпали с проверенным read-probe artifact13092343586/run41329447561.
  SHA256 ZIP `f8844237b38bcf839be34806f67266d9c6f7ff8286677472e376f59ac8bc0a26`.
  Все четыре GET200, active=true, права чтения и комментариев заявлены API.
  Проверялись только разрешённые поля отчёта; Actions secret values не извлекались.
- `bot_account_id` — техническое поле авторства комментария; здесь это аккаунт
  владельца. Отдельный Jira bot не требуется. Модель basic+email+scoped REST API
  token совместима с gateway; MCP agent-interface token не подходит.
- Опубликованный HTTP client конкатенирует base URL и `/rest/api/3/...`, сохраняя
  `/ex/jira/<cloudId>`; synthetic проверка пути и Basic header PASS.
- Новый manager: recovery protocol1, profile `http-requests-6`, graph schema2,
  service schema1, output2.1. Формат candidate совместим. Guard/preflight использует
  код целевого immutable release в отдельном interpreter, не publisher. В исправлении
  #89 новый manager сам выполняет полный Jira REST-v3 discovery; auth/fetch/version
  остаются кодом выбранного target, включая14e/234. Дефект
  выше касается полноты списка, а не отключения guard.
- Недавняя Jira-задача без единого PR и без webhook на неизменённом release234
  проанализирована настоящим core: DONE/USEFUL/preliminary_impact_found.
  Старая30д — `enqueued=0`; отдельный recovery regression также RED.
  На исправлении 6 новых регрессий PASS; 78 targeted service/config/recovery tests
  PASS до добавления последнего preflight-теста. Ruff F401/F811/F841 и diff check PASS.
  Это авторские локальные примеры, не оценка качества KAN-1..3.

Цепочка по коду release234: `worker_loop → service.reconcile → synthetic event →
step/_ingest → apply_snapshot/job → _analyze → CoreAnalyzer.analyze` (ветка без PR)
`→ match_intent → GraphQuery.impact → jira_result → DirectorySink`.
Ограничения: совпадение summary/description с операциями графа; ABSTAINED допустим
при неясном намерении, он не означает отсутствия влияния. До diff всегда
`jira_without_diff`; поломка контракта не доказана. Первый поиск —7д, последующие
с checkpoint — прошедшее время+10мин, максимум20 страниц по100; переполнение
отказывает без продвижения checkpoint. Read-probe/doctor не доказывают анализ.

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
NAME=agent-service-0.1.0-g23412df5e385-linux-x86_64-cp312
ARCHIVE="$PWD/$NAME.tar.gz"
CANDIDATE="$PWD/box.candidate.yaml"
CHECK="$PWD/vm_check.py"
NEW="/opt/agent-service/releases/$NAME"
EVIDENCE="$PWD/vm-evidence"
mkdir -p "$EVIDENCE"
printf '%s  %s\n' af1cf03135628e875d7071b19033f6870254132e02fac3a0e70695d5a898b227 "$ARCHIVE" | sha256sum -c -
tar -xzf "$ARCHIVE"
printf '%s  %s\n' 2e72fe9a66436aca30ff20dafdda216bb4b99d5ea5a76ff19226e23f95e9c5fb "$PWD/$NAME/manifest.json" | sha256sum -c -
python3 "$PWD/$NAME/app/tools/agent_service/box/release.py" verify "$PWD/$NAME"
sudo ss -ltnp 'sport = :8091'
sudo python3 "$PWD/$NAME/box" plan --config "$CANDIDATE" --json > "$EVIDENCE/plan.json"
```

У verify: commit=полный23412df…, status=VERIFIED. У plan problems=[] и
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

Установка release234 для полной приёмки заблокирована найденным дефектом. Если
оператор проводит именно диагностическую проверку согласованного dry_run-контура:

```bash
sudo python3 "$NEW/box" install --config "$CANDIDATE" --json > "$EVIDENCE/install.json"
sudo /usr/local/sbin/agent-service-box status --json > "$EVIDENCE/status.json"
sudo /usr/local/sbin/agent-service-box doctor --json > "$EVIDENCE/doctor.json"
sudo systemctl cat agent-service.service
sudo systemctl show agent-service.service -p MainPID -p ActiveState -p SubState
sudo journalctl -u agent-service -u agent-service-sync --no-pager -n 100
```

Exit install:0 готово;2 процесс есть, сценарий NOT_READY — разбирать причины;1 отказ.
Status: manager/invoked_cli/release/loaded.commit/state_identity.writer соответствуют
release234 и manifest hash; process/scenario READY; recovery.pending=null;
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
profile6/code_version release234, актуальную семантическую version из свежего GET,
`jira_without_diff`, model=null/model_calls0 и актуальный локальный DirectorySink JSON в `dry-run/jira/`: id, marker, generation, doc digest и queue receipt совпадают.
Также требует отсутствия GitHub PR resources. `existing_issues_missing` или
`analysis_missing:KAN-N` — FAIL, не успех чтения API. Старая отсутствующая в БД
задача на release234 ожидаемо не пройдёт; это нельзя исправлять изменением самой
задачи или ручным patch релиза. В текущих KAN-1..3 может не оказаться старой задачи:
их успешная проверка не снимает воспроизведённый30д-дефект.

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
sudo python3 "$NEW/box" rollback --to "$OLD" --json > "$EVIDENCE/rollback.json"
sudo /usr/local/sbin/agent-service-box status --json > "$EVIDENCE/status-old.json"
sudo /usr/local/sbin/agent-service-box doctor --json > "$EVIDENCE/doctor-old.json"
sudo python3 "$NEW/box" update --config "$CANDIDATE" --json > "$EVIDENCE/re-upgrade.json"
sudo /usr/local/sbin/agent-service-box status --json > "$EVIDENCE/status-re-upgraded.json"
sudo /usr/local/sbin/agent-service-box doctor --json > "$EVIDENCE/doctor-re-upgraded.json"
```

После downgrade manager/invoked CLI/wrapper/timers/guard остаются234; loaded service
и state writer становятся14e/profile4. Из-за несовместимых semantics нужен
restored_backup, не code-only switch. После re-upgrade снова234/profile6,
актуальные результаты, прежние resource/comment IDs. Проверку `vm_check.py results`
выполнять на234, не на14e: helper намеренно требует234. Самостоятельный bootstrap старого immutable target не меняется. Однако исправленный
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

Исправление PR относится к будущему отдельно принятому выпуску. Этот runbook и
helper намеренно закреплены на **опубликованном234**, где исходный30д-дефект остаётся.
Они не устанавливают код ветки PR и не заменяют pin. Для будущего выпуска отдельно
пересверяются archive/manifest/SHA и требования helper; не убирать exact checks
ради успешного результата. Предложение к merge/release и CI окончательного head
записываются в PR; ВМ по этим командам здесь не использовалась.

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
