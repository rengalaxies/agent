# Agent Graph Demo Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. The preserved execution method is the local Windows Codex session with working SSH to dm-p1-ui. Steps use checkbox syntax for tracking. Do not spawn subagents unless separately requested by the user or required by applicable repository instructions.

**Goal:** Реализовать воспроизводимое демо «зависимость → изменение API → реальное последствие → исправление → обновлённый граф» с UI на существующей ВМ.

**Architecture:** Отдельные исполняемые Python-сервисы и независимый runner образуют синтетическое окружение. FastAPI backend с одной устойчивой очередью вызывает agent_graph CLI и отдаёт статический UI; Nginx проксирует backend на loopback 18081. Операторский runner управляет тестовыми контейнерами по SSH; web не получает Docker или sudo.

**Tech Stack:** Python 3.12, существующие pydantic/FastAPI/uvicorn extras проекта, requests для consumers, SQLite, plain HTML/CSS/JavaScript с SVG, unittest, Playwright для браузерной приёмки, Docker Compose, Nginx. Новые Python-зависимости и runtime-образы закрепить в dedicated lock/manifest; не обновлять зависимости других контуров ради демо.

**Spec:** [Согласованная спецификация](../specs/2026-10-21-agent-graph-demo-design.md), согласие владельца продукта получено 21 октября 2026. Направление исполнения уже выбрано: локальный Codex, затем SSH с Windows.

## Global Constraints

- Целевая ВМ dm-p1-ui: 2 vCPU / 4 GiB, Ubuntu 24.04.4; адрес 45.151.31.140, пользователь dmadmin. Ключ выбирается по успешной локальной SSH-проверке, а не по предположению об имени v2.
- Backend публикуется только на 127.0.0.1:18081. Порты 8000/8080 сохраняем за существующими конфигурациями. Сервисы sandbox не публикуются в интернет.
- Начальные пределы: одно исполняемое задание; до четырёх ожидающих, затем явный busy; общий job deadline 180 секунд; max_files 256, max_file_bytes 65536, max_corpus_bytes 2000000, scan_seconds 15, freshness_seconds 3600, max_tool_lines 60.
- Плановые memory caps: backend/worker/graph 768 MiB, Orders 192 MiB, Status 128 MiB, каждый consumer job 128 MiB, тестовый runner 256 MiB. Consumer/test jobs и анализ сериализуются.
- Граф не выполняет тесты и не выдаёт разрешение на выпуск. report_check сохраняет EXTERNAL_REPORTED. Реальная проверка runner и условный вывод графа — разные объекты.
- Профиль http-requests-2; произвольные wrappers/dynamic URLs, межобластное сравнение разных view и inference неизвестной конфигурации не объявляются поддержанными.
- Web-процесс не получает Docker socket, членство в docker group, sudo, SSH-ключ или cloud credentials.
- Источники и runtime versions закрепляются digest; proposed и running — разные поля. Корень Export разрешён до его первого HTTP-вызова.
- Большая локальная LLM, CPU-модель как её непроверенная замена, PostgreSQL, RabbitMQ, SSO и multi-tenant в этот объём не входят.
- Синтетические fixtures и диагностическая v4-серия остаются отдельными: демо не доказывает спрос, H1 или сокращение труда.
- Принятый SHA PR №28 необходим до интеграционной приёмки и развёртывания. При составлении плана PR открыт/draft, HEAD f1c4546725e759ffc06ca0281f7103132dbcfe73; это не заранее принятое основание.

## Review Focus

1. Повторный POST после сетевого обрыва возвращает тот же job только при одинаковом содержимом; иной запрос с тем же ключом даёт конфликт — Task 4.
2. Запоздавший результат после новой revision/reset не становится текущим — Tasks 2, 4, 6.
3. Тест от другой версии сервиса или dataset не «озеленяет» актуального кандидата — Tasks 2, 7.
4. Посторонняя сессия, path traversal и HTML в source не раскрывают данные и не исполняются — Tasks 3, 5, 6.
5. Падение процесса оставляет RUNNING неопределённым, не повторяет inference и не снимает ещё действующий OS-lock модуля — Tasks 3, 4.

Все пять классов включены в названные ниже проверки; это фокус ревью, а не замена остальной приёмки.

---

## Карта файлов и общие типы

