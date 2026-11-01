# GitHub pilot → оператор

1. **Уже проверено Connector API:** private rengalaxies/agent-pilot-orders (1437522215)
   и agent-pilot-reporting (1437522551), все refs/bytes совпадают с prepared.json, PR нет.
   Bot login rengalaxies-agent-pilot[bot], numeric349497413 подтверждены. App5515659,
   installation176298402 пока только configured/owner UI: App JWT ещё не подтверждён.
2. **Блокер GitHub:** создать/настроить environment `agent-pilot-app` с required reviewer
   и deployment branch rule только `main`; доставить PEM этой существующей App в environment
   secret `AGENT_PILOT_APP_PRIVATE_KEY` через доверенное хранилище. Наличие ключа неизвестно;
   новую App/installation/key эта пачка не создаёт. Значения не отправлять в чат/PR.
   Repository-level secrets metadata недоступны; не считать это доказательством отсутствия key.
3. После merge probe fix сверить актуальный main и выполнить:
   `gh workflow run agent-pilot-app-probe.yml --ref main -f expected_main_sha=FULL_CURRENT_MAIN_SHA`.
   Approve environment должен назначенный reviewer; обходов и rerun нет. Проверить каждую
   запись App identity / installation / exact selected repos / bot / refs / PR reads / revoke.
   Пустые PR lists допустимы, но не доказывают чтение будущего реального PR diff.
4. Минимальные права существующей App: Metadata read, Contents read, Pull requests read,
   Issues write; Only selected repositories — ровно два private pilot repo. При несовпадении
   probe FAIL; не расширять права ради прохождения. Read-only probe не проверяет comment write.
5. Config: `m2-a-2026-10-28/box.github-only.yaml` (dry_run, MODEL OFF). На сервисе PEM
   потребляет `GITHUB_APP_PRIVATE_KEY_PATH`, подпись webhook — `GITHUB_WEBHOOK_SECRET`;
   GitHub environment secret не копируется из Actions на сервис. Оператор доставляет ключ
   отдельно из доверенного источника. Не использовать Connector как service App.
6. Webhook Active/URL сейчас не менялись. После подтверждённого HTTPS сервиса настроить
   App webhook `<HTTPS_ORIGIN>/webhooks/github`, SSL verification ON, pull_request +
   issue_comment, отдельный согласованный secret. Jira admin webhook — `/webhooks/jira`,
   body + HMAC secret, issue/comment события только согласованного test project.
7. Для Jira→PR→актуального результата ещё нужны: установленный M3 exact release/loaded
   identity и единственный worker; App-auth PASS; Jira site/project/bot accountId и
   JIRA_EMAIL/JIRA_API_TOKEN/JIRA_WEBHOOK_SECRET в хранилище; подписанная HTTPS доставка;
   разрешённая отдельная LIVE-приёмка и публикация. Не выдумывать Jira key/данные.
8. После согласования сценария оператор создаёт Jira issue, затем PR orders main ←
   pilot-page-limit с настоящим Jira key; update того же head fast-forward на pilot-restored;
   redelivery/API failure/self-comment/restart, те же comment IDs и свежие base/head.
   Neutral pilot-docs-only, ambiguity, Reporting pilot-explicit-limit — отрицательные/repair
   контроли. Сейчас PR/Issues и ветки не создавались/не переписывались. Полный сценарий:
   `../m2-a-2026-10-28/LIVE.md`; deployment/recovery — отдельный handoff release-recovery-2026-10-31.

Общий M2 остаётся PARTIAL / LIVE BLOCKED. MODEL OFF, M3/participant/client benefit здесь
не квалифицируются. От владельца сейчас нужны только защищённый environment + доверенная
доставка PEM + reviewer approval будущего запуска; инфраструктуру выполняет другой исполнитель.
