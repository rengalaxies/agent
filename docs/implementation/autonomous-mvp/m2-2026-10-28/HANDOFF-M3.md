# Подключение M3 для завершения LIVE-приёмки M2

Состояние 28.10.2026: **M2 PARTIAL / LIVE BLOCKED, MODEL OFF**. Владелец подтвердил:
установленный автономный сервис, тестовый контур, credentials и HTTPS URL пока не
определены. Демо dm-p1-ui не считается M3. Основной `rengalaxies/agent` используется
для разработки/PR; он не разрешён как тестовая площадка для бота. Новая ВМ здесь не нужна.

## Код и точный артефакт

Исходные исправления: `7a624ed431ac2c3d7b8488985ca3cdc6e34147c7` (или содержащий
его проверенный merge в main, указанный в README). На старте M2 pin
`infra/cloudru/box/release.json` указывал на f5c0c36 без M1/M2. Актуальная поставка ниже.

Рабочий способ выпуска уже существует, новый установщик не требуется. На принятом
main после зелёных Core/box checks зафиксировать **полный** SHA:

```bash
gh workflow run agent-service-release.yml --ref main -f expected_main_sha=<EXACT_MAIN_SHA>
```

Сохранить run ID, URL, manifest и `.sha256`. Локально уже проверен кандидат
`7a624ed431ac2c3d7b8488985ca3cdc6e34147c7`, archive sha256
`9d665121216a54589aed02f319fa83c46ddebc6ed7bf19de80273a64b637f2ed` (две
одинаковые сборки, manifest VERIFIED); он не установлен в M3. Дождаться `release` **и**
`install-published`: сборка дважды, побайтное равенство архивов, скачивание
опубликованного asset, проверка sha256/manifest и чистая установка с systemd на CI.
Это CI, не VM/LIVE. По результату отдельным проверенным PR закрепить `url`, `sha256`,
`name` в `infra/cloudru/box/release.json`; не менять pin до появления проверенного asset.

Тот же воспроизводимый builder локально (Linux x86_64 / Python 3.12):

```bash
python tools/agent_service/box/release.py build --commit <EXACT_SHA> --platform linux-x86_64-cp312 --output work/m2-release/A
python tools/agent_service/box/release.py build --commit <EXACT_SHA> --platform linux-x86_64-cp312 --output work/m2-release/B
```

Сравнить архивы `cmp`, проверить `.sha256`, распаковать и выполнить
`python tools/agent_service/box/release.py verify <EXTRACTED_RELEASE>`. Manifest читает
blob-ы **коммита**, не рабочее дерево; wheel-ы проверяет hash-lock. PR box workflow также
сохраняет готовый архив и manifest в artifact `agent-service-box-<github.sha>` на 14 дней.
Он годится для воспроизведения CI, постоянная поставка должна иметь release asset/pin.

## Единственный список действий владельца M3

1. Выбрать уже существующий подходящий Linux-хост либо согласовать отдельный план M3.
   Для dm-p1-ui сначала обследовать ОС, ресурсы, порты, действующие сервисы, TLS,
   резервные копии и владельца. Не устанавливать поверх демо без согласованного плана.
   Передать исполнителю SSH-доступ и способ проверки host key. Это блокирует фактически
   установленный SHA, restart и восстановление.
2. Назначить отдельные тестовые GitHub repositories Orders/Reporting и Jira site/project,
   допустимые операции (создание/изменение задач и PR, комментарии App, redelivery,
   контролируемый отказ credentials и перезапуск). В основной agent не слать тестовые
   события. Это блокирует LIVE Jira → PR, дубли и self-loop.
3. Создать/выбрать GitHub App только для тестовых репозиториев. Права:
   Metadata read, Contents read, Pull requests read, Issues write. События: Pull request;
   Issue comment включить на время приёмки self-loop (они игнорируются сервисом).
   Зафиксировать App ID, installation ID и точный bot login. Установить App на provider
   **и** consumer. Webhook secret отдельный для этого контура. Token-режим — для
   разработки; LIVE acceptance проверяет App installation, не выдаёт токен за App.
4. Выделить Jira Cloud bot account/accountId, право Browse projects, Add comments,
   Edit own comments и видимость согласованных задач; создать API token выбранного типа.
   Для unscoped API token — **Basic email+API token** и URL site. Scoped API token
   также использует **Basic**, но base URL `https://api.atlassian.com/ex/jira/<cloudId>`;
   Bearer относится к отдельному OAuth access token, а не автоматически к scoped API token
   ([Atlassian](https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/)).
   Администратор регистрирует webhook с
   секретом и фильтром тестового проекта: issue created/updated/deleted; comment events
   для проверки цикла. Проверить настоящий `X-Hub-Signature: sha256=...` и стабильный
   `X-Atlassian-Webhook-Identifier` по полученной доставке. Локальная подпись этого не доказывает.