Предлагаемые новые пути. Перед исполнением проверить их отсутствие и актуальные AGENTS.md; если после ревью появились эквивалентные компоненты, явно скорректировать карту без дублирования.

| Путь | Ответственность |
|---|---|
| examples/agent_graph_demo/services/{orders,status}/app.py | Настоящие FastAPI API и их обычные зависимости |
| examples/agent_graph_demo/consumers/{reporting,billing,health,export}/client.py | Вызовы requests; Export до шага E без HTTP-вызова |
| examples/agent_graph_demo/scenarios.py | Построение A/B/D/E из контролируемого diff, без import исполняемых source |
| examples/agent_graph_demo/oracle.py | Независимая проверка 250 ID; не включается в анализируемый корпус |
| src/agent_graph_demo/contracts.py | Общие строгие типы/ошибки API, manifest и receipt |
| src/agent_graph_demo/snapshots.py | Разрешённые снимки, manifests, materialize, policy и сериализация переходов |
| src/agent_graph_demo/graph_cli.py | Ограниченный JSON CLI adapter с deadline/отменой |
| src/agent_graph_demo/store.py, worker.py | Сессии, идемпотентная очередь, leases и история |
| src/agent_graph_demo/api.py, auth.py | HTTP-маршруты, роли и серверная область доступа |
| src/agent_graph_demo/web/{index.html,app.js,styles.css} | Экран карты/изменения/оснований/истории |
| tools/agent_graph_demo/{run_scenario.py,ingest_receipt.py,accept.py} | Доверенный операторский runner, импорт результата, приёмка |
| infra/agent_graph_demo/{compose.yaml,Dockerfile,nginx.conf,agent-graph-demo.service} | Воспроизводимое размещение и запуск |
| infra/agent_graph_demo/{requirements.lock,images.json,README.md} | Закреплённые зависимости, image digests и эксплуатация |
| tests/graph_demo/test_*.py | Поведенческие unit/integration boundary checks |
| tests/graph_demo/browser_acceptance.py | Реальный браузерный сквозной сценарий |
| .github/workflows/agent-graph-demo.yml | Отдельная бесплатная серия без model secrets |
| docs/agent-graph-demo/{RUNBOOK.md,ACCEPTANCE.md} | Показ, фактическая приёмка, ресурсы и ограничения |

Создать обычные __init__.py там, где нужны importable packages; для web assets добавить package-data agent_graph_demo в pyproject.toml. Не расширять существующий ui/index.html старой исследовательской модели ACCEPT/REJECT.

В contracts.py определить единственные общие типы (Pydantic, extra=forbid):
- ScenarioVersion = Literal["A", "B", "D", "E"]; JobAction = Literal["prepare_context", "analyze_change", "investigate"].
- SnapshotManifest: schema_version=1, scenario_version, product_sha, extractor_profile, dataset_sha256, repositories[{id,service,revision,files[{path,sha256}]}], manifest_sha256. manifest_sha256 считается по каноническому JSON остальных полей.
- SessionRecord: id, revision, scenario_version, proposed_manifest_sha256, running_manifest_sha256|null, base_context_id|null, current_context_id|null, created_at.
- JobRecord: id, session_id, session_revision, action, status, input_sha256, created_at, started_at|null, finished_at|null, result_ref|null, error_code|null.
- CheckReceipt: id, session_id, session_revision, proposed_manifest_sha256, running_manifest_sha256, dataset_sha256, fixed_check_id, expected_count, actual_count, missing_ids, duplicate_ids, unexpected_ids, status PASS|FAIL|ERROR, command_id, started_at, finished_at, exit_code, origin="operator_runner".
- Actor: subject, role operator|viewer, allowed_session_ids. Session ownership/grants проверяются сервером.
- DemoError(code: str, http_status: int); timestamp UTC, JSON без NaN, arbitrary caller fields не сохраняются как authority.

### Task 1: Исполняемый сценарий и независимая проверка

**Files:** Create services/consumers/scenarios.py/oracle.py из карты; tests/graph_demo/test_scenario.py; начальные Dockerfile/requirements.lock для их запуска.

**Interfaces:**
- orders.create_app(dataset_path: Path) -> FastAPI; GET /orders(page_size: int|None=None, cursor: int=0) -> {items:[{id:int}], next_cursor:int|null}.
- reporting.run() и billing.run() -> list[int]; reporting сначала делает один GET, billing обходит next_cursor.
- scenarios.build_version(destination: Path, version: ScenarioVersion) -> None.
- oracle.check_ids(actual: list[int]) -> dict с expected_count=250, actual_count, missing_ids, duplicate_ids, unexpected_ids, passed.

