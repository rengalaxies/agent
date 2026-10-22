# HTTP graph demo: запуск и передача

Это приложение пачки 2, отдельное от исторического `ui/` и модельных экспериментов. Согласованная спецификация: [PR29, 778b766](https://github.com/rengalaxies/agent/pull/29). Начальное основание работы: `08a52704269c75d8d78a8fcf4ed8b9f10cf45722`.

Ядро уже принято в `main`: внешний read-only checkout **a9385c565d5471698da62987b226dcff4cbdea86**, профиль `http-requests-2`. Проверяются SHA-256 всех Python-файлов пакета по [core.lock.json](../../infra/agent_graph_demo/core.lock.json). Копии ядра в diff и Docker-образе приложения нет. Ветки пачки 1 не изменяются; PR35 и его реальные модельные результаты не участвуют в этом показе.

## Проверка в рабочей среде / CI

Python 3.12, Docker Engine + Compose, Chromium. Это команды для изолированной среды приёмки, не инструкция менять общую ВМ. Модельных ключей, cloud credentials и SSH не требуется.

```bash
# Рядом с checkout приложения: отдельная зависимость, не внутри его diff.
git clone --no-checkout https://github.com/rengalaxies/agent.git ../agent-graph-core
git -C ../agent-graph-core checkout --detach a9385c565d5471698da62987b226dcff4cbdea86
export DEMO_CORE_ROOT="$(realpath ../agent-graph-core)"
export PYTHONPATH=src:.
python -m pip install -r infra/agent_graph_demo/requirements.lock
python -m pip install httpx==0.28.1 playwright==1.62.0
python -m unittest discover -s tests/graph_demo -t . -v

# Сборка вне целевой ВМ: сеть нужна только для download/pull.
mkdir -p work/wheels
python -m pip download --only-binary=:all: --require-hashes \
  -r infra/agent_graph_demo/requirements.lock --dest work/wheels
export BUILDX_CONFIG="$PWD/work/buildx"
docker build --network=none -f infra/agent_graph_demo/Dockerfile \
  --build-arg PRODUCT_SHA="$(git rev-parse HEAD)" -t agent-graph-demo:accept .
# Docker должен быть выбран локальный; в managed Codex runner сам закрепляет unix socket.
DEMO_IMAGE_ID="$(docker image inspect agent-graph-demo:accept --format '{{.Id}}')"
python tools/agent_graph_demo/accept.py --mode local --core-root "$DEMO_CORE_ROOT" \
  --image "$DEMO_IMAGE_ID" --product-sha "$(git rev-parse HEAD)" --output work/acceptance
```

На GitHub предусмотрен отдельный `agent-graph-demo.yml`: pull_request, без model/cloud secrets, без `pull_request_target`, без платного inference. CI отдельно получает точный core pin. Публикуются только ACCEPTANCE.json, безопасные журналы проверок и реальные screenshots, **не** auth/config/SQLite/state.

`work/acceptance/ACCEPTANCE.json` фиксирует реальное выполнение. Ожидаемый FAIL версии B — предметный результат, а не провал инфраструктуры. `PARTIAL` статического анализа остаётся видимым. Повторная приёмка сохраняет историю; незавершённый UNKNOWN не восстанавливается автоматически. Для него требуется явный `reconcile` того же registry. Не удаляйте state ради «зелёного» повтора.

## Запуск приложения без Docker-полномочий

```bash
export PYTHONPATH=src:.
python tools/agent_graph_demo/configure.py --directory work/local-demo \
  --core-root "$DEMO_CORE_ROOT" --product-sha "$(git rev-parse HEAD)"
python -m agent_graph_demo --config work/local-demo/web.json
```

Открыть `http://127.0.0.1:18081/`, HTTP Basic, пользователь `operator`, пароль вводится при configure и не печатается. Это реальное приложение и CLI; runtime остаётся «не подтверждено», пока отдельный оператор не инициализирует registry и не запустит сервисы. В браузере нельзя выбрать executable, host path, URL или model policy.

Для operator runner создать **отдельный защищённый** JSON (пути — абсолютные):

```json
{
  "state_root": "/var/lib/agent-graph-demo/state",
  "runtime_root": "/var/lib/agent-graph-demo/runtime",
  "product_sha": "EXACT_TESTED_PRODUCT_SHA",
  "image": "sha256:EXACT_LOCAL_IMAGE_ID_OR_REPOSITORY_AT_DIGEST"
}
```

`image` принимает только `sha256:<64 hex>` либо `repository@sha256:<64 hex>`. Это шаблон конфигурации; текстовые placeholders не являются рабочими digest. Проверяется label `agent-graph-demo.product`. Полное имя конфигурации — `/etc/agent-graph-demo/operator.json` в командах UI; заменить его только в операторском запуске, не через браузер.

```bash
# Первый запуск: registry отсутствует, generation=0; сверяется отсутствие собственных sandbox.
python tools/agent_graph_demo/run_scenario.py --config /etc/agent-graph-demo/operator.json \
  reconcile --expected-generation 0
# UI показывает session и текущую generation в диагностике/инструкции.
python tools/agent_graph_demo/run_scenario.py --config /etc/agent-graph-demo/operator.json \
  run --session SESSION_UUID --version A --expected-generation N \
  --check collection --output /var/lib/agent-graph-demo/receipts
python tools/agent_graph_demo/run_scenario.py --config /etc/agent-graph-demo/operator.json \
  stop --session SESSION_UUID --expected-generation N
```

После каждой команды generation меняется. Старый N даёт конфликт до Docker-мутации. `observe --expected-generation N` сверяет контейнеры/labels/image и освежает наблюдение. Наблюдение старше 120 секунд становится UNKNOWN в web. Оператор должен вызывать observe периодически (например, каждые 60 секунд, читая новый N); отсутствие такого обслуживания не выдаётся за работающий runtime. STARTING/UNKNOWN требует `reconcile --expected-generation N`; он останавливает только exact pinned project и не возрождает исторические окружения. Ошибка down блокирует новый up.

## Показ через UI

1. «Новый показ» → «Обследовать исходники»: реальные Billing/Reporting → Orders и Health → Status. Export разрешён, но пока без вызова.
2. Оператор запускает A; «Получить результаты» показывает полный набор 250/250.
3. «B · Лимит 100»: reserved job, затем опубликован B; running остаётся A. Открыть Reporting → Orders, точный фрагмент и diff.
4. Оператор запускает B: независимый oracle показывает Reporting 100, пропуски 101…250, Billing 250. Это отдельный фактический FAIL, не вывод модели.
5. «D · Исправить Reporting» применяет фиксированное известное исправление сценария, не автономную правку LLM. Оператор запускает D: Reporting снова 250.
6. «E · Добавить Export»: CLI обнаруживает новый callsite в прежнем разрешённом root; операторская проверка Export получает все 250.
7. Открыть прежний анализ B в истории: историческое основание не меняет текущий кандидат. Human correction доступна с текущим evidence, capability correct и supersedes; она не меняет техническое ребро или утверждённое требование.
8. Reset: сначала операторский stop, затем UI «Сбросить после остановки». При UNKNOWN/активном sandbox сброс отклоняется; прежняя история сохраняется.

Модельный режим недоступен в этой пачке. Нет scripted модельных replies. Импорт через `ingest_receipt.py` хранится как отдельный внешний отчёт `EXTERNAL_REPORTED`, не как локальная проверка или свидетельство running.

## Совместимость и границы

- Используются обычные CLI `prepare_context`, `dependencies`, `analyze_change`, `evidence`, `propose`. Нет прямого чтения/изменения private core SQLite или альтернативного extractor.
- API допускает task до 4000; текущий core prepare ограничен 2000: адаптер явно отклоняет превышение, не обрезает текст. CLI analyze использует task базового контекста; выбранная задача сохраняется в журнале web, не передаётся как неподдержанный флаг.
- Точный текст citation для UI получает core evidence. Исторические строки delta разрешаются через опубликованный base context, а не через текущий изменившийся source.
- При failed/cancelled/recovered job файлы восстанавливаются до снятия reservation. Если core успел создать новый immutable head, он не перематывается: опубликованный результат остаётся прежним, freshness становится UNKNOWN, требуется явный refresh перед correction. Поздний ответ не публикуется.
- В принятом core FastAPI decorators дополнительно дают `unknown_http_client`: статическое покрытие PARTIAL. Это не маскируется и не исправляется в чужом ядре.
- Синтаксический cursor loop не доказывает семантическую полноту. Oracle проверяет runtime независимо; UNKNOWN и EXTERNAL_REPORTED не означают PASS/допуск к выпуску.
- Backend: один процесс uvicorn, один durable worker, SQLite отдельно от core store; root-runner обращается к web SQLite только через фиксированный helper под UID 10001 (иначе root-owned WAL блокирует приложение); один RUNNING и максимум четыре QUEUED. Deadline выполнения 180 секунд; stdout CLI 2 MiB, stderr наружу не передаётся, process group terminate/kill+wait.
- Advisory corpus: до 256 файлов, 64 KiB/file, 2 MB total, scan 15 секунд, freshness 3600 секунд, evidence максимум 60 строк — core policy defaults закреплённого pin.

## Исходный handoff развёртыванию (выполнен 22 октября 2026)

Этот раздел описывает исходный handoff приложения. Последующая закрытая установка
на существующую dm-p1-ui выполнена 22 октября 2026:
[точные SHA/digest, целевая приёмка, SSH tunnel, показ и откат](deployments/2026-10-22/README.md).

Цель: Ubuntu 24.04 / 2 vCPU / 4 GiB. Не меняли общую ВМ, старую dmrp-ui.service, Nginx, secrets/vars. Сборка off-VM, перенос неизменяемого image и отдельного read-only core pin. Основной Compose: [compose.yaml](../../infra/agent_graph_demo/compose.yaml), systemd и Nginx fragment рядом.

1. Повторно обследовать фактические процессы/порты/старые unit; сохранить конфигурацию и журналы. Не запускать старую службу ради нового демо.
2. Установить exact release в `/opt/agent-graph-demo/releases/<SHA>`, core checkout отдельно. Указать DEMO_IMAGE и DEMO_CORE_ROOT в защищённом release.env; image только digest. Сборок на ВМ нет.
3. State `/var/lib/agent-graph-demo/state`: владелец 10001:10001, 0700. Один общий workload.lock на этом же host path для web и operator. Runtime `/var/lib/agent-graph-demo/runtime`: root:10001 0750, active.json root:10001 0640; web получает read-only mount. Нужен общий рабочий lockfile, не копия в другом volume.
4. `/etc/agent-graph-demo/web.json` должен содержать контейнерные пути `/var/lib/agent-graph-demo/state`, `/core`, `/etc/demo/auth.json`, `/var/lib/agent-graph-demo/runtime/active.json`; core hash проверяется при старте. checkout ядра/релиза должен быть читаемым UID 10001 (каталоги 0755, исходники 0644, без выдачи прав записи); auth.json 0640 root:10001; operator.json 0600 root. Не помещать credentials в git, образ, URL, логи и отчёт.
5. Web UID/GID 10001, root filesystem read-only, cap_drop ALL, no-new-privileges, без Docker socket/group, sudo, SSH и cloud keys. Публикация только 127.0.0.1:18081. Sandbox внутренний, без ports, restart=no, memory/pid/log caps; до нового up прежний exact project down без -v.
6. Подтвердить stop/reconcile/observe, пять показов, сохранность SQLite/истории после рестарта backend и Docker, работу независимого контрольного проекта. Измерить реальные peak RAM/CPU, cold/warm durations, OOM, disk/log growth на целевой ВМ. Запланировать retention после экспорта, не удалять историю автоматически.
7. Самостоятельный внешний доступ: **NOT_CONFIGURED**. Нужны утверждённые hostname/DNS/TLS и allowed_origins https; до этого только локальный операторский просмотр. Nginx fragment не является готовым публичным HTTP vhost. Viewer задаётся только server auth config, с конкретными allowed_session_ids.

Точные локальные результаты и оставшиеся проверки — в [ACCEPTANCE.md](ACCEPTANCE.md). При изменении ядра обновить lock отдельным совместимостным изменением, выполнить CLI/API/browser suites; не принимать несовпадающий hash автоматически.

## Закрытая поставка immutable image

После приёмки и merge приложения можно вручную запустить `agent-graph-demo-delivery.yml`
на main с `expected_main_sha=<полный проверенный SHA>`. Workflow не развёртывает
приложение и не получает cloud/model/SSH secrets. Он собирает образ вне ВМ,
сверяет `/app` с разрешёнными Git-файлами, non-root/env, filenames/credential patterns
во всех image layers и соответствие config digest архива проверенному image ID.
Это статическая проверка упаковки, не общая сертификация безопасности base image.

Artifact `graph-demo-delivery-<SHA>` хранится **1 день**: image archive, разрешённые
source/core archives, hash-locked wheels, image-audit.json и SHA256SUMS. Сначала
проверить SHA256SUMS и audit PASS, затем передать файлы существующим SSH/SCP.
На ВМ только load image и установка готовых wheels, без Docker build. Digest,
checksum, резервная копия конфигураций, фактические проверки ВМ и rollback должны
быть закреплены отдельным отчётом установки; CI не заменяет эту приёмку.