5. Доставить секреты штатным секрет-хранилищем/SSH на выбранный хост: root-only
   `/etc/agent-service/secrets.env`, App PEM и переменная
   `GITHUB_APP_PRIVATE_KEY_PATH`; имена `GITHUB_WEBHOOK_SECRET`, `JIRA_EMAIL`,
   `JIRA_API_TOKEN`, `JIRA_WEBHOOK_SECRET`. Box генерирует `AGENT_SERVICE_STATUS_TOKEN`.
   Значения не пересылать в чат, не извлекать GitHub Secrets; облачные/модельные
   credentials не подходят. Проверить доступ пользователя сервиса к PEM по runbook box.
6. Определить DNS/HTTPS, сертификат и reverse proxy. Снаружи только
   `/webhooks/github` и `/webhooks/jira`, raw body/заголовки подписи сохраняются,
   лимит 5 MiB. Шаблон [Caddyfile](Caddyfile); проверить `caddy validate` перед применением.
   `/status` и `/graph` доступны через приватный доступ/SSH tunnel и bearer token;
   TLS verification не отключать. Исходящий HTTPS: api.github.com, github.com для
   Git-зеркал, выбранный Jira API, releases/dependencies на этапе доставки. Webhooks
   не заменяются ручным запуском анализа.
7. Заполнить [box.yaml](box.yaml), соответствие сервисов, pinned branches, адрес Orders
   и реальные требования потребителя. Если используются примеры, перенести
   `examples/orders_reporting/stand.py`: Orders main (100), PR (20), Reporting вызов без
   page_size. Для точного `POSSIBLE_TRUNCATION` нужны подтверждённое требование полной
   коллекции и его источник; при его отсутствии ожидается ограниченный вывод/recheck.
   Не выдавать примерное требование за факт заказчика. Модель остаётся OFF.
8. Поставить проверенный текущий релиз, сверить manifest с loaded/status, провести сценарий
   ниже, сохранить доказательства. Зафиксировать вручную выполненные действия и реальные
   минуты, только если человек их измерил. До этого M2 не DONE.

## Подключение и наблюдение

По инструкции `infra/agent_service/README.md`: проверить архив, распаковать,
`sudo ./<release>/box plan --config box.yaml`, затем `install` (или `update` для уже
существующей box-установки). Сначала `publication: dry_run`: source probes, graph,
сверка App identity, Jira account/project, отсутствие обращений к модели. После согласования
контура включить `live` и применить конфигурацию `sudo ./<release>/box update --config box.yaml`.
Для нового контура использовать новое имя установки и отдельный state; иначе dry-run
receipts могут считаться выполненными публикациями. Не удалять production state.

```bash
sudo agent-service-box status --json
sudo agent-service-box doctor
sudo journalctl -u agent-service -u agent-service-sync --since '10 minutes ago' --no-pager
sudo systemctl status agent-service agent-service-sync.timer
```

Проверить `/healthz` локально (только живость), `/status` с `Authorization: Bearer ...`
(не печатать токен), `/graph` по тем же правилам. Сопоставить manifest code.commit,
`/var/lib/agent-service/run/loaded.json`, process/release/core identity. Оператор сохраняет
без секретов snapshot state/history или выборку из `service.sqlite` (read-only, без
редактирования таблиц): events, jobs, intents/receipts, notices, checkpoints. Request ID
находится в result.request_id/correlation_id, event ID — в events/jobs/result; в Jira
версия — digest смысловых полей, не updated timestamp; PR версия включает base/head,
ветку назначения и явные Jira keys. Базу и исходники не публиковать целиком без проверки.

## LIVE-сценарий и критерии

Заполнить [live-record.template.json](live-record.template.json). Указать все настоящие
URL задач/PR/комментариев, полные SHA, request/event ID. Исходно всё `NOT_RUN`.

1. Создать задачу в согласованном проекте: Orders GET /orders page_size 100 → 20.
   Сервис без ручного анализа публикует предварительное влияние, ограничения/основания,
   модель OFF. Отсутствие кода не доказывает поломку.