- [ ] Написать test_A_complete_B_loses_150_D_repairs и test_duplicate_count_does_not_pass: A Reporting/Billing дают IDs 1..250; B Reporting даёт 1..100, Billing 1..250; D Reporting снова полон; 250 повторений одного ID не проходят oracle.
- [ ] Запустить: python -m unittest tests.graph_demo.test_scenario -v. До реализации подтвердить целевое падение, не случайную ошибку окружения.
- [ ] Реализовать базовый API без лимита при page_size=None, версию B с default 100 и реальным срезом данных. Одинаковый dataset, фиксированные варианты source; D меняет только Reporting. Вызовы consumers соответствуют поддержанному literal/module-constant requests-профилю.
- [ ] Health вызывает Status, а не Orders; tests фиксируют это даже при одинаковом /orders. Добавить случай cursor вне диапазона и отказа API без молчаливого принятия частичных данных.
- [ ] Повторить unit-проверки и реальный HTTP-прогон в disposable Docker network: суммы/множества проверяются по исполнению, без подмены requests ответами.
- [ ] Закрепить runtime dependencies и commit: feat: add executable HTTP demo and independent collection checks.

### Task 2: Снимки, сессии и доверенная область

**Files:** Create contracts.py, snapshots.py, tests/graph_demo/test_snapshots.py.

**Interfaces:**
- create_session(root: Path, product_sha: str, profile: str) -> SessionRecord.
- materialize_version(root: Path, session_id: str, expected_revision: int, version: ScenarioVersion) -> tuple[SessionRecord, SnapshotManifest].
- build_policy(session_root: Path, manifest: SnapshotManifest, actor: Actor) -> agent_graph.contracts.Policy.
- applicable(receipt: CheckReceipt, session: SessionRecord, dataset_sha256: str) -> bool.

- [ ] Написать tests test_manifest_binds_every_source, test_late_receipt_is_historical, test_root_and_view_stable_A_to_E: изменение byte меняет digest; неправильный dataset/revision/running version не применимы; A/B/D/E используют одну policy область.
- [ ] Запустить python -m unittest tests.graph_demo.test_snapshots -v и подтвердить падение до реализации.
- [ ] Реализовать архив неизменяемых manifests и стабильные рабочие корни на сессию. Все materialize и graph executions используют один session lock. Экспорт/сброс не удаляет архив прежней сессии.
- [ ] Включить корни Orders/Reporting/Billing/Health/Status/Export без рёбер; Export изначально содержит лишь неисполняемый HTTP-запросов placeholder-модуль. Oracle, модельные секреты, deployment и generated receipts вне corpus.
- [ ] Требование полной коллекции из отдельного business.md включить в policy с точным digest и issuer. Не вычислять authority из текста source. Зафиксировать revision=source commit/manifest label и отдельный digest, не выдавая метку за Git attestation.
- [ ] Проверить symlink/path escape, изменение файлов во время materialize, несовпадение expected_revision и новый реальный repository root: конфликт/новая область, не ложное сравнение со старым контекстом.
- [ ] Повторить tests; commit: feat: add versioned demo snapshots and applicability rules.

### Task 3: Adapter к настоящему agent_graph CLI

**Files:** Create graph_cli.py, tests/graph_demo/test_graph_cli.py; reuse src/agent_graph/__main__.py без копирования extractor.

**Interfaces:**
- GraphCLI.execute(policy_path: Path, state_path: Path, action: str, *, context_id: str|None=None, input_path: Path|None=None, task: str="", deadline: float, cancel: threading.Event) -> dict.
- Разрешённые adapter actions: prepare_context, dependencies, evidence, analyze_change, investigate, propose, report_check. HTTP jobs доступны только для JobAction.

