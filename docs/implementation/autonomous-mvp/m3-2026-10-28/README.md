# M3 — подготовка установки, 28.10.2026

**IN PROGRESS / ACCESS BLOCKED. MODEL OFF. В этом запуске установка на Cloud.ru не выполнялась.**

Исходная и проверенная remote main: `d5e25fde5927eca99e574b2ac82be80cd5adfe16`.
GitHub compare и `git fetch origin main` подтвердили отсутствие последующих коммитов.
Работа: ветка `m3/dm-p1-ui-install`; пользовательские untracked master/continuation prompts не менялись.
Приоритет — существующая dm-p1-ui; новые ВМ, платные ресурсы, правила SG и старый pending plan не применялись.

## Фактически выполнено

| Проверка | Где | Результат |
|---|---|---|
| Скачивание опубликованного asset | ноутбук macOS | 8 976 729 байт; SHA256 совпал с pin |
| Проверка дерева и manifest штатным `release.py verify` | ноутбук | VERIFIED, code `14e65e8affe3b64a9ceb647f537e8af6ff7a1138` |
| TCP22 исторического IP `45.151.31.140` | с ноутбука, сейчас | CONNECTED; это ещё не идентификация ВМ |
| ED25519 host key | с ноутбука, сейчас | **MISMATCH** с console pin в репозитории; вход не выполнялся |
| SSH credentials | ноутбук | `~/.ssh` отсутствует, agent без identities; Cloud.ru/GitHub/Jira credentials в окружении отсутствуют |
| Поиск прежнего доступа | локальные каталоги и история команд | найдены SSH ключи RavenAcademy для другой ВМ; они не использовались для dm-p1-ui |
| Cloud.ru console | после входа владельца | текущие VM ID/FIP/SG подтверждены; Ubuntu 24.04, 2 vCPU, 4 ГБ RAM, 30 ГБ SSD |
| Виртуальная / серийная консоли | авторизованный браузер | экран ОС не загрузился; spinner после ожидания, VNC повторно загружена один раз |
| Облачные резервные копии ВМ | console UI | список пуст; локальные backups на ОС ещё не обследованы |
| Публичный HTTPS демо | ноутбук → 45-151-31-140.sslip.io | TLS ConnectionResetError; HTTP response не получен; сертификат/доступность не подтверждены |
| Box plan конфигурации | локально macOS, отдельный prefix | exit 1: нет secrets; Apple Git version parser и sandbox bind checks не дают переносимого вердикта для Linux |
| GitHub connector | подключён | доступ к исходникам и selected installation; это не ключ сервисного GitHub App |
| Jira | каталог плагинов | Atlassian доступен, но не установлен/не подключён |

Доказательства: [release-verification.json](evidence/release-verification.json),
[manifest.json](evidence/manifest.json), [ssh-preflight.json](evidence/ssh-preflight.json),
[cloud-console.json](evidence/cloud-console.json), [local-plan.json](evidence/local-plan.json),
[public-https.json](evidence/public-https.json).
Архив находится локально в `/private/tmp/m3-agent-release.tar.gz`, распакован в `work/m3-release/` (не коммитится).
SHA256: `95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`.
Manifest SHA256: `9fdd6e8aa48e5e09d803840ef262c1c3d57bb01af9c884a690f86a98888533a9`.
Проверены именно скачанные байты; новый выпуск не запускался.

## Точная граница блокировки

Текущий SSH-сервер по старому IP предъявил fingerprint hex
`ff9e41bf2b245a7fe2a16f6de1f419171a02fdb542128c04d6212b4a571af870`,
ожидаемый console pin — `514f4f24c935f805cd914c2b7c0b1868173665eab883feaf6dff3822f0afdd25`.
Причина изменения неизвестна: нельзя предполагать переустановку или принадлежность IP.
`known_hosts` и pin не обновлялись. Текущий FIP → VM ID/имя/project уже сверен через авторизованную Cloud.ru консоль.
Остаётся независимая сверка ключа в консоли ОС, которая пока не загрузилась. Не отключать StrictHostKeyChecking.

Следующий заблокированный шаг — **аутентифицированное свежее обследование dm-p1-ui**.
Ресурсы, процессы, Nginx/TLS, каталоги, службы, демо и backups сейчас NOT_VERIFIED.
Сведения 18.10 не считаются текущим обследованием.
Параметры конфигурации ВМ подтверждены в Cloud console; свободная RAM/диск/нагрузка не измерены.
После обследования и backup можно применять разрешённые обратимые изменения хоста.