2. Создать PR с явным ключом задачи в title/branch. Проверить статическую связь Reporting,
   основания `repository@commit:path#line`, base/head и версию задачи отдельно.
   Явный ключ не доказывает, что задача существует или что изменение её реализует.
   Несколько ключей сохраняются как несколько явных ссылок; единственный не выбирается.
3. Исправить поведение новым head (100 или явная корректная пагинация потребителя).
   Проверить тот же comment ID, отсутствие прежнего риска в текущем теле и старый result
   только в истории. Отдельно изменить задачу и проверить новую версию/замену комментария.
4. Повторить точную доставку из GitHub App delivery UI и доступного Jira redelivery,
   затем доставить старый payload с новым delivery ID: fetch текущего ресурса определяет
   версию. Число jobs/комментариев/POST не растёт из-за дубля. Не подделывать payload
   вместо утверждения, что redelivery прошла через настоящую платформу.
5. Провести нейтральный README PR и задачу `GET /orders` при двух провайдерах этого
   маршрута без названия сервиса: ожидается `no_supported_delta` / `intent_unclear`,
   без уверенного вывода. Сопоставить предварительную гипотезу, статическую связь и
   **реальный** результат проверки отдельно: сервис не запускает тесты потребителя.
6. При разрешённом тесте временно отозвать/ограничить тестовые credentials либо применить
   отказ на согласованном egress proxy; сохранить реальный HTTP status/request ID.
   Проверить pause/backoff, FAILED/BLOCKED/notices, восстановить доступ, reconciliation.
   Настоящий ответ 429/5xx не выдумывать и не вызывать rate limit на production.
   Если controllable external error недоступна — этот пункт LIVE NOT_RUN, не DONE.
7. Включить delivery собственных issue_comment/Jira comment событий; сохранить ID.
   Анализ и новые комментарии не размножаются. Перезапустить worker после принятого
   задания/записи, проверить durable очередь и усыновление комментария по author+marker.
8. В согласованном тесте отключить webhook, изменить head, дождаться reconciliation;
   вернуть webhook. Проверить пропущенное событие и возврат к уже виденному head.
9. Отдельно исследовать race: между контрольным чтением и отправкой изменить внешний
   head/задачу (управляемая задержка только тестового proxy или подтверждённая трасса).
   Записать порядок GET → изменение → POST/PATCH → GET → stale notice → новый result,
   время видимости старого тела. Повторить с ошибкой post-send GET и restart.
   Без управляемой трассы live race остаётся NOT_RUN даже при зелёных локальных тестах.

## Откат

Перед update: `sudo agent-service-box backup`, записать release/manifest/SHA и имя копии.
При отказе: `sudo agent-service-box rollback`; для повреждённого состояния — штатный
`restore <backup>` с остановкой worker по инструкции box. Не удалять SQLite/комментарии,
не перезапускать восстановленный worker параллельно старому. После возврата проверить
loaded identity, `doctor`, reconciliation, author+marker и один комментарий на ресурс.
Схема очереди M2 остаётся 1; откат на код до M2 возвращает исправленные ошибки, это
временное восстановление работоспособности, не сохранение гарантий M2. Старый PR version
на новой установке откроет ровно одно новое поколение при первой сверке.

При внешней проблеме сначала остановить тестовый worker и webhook/отозвать только
тестовый App access; сохранить state и журналы. Подтверждённые комментарии могут уже
существовать во внешней системе: восстановление БД не откатывает внешний API.

## Готовая поставка после #69

Выпуск уже выполнен на main **`14e65e8affe3b64a9ceb647f537e8af6ff7a1138`**:
[release](https://github.com/rengalaxies/agent/releases/tag/agent-service-0.1.0-g14e65e8affe3),
[проверка опубликованной установки](https://github.com/rengalaxies/agent/actions/runs/40693796501).
Архив `agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312`, sha256 `95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`.
Публичный URL: https://github.com/rengalaxies/agent/releases/download/agent-service-0.1.0-g14e65e8affe3/agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312.tar.gz
Pin в `infra/cloudru/box/release.json`: [PR #70](https://github.com/rengalaxies/agent/pull/70),
после verification опубликованного asset.
Команду выпуска выше повторять для этой версии не надо (существующий tag не заменяется).

Для M3 остаются выбор хоста и контур/credentials/TLS, установка этого asset, сверка
loaded с `14e65e8affe3b64a9ceb647f537e8af6ff7a1138`, и весь LIVE-сценарий. CI-установка с systemd не является M3.
Старый pending cloud plan на f4e6ab7 не применять: после принятия pin нужен новый plan,
review digest/срока/бюджета и отдельное одобрение apply. Здесь apply не выполнялся.