- [ ] Написать test_real_cli_detects_reporting_risk_and_status_decoy, test_new_export_call_is_discovered, test_profile_mismatch_is_error.
- [ ] Запустить python -m unittest tests.graph_demo.test_graph_cli -v; до реализации ожидается падение adapter, после — реальные JSON CLI subprocesses.
- [ ] Вызывать sys.executable -m agent_graph фиксированным argv, shell=False; policy/state только из серверного каталога сессии. input JSON создаётся сервером с проверенной схемой. stdout ограничить 2 MiB; stderr не передавать браузеру.
- [ ] Применить общий deadline 180 секунд и terminate/kill+wait дочернего process group при отмене; Windows и Linux cancellation реализовать средствами их subprocess API. Не «возвращать» зарезервированный бюджет и не обходить OS-lock модуля.
- [ ] Проверить invalid JSON, stdout overflow, зависший subprocess и ERROR exit=2: FAILED/PARTIAL с безопасным кодом, без traceback/headers/секретов; отсутствие модели — явный unavailable.
- [ ] Citation получать через evidence по сохранённому серверному ID; произвольные host paths не допускаются. Ошибку неподдержанной грамматики показывать как gap, не исправлять её незаметным альтернативным extractor.
- [ ] Повторить tests и существующие tests/graph; commit: feat: adapt demo to bounded graph CLI.

### Task 4: Устойчивая последовательная очередь

**Files:** Create store.py, worker.py, tests/graph_demo/test_jobs.py.

**Interfaces:**
- DemoStore.create_session(...)->SessionRecord; get_session(id)->SessionRecord.
- enqueue(session_id: str, expected_revision: int, action: JobAction, payload: dict, idempotency_key: str)->JobRecord.
- claim_next()->JobRecord|None; finish(job_id: str, result_ref: str|None, error_code: str|None, status: str)->JobRecord.
- recover_interrupted()->list[str]; reset_session(id: str, expected_revision: int)->SessionRecord.
- DemoWorker.run_once(cancel: threading.Event)->bool uses Task 3 adapter and Task 2 session lock.

- [ ] Написать test_same_key_same_body_returns_same_job, test_same_key_different_body_conflicts, test_one_running_four_waiting_then_busy.
- [ ] Запустить python -m unittest tests.graph_demo.test_jobs -v и подтвердить падение до реализации.
- [ ] Реализовать SQLite transactions и CAS по session revision. Очередь, jobs, transitions и refs артефактов постоянны; claim транзакционно разрешает один активный job в установке.
- [ ] Написать test_restart_marks_running_unknown_without_retry и test_old_job_after_reset_not_current. Реальный process restart должен сохранять историю и оставлять незавершённое UNKNOWN_AFTER_RESTART.
- [ ] На B фиксировать proposed manifest B при running A; смена runtime происходит только после привязанного receipt оператора. Нельзя обновлять running version из ответа модели/браузера.
- [ ] Повторить tests и записать commit: feat: persist serialized graph demo jobs and history.

### Task 5: API, серверные права и режим доступа

**Files:** Create api.py, auth.py, tests/graph_demo/test_api.py; Modify pyproject.toml только package-data; add backend launch config.

**Interfaces:**
- create_app(settings: DemoSettings)->FastAPI; lifespan создаёт один DemoWorker.
- DemoSettings: state_root: Path, cli_python: Path, allowed_origins: list[str], auth_config_path: Path, public_mode: bool=False; пути/секреты только server configuration.
- authenticate(request)->Actor; authorize_session(actor: Actor, session_id: str, write: bool)->None.
- Маршруты и HTTP-methods точно из спецификации §6; все session paths используют UUID, evidence — opaque server citation ID.

- [ ] Написать tests test_requires_auth, test_viewer_cannot_write, test_other_session_not_disclosed, test_origin_required_on_mutation, test_unknown_action_and_paths_rejected.
- [ ] Запустить python -m unittest tests.graph_demo.test_api -v, зафиксировать ожидаемые падения.
- [ ] Применить HTTP Basic для закрытого/малого demo с серверной operator/viewer конфигурацией, constant-time credential comparison и session grants. Конфигурация вне Git, браузер не выбирает роль или actor. В публичном режиме только HTTPS за доверенным Nginx; direct backend остаётся loopback.
- [ ] Реализовать POST jobs с 202/job ID; malformed=422, authentication=401, forbidden=403, stale/idempotency conflict=409, queue full=429. Не включать credentials/authorization в logs.
- [ ] GET graph/history читает сохранённые артефакты; не запускает implicit scan. Свежесть помечена временем последней оценки; явное обновление ставит job. Не смешивать безопасность read-only viewer с single trusted OS-user моделью.
- [ ] POST proposals: operator-only; схема/цитата/supersedes проходят настоящие проверки модуля. Исправление нормы не делается через UI boolean approve.
- [ ] Повторить tests; commit: feat: expose authenticated graph demo API.