Даже после восстановления SSH минимальный box требует `github.repositories` (минимум один,
с `watch_prs`), bot login и App PEM либо token, а также webhook secret. Jira необязательна;
удаление Jira не устраняет требование GitHub credentials. `dry_run` не обходит validation/probes.
Не подставлять фиктивные токены, основной agent или тестовые loopback API ради зелёной установки.
Bootstrap перед validation может разложить проверенный release/venv, но это не запущенный сервис.
Точный второй блокер: `validate` (отсутствующие App identifiers/PEM); после него нужны реальные source probes.

## Размещение и продолжение

Конкретное предлагаемое размещение и процедуры — [RUNBOOK.md](RUNBOOK.md).
До свежего inventory это кандидат, а не одобренная по фактам конфигурация хоста.
Кандидат [box.candidate.yaml](box.candidate.yaml) проверен только локальным вызовом CLI
из скачанного релиза, с отдельным prefix и process supervisor; target systemd plan NOT_RUN.
Локальные ошибки Apple Git/sandbox bind не являются замером версии git/занятости порта ВМ.
Штатные пути `/opt/agent-service`, `/etc/agent-service`, `/var/lib/agent-service`,
пользователь/units `agent-service`; webhook listener `127.0.0.1:8091`.
Ни demo checkout, ни его state/units не используются. Если штатные пути/units уже заняты,
установку остановить и пересмотреть размещение: `--prefix` предназначен для development,
а не для второй production systemd установки.

| Приёмка на целевом хосте | Статус |
|---|---|
| свежий полный inventory / backup демо | NOT_RUN — доступ не подтверждён |
| box plan / install / doctor | NOT_RUN — сначала доступ, затем реальные GitHub inputs |
| loaded SHA, process uid, model OFF, status/logs | NOT_RUN — установленный процесс не проверен |
| restart / reboot и автозапуск | NOT_RUN |
| backup / restore и история/очередь | NOT_RUN |
| update / rollback на другой проверенный релиз | NOT_RUN |
| настоящие App/Jira/HTTPS события | NOT_RUN — отдельная LIVE M2 приёмка |

## Недоступные входы владельца — один список

1. Вход в Cloud.ru уже выполнен владельцем; VM/FIP проверены. Открыть консоль ОС в обычном
   браузере, если она работает там, и войти штатно: это позволит проверить host key и восстановить
   доступ. Секреты в чат не нужны; сброс пароля не выполнялся.
   Известные SSH ключи ноутбука относятся к RavenAcademy, не применять их к другой ВМ.
2. Назначить отдельные тестовые Orders/Reporting repositories и Jira site/project, разрешённые
   тестовые операции. GitHub connector не умеет создавать репозитории/App и управлять private key;
   у него нет доступного Actions dispatch. App ID/installation/bot identity должны быть именно тестового App,
   а не installation ID коннектора. Дать доступ к настройкам GitHub/Jira либо подключить Atlassian.
3. Доставить App PEM/Jira token штатно на подтверждённый хост (root-only secrets.env; PEM доступен
   service group), без передачи в чат. Согласовать hostname HTTPS и право настроить DNS/сертификат
   и только два webhook location. `/status` и `/graph` остаются приватными.

Логины/согласование контура не выдаются за успешную интеграцию.
Передача M2 готовой установки **не выполнена**: установленного SHA и проверенных адресов нет.
M2 остаётся PARTIAL / LIVE BLOCKED; этот отчёт не закрывает его.

## Локальная проверка комплекта

`python -m unittest discover -s infra/cloudru/box -p 'test_*.py' -v`: 58 тестов, OK,
1 skipped (Terraform отсутствует); [полный вывод](evidence/box-infra-local-tests.log).
`inventory.py` прошёл py_compile; на Linux-хосте не запускался. Проверка whitespace `git diff --check` чистая.
Это не подтверждает установку или recovery на Cloud.ru.

Независимое ревью подготовленного комплекта: две Important-ошибки исправлены до
использования на хосте. Сырые строки Nginx исключены из inventory (однострочный location
мог содержать Authorization); регрессия `test_inventory.py` наблюдалась RED → GREEN.
В runbook разделены generated-каталоги 750 и файлы 640. Фактических секретов в evidence
не найдено. Отложенных minor замечаний нет. Ревью документов не оценивает ОС/демо,
принадлежность нового host key, SSH/консоли, установку/recovery или внешние интеграции:
всё это остаётся непроверенной частью M3/M2, а не исключением из требований.
