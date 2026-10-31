# Handoff M3: manager с recovery guard

Применять только после зелёного CI #83, принятия main и проверки опубликованного нового asset.
Точные accepted SHA, release name/URL/checksum/manifest записываются в итоговое evidence этого
каталога и PR. Действующий pin release14e не менялся. Этот документ не разрешает установку на ВМ.

## Управляющий инструмент

Использовать **box из нового проверенного release** для update/rollback/restore и его
установленный wrapper `/usr/local/sbin/agent-service-box` для maintenance. После downgrade
wrapper, timers и guard остаются на новом manager; loaded service при этом может быть release14e.
Status показывает manager / invoked_cli / loaded service / state_identity отдельно.
Прямой старый `release14e/box` или `launch.py` не защищён новым механизмом. Не переключать
unit/wrapper на него и не удалять `.box-state.json`, `.box-recovery.json` или `.restore.json`.
Новый путь preflight рассчитан на Linux; другие ОС не квалифицированы.

Update/install всегда выполнять явно из выбранного архива: эти команды устанавливают именно
вызывающий архив, даже если manager поддерживает сейчас более старый service. Выбор другого
manager может потребовать один restart; следующий unchanged install того же manager идемпотентен.

## Команды после отдельного разрешения установки

В `/path/to/VERIFIED-NEW-RELEASE` должен быть **скачанный и проверенный** новый release,
не архив 14e, которому приписали новый checksum. Эти пути — placeholders, не известный хост.

```bash
sudo python3 /path/to/VERIFIED-NEW-RELEASE/box plan --config /etc/agent-service/box.yaml
sudo python3 /path/to/VERIFIED-NEW-RELEASE/box update --config /etc/agent-service/box.yaml
sudo /usr/local/sbin/agent-service-box status --json
sudo /usr/local/sbin/agent-service-box doctor --json
sudo /usr/local/sbin/agent-service-box backups --json
```

Сначала подтвердить инвентаризацию/доверие восстановленному хосту. Сохранить текущие config,
секреты в доверенном хранилище, внешние ownership/custom-constitution файлы и старый immutable
release14e. Один оператор; внешние доставки могут повториться, но writer должен управляться box.
Новый guarded ExecStart устанавливается до открытия state новым кодом; после прерывания
supervisor не возвращается к старому прямому launcher. Pre-update backup создаётся после stop
и **до** graph/start нового кода. Повтор update проверяет происхождение первоначальной копии,
а unchanged install сохраняет reconciliation gate. Зафиксировать его имя,
target manifest SHA, schemas/counts и оба config hashes из backup.json. Не редактировать backup.

```bash
sudo /usr/local/sbin/agent-service-box rollback --to agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312
sudo /usr/local/sbin/agent-service-box restore MATCHING_BACKUP_NAME
sudo /usr/local/sbin/agent-service-box rollback --abort
```

Это разные решения: rollback к 14e выбирает его matching pre-update backup; restore требует
backup **активного** целевого релиза; --abort возвращает safety copy незавершённого восстановления.
Для смены цели при hold сначала завершить исходный переход либо выполнить проверяемый --abort.
Повторять ту же команду после прерывания. Не продолжать обычным install при незавершённом restore.

При несовместимой schema/semantics без valid matching backup запуск запрещён. Повреждённая копия
не заменяет рабочие БД. При recovery/API/source failure hold остаётся; code-only downgrade на новом
profile6 state не поддерживается. При необходимости сохранить исходное состояние использовать
проверенный safety backup и --abort. Если credentials/API/source всё ещё недоступны, даже abort
не запускает publisher: сначала устранить причину, не обходить guard.

Локальная история после backup остаётся в safety copy, а не сливается автоматически в старую БД.
Нынешние внешние версии возвращаются reconciliation; удалённая внешняя история не гарантируется.
Safety backups защищены от обычной retention. Освобождать место только после осознанной приёмки.

## Контроль на восстановленной ВМ — NOT_RUN здесь

1. Сверить downloaded archive sha256 и manifest code с evidence. Не менять deployment pin
   этим документом; новый plan/pin — отдельное действие M3 после согласования владельца.
2. После update сверить status: manager — новый accepted release; loaded service — выбранный;
   state_identity.writer — его manifest; правильные profile/code_version/constitution/config.
   Проверить `recovery.pending=null`, process/scenario READY и завершённую сверку sources/queue.
3. Наблюдать `journalctl -u agent-service -u agent-service-sync --no-pager -n 100`, install reports
   и `doctor`. `recovery_reconciliation_failed:<code>` означает, что publisher не запущен;
   `matching_backup_missing`, unknown contract, backup/config mismatch требуют проверки копии,
   не ручного запуска старого процесса. Секретные значения в отчёт не копировать.
4. На согласованном контуре проверить restart/reboot, update→rollback→re-upgrade, новый PR head,
   Jira update, точный redelivery, API outage, self-comment и восстановление. Сохранить IDs,
   base/head, task versions, checksums, pending/checkpoint state и фактическое окно устаревания.
5. Service release поставляет service/box. UI собирается отдельным Docker artifact; этот архив
   не доказывает наличие или обновление UI. M2 LIVE и participant/client benefit не закрыты.

| Работа | Исполнитель | Нужна ВМ | Доступы | Критерий завершения |
|---|---|---|---|---|
| Проверка exact published asset / CI | текущий исполнитель | нет | GitHub workflow/release | checksum/manifest + install/recovery published PASS |
| Установка, reboot и восстановление | один оператор M3 | да | доверенный восстановленный хост, отдельное разрешение и config | фактические loaded identities, очередь, rollback/re-upgrade PASS |
| App/Jira/HTTPS и M2 LIVE | владелец + M3 | установленный сервис | scoped App PEM через хранилище, Jira test project/account, HTTPS | настоящий Jira→PR→актуальный комментарий и сбои/дубли/self-loop |
| Проверка пользы на независимом проекте | независимый участник + владелец | не обязательно | согласованный проект/доступ к показу | заполненный participant protocol, без авторской карты ответов |