### Task 6: Основной экран и проверяемый пользовательский путь

**Files:** Create web/index.html, app.js, styles.css; tests/graph_demo/browser_acceptance.py.

**Interfaces:**
- UI получает SessionRecord, JobRecord и сохранённый graph/evidence JSON через Task 5 API; отдельного browser graph store с «истиной» нет.
- uiRenderSession(session), uiRenderGraph(graph), uiRenderEvidence(citation), uiPollJob(jobId) в app.js; содержимое source вставляется textContent.
- Карта строится из nodes/edges результата: группировка сервис → операция → consumer, стабильная сортировка и SVG paths; зависимости не захардкожены.

- [ ] Написать browser journey test_open_risk_follow_evidence_and_history: выбрать B, запустить анализ, открыть Reporting и исходный фрагмент, увидеть proposed=B/running=A; после receipt B увидеть тестовый FAIL отдельно от graph risk.
- [ ] Запустить browser acceptance на реальном backend; до UI ожидается отсутствие конкретных controls/данных, не сетевой сбой тестового окружения.
- [ ] Реализовать один desktop экран: header состояния, карта слева, task/diff/findings в центре, evidence справа, история внизу; удобная типографика, русские подписи, legend, keyboard focus и текстовые статусы.
- [ ] Добавить test_script_in_source_rendered_as_text, test_partial_and_model_unavailable_visible, test_previous_revision_result_stays_historical. На width 390 экран остаётся читаемым через последовательное расположение панелей.
- [ ] Управление сценариями с mutating runtime не выдавать за команду агента. Показывать «ожидает действия оператора» до действительного запуска runner; scripted replay маркировать отдельно.
- [ ] Показывать кандидатов/конфликты и operator correction; после refresh видна STALE correction, а не безусловно подтверждённое знание.
- [ ] Сохранить screenshots основного сценария и ошибок, пройти journey глазами; commit: feat: add evidence-first graph demo UI.

### Task 7: Операторский runner и реальные результаты исполнения

**Files:** Create tools/agent_graph_demo/run_scenario.py, ingest_receipt.py; finish infra/agent_graph_demo/compose.yaml; tests/graph_demo/test_runner.py.

**Interfaces:**
- run_scenario.py --session ID --version A|B|D|E --check collection --output DIRECTORY.
- Compose project name вычисляется из проверенного session UUID с префиксом agent-graph-demo-; служебные пути только из operator config.
- run_check(session: SessionRecord, manifest: SnapshotManifest)->CheckReceipt.
- ingest_receipt.py --session ID --receipt PATH imports receipt into demo store and optionally calls graph report_check; сохраняет раздельную provenance.

- [ ] Написать test_receipt_for_wrong_runtime_or_dataset_is_historical, test_caller_cannot_choose_shell_or_compose_file, test_reset_preserves_other_project.
- [ ] Запустить python -m unittest tests.graph_demo.test_runner -v, подтвердить целевое падение.
- [ ] Реализовать фиксированный набор subprocess argv Compose и checks, без исполнения текста из UI/source. Доставленный manifest сверяется с реально запускаемым артефактом; receipt фиксирует startup/errors отдельно от semantic FAIL.
- [ ] Сделать реальный A→B→D→E прогон с requests через Docker-сеть. Проверить 250/100/250 Reporting, 250 Billing, отсутствие cross-service Health риска, новый Export edge.
- [ ] Runner выполняется оператором с sudo Docker вне web. Запись receipt не делает внешний тест внутренним PASS графа; подпись/attestation не заявляется. Импорт несовпадающего current revision не продвигает running state.
- [ ] Сброс переключает новую сессию в A и сохраняет предыдущие артефакты; cleanup ограничен точным disposable project. Не использовать глобальный docker prune или down -v существующего runtime.
- [ ] Commit: feat: run and record isolated HTTP demo scenarios.

### Task 8: Воспроизводимая приёмка и упаковка

**Files:** Create tools/agent_graph_demo/accept.py, .github/workflows/agent-graph-demo.yml, tests/graph_demo/test_acceptance.py; finish Dockerfile/requirements.lock/images.json; Modify core-tests.yml только для обязательного включения нового пакета в linter scope при необходимости.

