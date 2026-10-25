# agent-service: коробка для Linux-ВМ

Один релиз, один установщик (`box`), один файл конфигурации. Код установщика:
`tools/agent_service/box/`. Отчёт пачки 5А с проверками:
`docs/implementation/autonomous-mvp/batch-5a.md`.

## Инструкция владельца

Что нужно один раз:

1. ВМ с Ubuntu 24.04: git и python3.12 уже есть в образе, Docker не нужен. Размер ВМ
   пока ориентир (2 vCPU, 2 ГБ RAM, 10 ГБ диска), замеров на ВМ ещё нет.
2. GitHub App с правами Contents: read, Pull requests: read, Issues: write (комментарии),
   установленная на нужные репозитории; её `app_id`, `installation_id` и ключ `.pem`.
   Либо токен с теми же правами.
3. Для Jira: учётная запись бота, её API token и accountId.
4. Соответствие сервис → команда (`ownership.json`), если нужно называть команды.

Установка, три команды:

```bash
sha256sum -c agent-service-0.1.0-g<sha>-linux-x86_64-cp312.tar.gz.sha256
```

```bash
tar -xzf agent-service-0.1.0-g<sha>-linux-x86_64-cp312.tar.gz
```

```bash
sudo ./agent-service-0.1.0-g<sha>-linux-x86_64-cp312/box install --config box.yaml
```

Перед установкой заполните `box.yaml` по образцу `box.example.yaml` и создайте
`/etc/agent-service/secrets.env` (владелец root, права 600):

```
GITHUB_APP_PRIVATE_KEY_PATH=/etc/agent-service/github-app.pem
GITHUB_WEBHOOK_SECRET=...
JIRA_EMAIL=bot@acme.example
JIRA_API_TOKEN=...
JIRA_WEBHOOK_SECRET=...
```

Если чего-то не хватает, `box install` останавливается до любых изменений сервиса и
его состояния и называет, что именно добавить (проверенный релиз при этом уже
разложен в `/opt/agent-service/releases`). Команда `box plan` показывает план без изменений.

Как понять, что готово: установка заканчивается строкой
`Живость: LIVE; процесс: READY; сценарий: READY` и кодом выхода 0.
Код 2 значит, что сервис запущен, но полезный сценарий не готов; под строкой
перечислены причины и что сделать. Потом то же покажет `sudo agent-service-box status`.

Webhook: GitHub App и Jira шлют события на `https://<адрес>/webhooks/github` и
`/webhooks/jira`. Сервис слушает `127.0.0.1:8090`, наружу его публикует TLS-прокси
компании. Без webhook сервис тоже работает: каждые `freshness.reconcile_seconds`
(15 минут) он сам сверяется с Jira и GitHub, только медленнее.

## Runbook

| Задача | Команда |
|---|---|
| состояние, загруженная версия ядра | `sudo agent-service-box status` (`--json` для машин) |
| диагностика с проверкой учётных данных | `sudo agent-service-box doctor` |
| резервная копия сейчас | `sudo agent-service-box backup` |
| список копий | `sudo agent-service-box backups` |
| восстановить копию | `sudo agent-service-box restore <имя>` |
| обновление | распаковать новый релиз, `sudo ./<новый релиз>/box update` |
| откат на предыдущий релиз | `sudo agent-service-box rollback` |
| синхронизировать Git-зеркала сейчас | `sudo agent-service-box sync-mirrors` |
| журнал сервиса | `journalctl -u agent-service -n 100` |

`agent-service-box` ставится в `/usr/local/sbin` и всегда вызывает установщик
активного релиза.

### Где что лежит

| Путь | Что | Владелец |
|---|---|---|
| `/opt/agent-service/releases/<релиз>/` | проверенный релиз и его venv, только чтение | root |
| `/etc/agent-service/box.yaml` | конфигурация владельца | root, 644 |
| `/etc/agent-service/secrets.env` | секреты, читает только systemd | root, 600 |
| `/etc/agent-service/generated/` | `service.json`, `policy.json` (генерирует box) | root:agent-service, 640 |
| `/var/lib/agent-service/` | очередь, граф, Git-зеркала, `run/loaded.json` | agent-service, 700 |
| `/var/lib/agent-service-box/` | журнал установщика, отчёты установок | root, 700 |
| `/var/backups/agent-service/` | резервные копии | root, 700 |

Сервис работает от системного пользователя `agent-service` с `ProtectSystem=strict`,
пишет только в `/var/lib/agent-service`, не имеет доступа к Docker и к
инфраструктурным credentials.

### Фазы установки

`validate → release → configure → mirrors → probes → [backup] → graph → start → smoke → report`.
Каждая фаза идемпотентна. Повторный `install` ничего не меняет и не перезапускает
работающий сервис. Если установку прервать, повторный запуск её доделывает.
Фаза `backup` есть только при замене релиза: сервис останавливается, состояние
копируется.

### Три уровня готовности

- живость: `/healthz` отвечает. Это всё, что она значит;
- процесс: PID из systemd совпадает с `loaded.json`, процесс загрузил ядро и релиз из
  manifest, `/status` принимает токен;
- сценарий: граф не пуст, источники свежие, проверки GitHub/Jira проходят, нет
  уведомлений сервиса (401/403, недоступный источник, выключенная модель), offline smoke
  установленного релиза прошёл.

### Обновление и откат

`box update` из нового релиза останавливает сервис, делает копию `pre-update`,
строит граф новым кодом, запускает новый релиз. Если новый процесс не становится
готовым, box сам откатывается на прежний релиз.

`box rollback` сравнивает версии схем на диске с тем, что открывает целевой релиз
(manifest, `contracts.state`):

- совместимы: переключается только релиз, состояние не трогается, события и комментарии
  после обновления сохраняются;
- несовместимы (новый релиз мигрировал очередь): box делает страховочную копию
  текущего состояния, восстанавливает копию `pre-update` этого релиза и запускает его.
  События после копии сервис забирает сверкой с Jira/GitHub при старте, а
  комментарии находит по маркеру и обновляет, а не создаёт заново.

Хранилище графа мигрирует только добавлением таблиц: старый релиз открывает
файл более новой схемы до той версии, что указана в manifest. Очередь сервиса
открывается только той же версией схемы, поэтому откат через схему всегда идёт
через восстановление копии.

### Что не входит в копию

Git-зеркала (box клонирует их заново), `secrets.env` (храните в хранилище секретов
компании), сам релиз (неизменяемый, ставится заново из архива).
