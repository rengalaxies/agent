# M3: размещение, приёмка и откат

Это подготовленный порядок исполнения, **не журнал выполненных операций**.
Текущий результат каждого шага записывается в README и evidence. Новый платный ресурс
и расширение ingress в этот план не входят; старый pending Terraform plan не применяется.

## 1. Идентификация и обследование

Через авторизованную Cloud.ru консоль сверить project `20853297-65b7-42a8-af40-25c8d2df4e11`,
VM `c9e589fc-a42a-4cc3-8038-fe7d73929713`, имя dm-p1-ui, FIP и NIC/SG attachment.
Через консоль ОС получить `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub -E sha256`.
Pin обновлять только после независимой сверки и объяснения расхождения, с evidence.
Для SSH использовать явный ключ, `IdentitiesOnly=yes`, `StrictHostKeyChecking=yes`
и отдельный проверенный known_hosts; не `accept-new` при уже обнаруженном mismatch.

Скопировать `inventory.py` в приватный staging и выполнить `sudo -n python3 inventory.py`.
Это чтение: ресурсы, процессы без аргументов, порты, unit/timer names и каталоги.
Выход сначала сохранить приватно; после просмотра отредактировать чувствительные данные для repo.
Дополнить по обнаруженным путям: SHA demo checkout, состояние unit/контейнеров, mounted volumes,
размеры и тип DB, список backups с датами, состояние TLS (issuer/SAN/expiry через openssl x509).
Routing и TLS paths проверить приватно; в отчёт переносить только проверенные безопасные
поля вручную. Скрипт не выводит строки nginx config: даже `location` может содержать секреты.
Не печатать process environment, `.env`, ключи или полный `nginx -T` в evidence.

Gate перед записью: Linux x86_64/Python 3.12, systemd/git, достаточно RAM и диска под
release + mirrors + state + две копии демо/состояния. Измерить, не брать 2 vCPU/2GB как факт.
Проверить, что свободны 8091, пользователь, пути и units `agent-service*` ниже.

## 2. Backup демо до любых изменений

Записать текущий boot ID, demo SHA, health/HTTP baseline и владельцев каталогов.
Создать root-only каталог `/var/backups/m3-preinstall/<UTC timestamp>` (700).
Скопировать конфигурацию Nginx/systemd и demo config, сохраняя владельцев/права;
секреты остаются только в приватной backup, никогда в GitHub artifacts/repo.
SQLite копировать через SQLite backup API; для иной DB — штатный dump/согласованная
остановка только обнаруженной службы. Не копировать работающую DB простым `cp`.
Для файловых volumes нужна согласованная консистентная копия.
Посчитать SHA256 backup, проверить чтение архива и целостность копии DB.
Записать private backup path и команды восстановления. Повторить baseline демо.
Если консистентность/размер/путь демо неизвестны — это gate, не выполнять установку.

## 3. Размещение рядом с демо

| Объект | M3 |
|---|---|
| Сервисный uid/gid | `agent-service`, system/nologin |
| Releases | `/opt/agent-service/releases/<name>` root, read-only |
| Конфигурация | `/etc/agent-service/box.yaml` root 644 |
| Секреты | `/etc/agent-service/secrets.env` root 600 |
| App PEM | `/etc/agent-service/github-app.pem`, root:agent-service 640; проверить чтение от uid сервиса |
| Generated config | каталоги `/etc/agent-service/generated` root:agent-service 750; файлы config 640 |
| Очередь/граф/зеркала/loaded | `/var/lib/agent-service` agent-service 700 |
| Журнал установщика | `/var/lib/agent-service-box` root 700 |
| Backup M3 | `/var/backups/agent-service` root 700 |
| Units | `agent-service.service`, `agent-service-sync.service/.timer`, `agent-service-backup.service/.timer` |
| Listener | `127.0.0.1:8091`, никакого нового публичного порта |

Эти пути выбираются только при отсутствии конфликта с demo inventory.
Вторую systemd установку посредством test `--prefix` не создавать.
Взять `../m2-2026-10-28/box.yaml`, заменить реальными тестовыми identifiers,
`installation_id: m3-acceptance`, port 8091, `publication: dry_run`; модель отсутствует.
Модельные/облачные credentials не передавать процессу. Без настоящего GitHub App
оставить конфигурацию неподготовленной, не придумывать успешные probes.

## 4. Проверка поставки, plan и install

Доставить опубликованный архив без повторного выпуска. На хосте проверить SHA256:
`95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`,
имя `agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312`.
После безопасной распаковки выполнить штатный `release.py verify` из проверенного дерева.
Ожидаемый code SHA `14e65e8affe3b64a9ceb647f537e8af6ff7a1138`.

В root-only staging, с подготовленными реальными config/secrets:

```bash
sudo ./agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312/box plan --config box.yaml
sudo ./agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312/box install --config box.yaml
sudo agent-service-box status --json
sudo agent-service-box doctor
sudo systemctl show agent-service -p MainPID -p User -p Group -p ActiveState -p SubState -p ProtectSystem -p NoNewPrivileges
sudo systemctl is-enabled agent-service agent-service-sync.timer agent-service-backup.timer
sudo journalctl -u agent-service -u agent-service-sync --since '10 minutes ago' --no-pager
```

Сохранить stdout/exit каждого шага без секретов. Код 2 — не READY.
Сверить manifest/code/core identity с `run/loaded.json`, PID/uid фактического процесса,
authenticated `/status` и status CLI. Проверить отсутствие model config и model requests.
HTTP `/healthz` доказывает только живость. Сверить права файлов и постоянное состояние;
повторить demo baseline. Если source probes блокируют запуск, зафиксировать фазу и реальную ошибку.

## 5. Приватный status/logs, webhook HTTPS

После успешной установки: SSH local forward
`ssh -N -L 18091:127.0.0.1:8091 <verified-ssh-profile>`.
`/status` и `/graph` запрашиваются по `http://127.0.0.1:18091` с bearer status token,
полученным оператором приватным способом; не печатать токен в command line/logs/repo.
Журналы: `sudo journalctl -u agent-service -u agent-service-sync -u agent-service-backup`.
Проверить отсутствие bearer → отказ и корректный bearer → authenticated response.

Публичный hostname пока не назначен. После согласования DNS/TLS добавить к существующему
proxy только точные `/webhooks/github` и `/webhooks/jira` → 127.0.0.1:8091,
raw body/signature headers, лимит 5 MiB. Остальные пути M3 возвращают 404;
не менять demo location/auth. Перед reload: config backup, `nginx -t` (либо caddy validate
для фактически обнаруженного proxy), затем проверить валидный сертификат и demo baseline.
Публикация новых URL требует согласования, даже если 443 уже открыт.
Никаких новых правил SG или TLS verification bypass.

## 6. Проверки восстановления на целевой ВМ

Перед каждым шагом сохранить release identity, boot ID, состояние units/timers и безопасный
срез counts/history/checkpoints из read-only DB. Сравнение counts само по себе не доказывает
сохранность: сверить стабильные IDs/versions и содержимое контрольной истории без секретов.

1. **Restart:** принять контролируемое задание в согласованном контуре, перезапустить
   только agent-service; убедиться, что очередь/история сохранились, job продолжилось,
   новый PID соответствует loaded; demo baseline проходит. Без внешнего контура это только
   проверка рестарта, не доказательство публикации/усыновления комментария.
2. **Reboot:** только после backup и проверки автозапуска демо/возможности восстановления
   доступа; записать boot ID до/после, downtime, units/timers/loaded/state/demo baseline.
   Перезапуск процесса не считать reboot всей ВМ.
3. **Backup/restore:** `sudo agent-service-box backup --label m3-acceptance`,
   `backups`; проверить manifest/hash и DB integrity. Сохранить текущую копию перед restore.
   `sudo agent-service-box restore <verified-name>`; проверить identity/историю/checkpoints,
   durable jobs и demo baseline. Не редактировать таблицы production вручную.
4. **Update/rollback:** требуется второй отдельно проверенный совместимый релиз и source probes.
   Записать исходный и целевой SHA/manifest, выполнить update и rollback, сравнить историю
   и очередь до/после обоих переходов. Повторный install того же SHA не считать update.
   Старый f5c0c36 содержит дефекты до M2; не включать на нём live публикацию.
   При отсутствии подходящего второго релиза оставить NOT_RUN с конкретной причиной.

При совместимых схемах штатный rollback меняет release, сохраняя state. При несовместимых
схемах нужен matching pre-update backup: проверить какие события будут восстановлены
reconciliation. Backup DB не отменяет внешние комментарии.
Не создавать вымышленные минуты подключения: записывать только измеренные человеком.

## 7. Откат установки

Сначала остановить M3 worker и его timers; сохранить state/journal/logs и текущий backup.
Для замены release: `sudo agent-service-box rollback` и проверка loaded/doctor/history.
Для повреждения state: штатный `restore` из проверенной копии; не удалять SQLite.
Не запускать два worker с одним state или внешней идентичностью.
Если нужно убрать свежую установку, disable только созданные M3 units/timers,
вернуть только добавленный M3 proxy fragment из preinstall backup, проверить proxy config,
reload и demo baseline. Каталоги M3 оставить архивированными приватно до приёмки отката;
demo/state не удалять и не заменять целиком.

## 8. Передача исполнителю M2

Передавать после готовности: verified SSH profile/адрес (без ключа), приватный status URL
и способ доступа, команды журналов, установленный полный code SHA/manifest, model OFF,
installation ID, repo/App/Jira identifiers, webhook hostname/paths/events/limits без секретов,
статус каждого recovery check. Сейчас передача готовой установки BLOCKED.
LIVE Jira → PR и гонки закрывает M2 отдельно по своему HANDOFF-M3.md.