**Interfaces:**
- accept.py --mode local --output DIRECTORY; запускает сценарий и browser journey, сохраняет manifest, checks, timings и screenshots.
- ACCEPTANCE.json: product_sha, extractor_profile, scenario_manifests, runtime_images, dataset_sha256, tests[], resources, model_mode, limitations; unknown/unrun остаются явными.

- [ ] Добавить tests для summarizer: наличие FAIL/ERROR/UNKNOWN не превращается в зелёную общую приёмку; настоящий ожидаемый broken-control FAIL отличается от непредвиденного провала.
- [ ] Запустить python -m unittest tests.graph_demo.test_acceptance -v; реализовать machine-readable report и независимый контроль.
- [ ] CI строит pinned образы вне ВМ и выполняет real HTTP + browser без платного inference и cloud secrets. Actions permissions=contents:read, отдельные disposable projects и finally-cleanup.
- [ ] Прогнать python -m unittest discover -s tests -v и python -m ruff check src services tools stand lab/app lab/product lab/runtime --select F401,F811,F841. Запустить accept.py по инструкции с установленным Playwright/Chromium. Не переиспользовать заявленное прежде число 480 как новый результат.
- [ ] Сверить Dockerfile/lockfile/image digests и package web assets; проверить, что oracle/receipts/deployment credentials исключены из model/graph sources.
- [ ] Commit: test: qualify reproducible HTTP graph demo and browser journey.

### Task 9: Закрытая установка на существующую ВМ

**Files:** infra/agent_graph_demo/agent-graph-demo.service, nginx.conf, README.md; docs/agent-graph-demo/RUNBOOK.md, ACCEPTANCE.md; host inventory report без секретов.

**Interfaces:**
- Версионная доставка в /opt/agent-graph-demo/releases/<accepted-sha>, state в /var/lib/agent-graph-demo; dedicated application UID/GID 10001.
- Один Compose-проект agent-graph-demo, backend bind 127.0.0.1:18081; SSH tunnel Windows local port 18081 к тому же remote loopback.
- Использовать только принятый точный SHA ядра и прошедшие Task 8 artifacts. Если PR №28 ещё не принят, завершить все независимые задачи и отчёт, deployment не выполнять.

- [ ] Проверить локальные Windows/SSH и sudo, актуальные RAM/disk/ports. Ключи/парольные фразы не выводить; успешный старый whoami не подменяет новую проверку.
- [ ] Сохранить Nginx config и старые systemd unit/start script с checksums. Зафиксировать ExecStart/Restart старой failed dmrp-ui.service. Если она всё ещё ожидает отсутствующий /opt/dmrp и мешает автозапуску, отключить именно её как обратимый шаг с записью команды восстановления; здоровый изменившийся runtime не трогать автоматически.
- [ ] Доставить готовые образы и код, сверить SHA/digests. Выдать приложению только собственные state/snapshots и server config; старый secrets.json не читать и не переиспользовать.
- [ ] Запустить отдельный Compose-проект с memory caps, cpu/log limits и restart policy; systemd восстанавливает именно этот проект. Проверить права и отсутствие Docker socket/sudo у web.
- [ ] Выполнить закрытую приёмку через SSH tunnel. Nginx конфигурацию проверять nginx -t перед reload; добавление public origin в этом шаге не требуется.
- [ ] Воспроизвести A→B→D→E/reset и отрицательный сценарий; записать реальные peak RAM/CPU, timings cold/warm, OOM counters, диск и log growth. Предел приложений до 2 GiB — цель проверки, не обещание до измерений.
- [ ] Проверить restart приложения/worker при незавершённом job, сохранность SQLite и startup служб. Для проверки полного reboot использовать согласованное окно демонстрационного стенда и сохранить открытый recovery-путь.
- [ ] Задокументировать остановку/rollback только нового проекта и восстановление Nginx. Backup делается с остановленным writer; проверить восстановление в отдельном disposable state.
- [ ] Commit sanitized deployment/acceptance report: docs: record closed VM demo acceptance.

### Task 10: Реальная модель и самостоятельный внешний просмотр

**Files:** extend deployment README, auth.py config и acceptance tests, docs/agent-graph-demo/RUNBOOK.md, ACCEPTANCE.md. Этот task содержит два явно независимых выпускаемых дополнения.

**Interfaces/inputs:**
- Модель: operator-approved ModelConfig с точными endpoint/model/configuration_id, route, allow_source_transfer и ненулевыми cost caps для corporate route; секрет — только server environment.
- Внешний просмотр: обязательный operator input DEMO_PUBLIC_HOST, проверяемый DNS на существующий адрес ВМ, HTTPS certificate и operator/viewer credentials/session grants. Если имени нет, Task 9 остаётся завершённым закрытым демо, внешняя доставка маркируется NOT_CONFIGURED.

- [ ] Для model path выполнить protocol/schema/tools/usage probe и реальный investigate на сценарии с заранее записанными ожиданиями. При отсутствии endpoint/лимита сохранить NOT_RUN; не включать CPU 0.6B или API fallback автоматически.
- [ ] Проверить ошибки/тайм-аут и бюджет на реальном provider; сохранить безопасные usage/time/results и ручную оценку смысла предложений. JSON validity сама по себе не качество.
- [ ] Для external path проверить hostname/DNS/доступность certificate issuance; использовать существующий Nginx на 80/443, не запускать конкурирующий proxy. Сначала nginx -t, затем reload и независимая проверка TLS.
- [ ] Выполнить browser tests: без входа 401, viewer не меняет jobs/proposals/reset, чужая сессия 403 без содержимого, mutating operator request требует разрешённый Origin. Пароли не попадают в URL, source, screenshot или logs.
- [ ] Проверить весь показ с отдельного браузера участника; loopback и внутренние сервисы недоступны публично. Для расширенного доступа operator работает своей отдельной учётной записью.
- [ ] Записать отдельно: model live measured/unrun; public delivery accepted/not configured; статус ядра, реальные ограничения и короткую запись показа. Не скрывать незавершённое за «демо готово».
- [ ] Commit: docs: qualify live model and protected external demo when configured.

## Контрольная карта спецификации

| Раздел спецификации | Реализация/проверка |
|---|---|
| §1–2 цель, ограничения, существующая ВМ | Global Constraints; Tasks 1, 8, 9 |
| §3 живой сценарий и контрольные случаи | Tasks 1, 2, 3, 7 |
| §4 UI, источники, история и correction | Tasks 5, 6 |
| §5 размещение и полномочия | Tasks 3, 5, 7, 9 |
| §6 API, очередь, отмена и ошибки | Tasks 3, 4, 5 |
| §7 versions, snapshots, receipts | Tasks 2, 4, 7 |
| §8 встроенная/внешняя модель и агент | Tasks 3, 6, 10; фактические действия внешнего coding agent фиксируются до плана и после diff |
| §9 ресурсы и этапы доступа | Tasks 8, 9, 10 |
| §10 вся приёмка | Tasks 1–10 и ACCEPTANCE.json |
| §11 отдельный PR и следующий пилот | Handoff ниже; диагностические v4/H1 не меняются |

## Execution handoff и результат

Этот план подготовлен и самопроверен, но ещё не исполнен. После просмотра плана владельцем продукта локальный Codex использует executing-plans и изолированную рабочую ветку/worktree; выбранный способ исполнения сохраняется.

1. Прочитать PR №29/spec/plan, актуальный PR №28 и AGENTS.md; проверить состояние локального дерева, не затирать чужие изменения.
2. Для независимых demo-файлов можно работать до окончания ревью ядра. Для интеграции использовать отдельный worktree/ветку от точного кандидата ядра, явно указав stacked base; main/ветку PR №28 не менять. После принятия ядра обновить основание и повторить релевантные проверки до deployment.
3. Создать отдельный draft implementation PR. Docs PR №29 может остаться отдельным; если он не слит, перенести согласованные документы отдельным commit с сохранением источника.
4. Выполнять task за task с проверяемыми checkpoint commits; найденное противоречие контракта исправлять явно с обоснованием, не подменять результат UI fixtures.
5. В итоговом отчёте дать accepted SHAs, PR/CI, команды, фактическую приёмку, адрес и способ доступа только при реально работающем показе, режим модели и ресурсы. Для каждого BLOCKED/NOT_RUN — конкретный недостающий input и следующую проверку.
6. Не сливать PR автоматически и не создавать новые платные cloud-ресурсы: данный объём использует существующую ВМ. Точный новый inference budget и отдельное изменение инфраструктуры готовятся для согласования, если потребуются.
