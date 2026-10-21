# Новый эксперимент evidence-refs-v2: runner готов, модельный запуск NOT_RUN

`plan.json` и manifest фиксируют одинаковые protocol/schema/system/task, corpus,
параметры и критерии для Qwen/Qwen3-Coder-Next и openai/gpt-oss-120b. Различаются
только модель/configuration ID и изолированные context/session IDs. Case order:
Reporting Qwen/GPT, Export Qwen/GPT, Status Qwen/GPT, строго последовательно.
Фиксированный протокол требует прочитать **все** listed sources полностью до первого
предложения, включая decoy; evaluator проверяет это отдельно от sufficiency ядра.
Никаких coaching, retries, исправления quotes, продолжения старых диалогов или
native tool_calls. Положительные офлайн-тесты явно scripted, не модельные результаты.

Корпус скопирован побайтно из сохранённых синтетических snapshots PR №31.
Manifest включает SHA256 corpus, ядра, runner/harness и oracle. `oracle.json`
читает только evaluator; его содержимое, ожидаемые связи и parser dependencies
не передаются модели. Исторические 21 попытка входят в ledger для затрат, но
результаты/score новой серии вычисляются только из её собственных действий.

## Условия и сроки

Strict JSON evidence-refs-v2; temperature 0; stream false;
`max_completion_tokens=4096`; context 131072; prompt ≤60000 bytes;
до 5 запросов/шагов и до 60 строк на чтение, одинаково для каждой модели.
Пять шагов позволяют read/read/read/propose/finish для Status, четыре — для
Reporting/Export. Нет адаптивной смены prompt, параметров или token field.

Абсолютный deadline серии — 2100 секунд (6 × 300 плюс 300 на setup), investigation
— 300 секунд. В Actions серия начинается с `created_at` execute run: очередь,
установка зависимостей и другие ожидания уже расходуют время. Case deadline
сохраняется **до** подготовки контекста; фактический HTTP timeout равен минимуму
60 секунд и остатка обоих абсолютных сроков. Transport проверяет deadline на
DNS/connect/TLS/send/headers/body; после ответа и перед записью кандидата срок
проверяется снова. Monotonic clock дополняет wall clock внутри процесса.
Инициализация ledger — отдельный шаг без моделей, до начала серии.

Продолжать interrupted process запрещено. Сессионные evidence references нельзя
восстановить предъявлением ID; скрытый replay/новая сессия изменили бы условия.
Повторный `execute`/rerun не сбрасывает deadline или счётчик, а завершается отказом.
Даже корректный поздний ответ не допускается как новый кандидат. При истечении
срока ledger сохраняет terminal status; rollback часов не открывает окно заново.

## Устойчивый ledger и бюджет

`tools/evidence_refs_ledger.py` хранит единый JSON ledger в **отдельной фиксированной**
ветке `experiment-state/evidence-refs-v2` репозитория. Это не ветки PR №28/32.
`initialize` может создать её ровно один раз с явно заданными новыми request/money
caps, source SHA и manifest digest. `execute` не создаёт отсутствующий ledger.
Каждая запись — immutable Git commit; non-force update ref с parent старого head
даёт compare-and-swap: конфликт/неизвестный результат записи останавливает runner.
Нет fallback на новый файл, ветку, experiment ID или обнулённый ledger.

До каждого модельного запроса расход резервируется в общем Git ledger **и**
существующем Store ядра. Неуспешный/timeout/invalid-schema запрос не возвращает
резерв; неизвестные HTTP/usage остаются null. Активный transport сохраняет
worker-owned finalizer и OS-lock ядра. Повторный процесс не может reclaim начатую
серию. Если Actions принудительно оборван до upload, durable reservation остаётся
в ветке как unknown; нельзя автоматически rerun ради получения ответа.

`new_request_count` означает число консервативно зарезервированных попыток, включая
возможный отказ до фактической отправки. `historical_requests` сохраняет исходные
21 записи, а новые IDs начинаются с 22. Отдельные observed usage sums и unknown
counts не подменяют неизвестное нулём. Billing остаётся NOT_MEASURED.

Рекомендуемый минимальный практический лимит — **30 новых попыток**, по 5 на каждую
из 6 пар. Теоретический минимум без запаса — **26 = 2 × (4 + 4 + 5)**; это подтверждён
только scripted офлайн-тестом, не гарантирован для моделей. Lifetime counts при
этом максимум 51 (или 47 при ровно 26 новых). Старое разрешение 40 автоматически
не расширяется. Параметры initialize задаст владелец отдельно; default caps=0
не разрешают запуск. Покрытие грантом уже подтверждено владельцем и не запрашивается
повторно.

Денежный резерв — консервативный верхний rate 244 RUB/миллион токенов для input и
output обеих моделей, фиксированный в plan. Попытка резервирует byte/token upper bound фактических messages + schema + 4096
framing + 4096 output. Его максимум:
`(60000+4096+4096) × 244 / 1000000 = 16.638848 RUB`, для 30 максимальных prompts —
499.165440 RUB; обычный резерв меньше и фиксируется перед отправкой.
Это guard bound, **не** оценка ожидаемого расхода и не фактический счёт. Более низкий
заданный money cap может остановить серию раньше request cap. Исторический расход
показывается отдельно по сохранённому observed usage; unknown request №15 остаётся
unknown и не списывается повторно из нового разрешения.

## Запуск после отдельной команды владельца и интеграции

Ничего из следующего при подготовке не выполнялось. Новый workflow
`cloudru-evidence-refs-v2.yml` имеет **только workflow_dispatch**, работает с принятым
`main`, проверяет exact expected SHA и run_attempt=1. Он не принимает PR/ref кода,
не использует pull_request_target и не выдаёт секрет недоверенному PR. Initialize
не получает Foundation secret; execute получает только CLOUDRU_FOUNDATION_API_KEY
штатно через env. GH_TOKEN — обычный github.token для записи accounting branch.
Нет infrastructure keys, SSH, VM, secrets/vars/settings API.

Workflow станет доступен для dispatch после интеграции в default branch. PR
не сливается автоматически. После интеграции подставить **фактический принятый
main SHA**, совпадающий в обоих вызовах, и отдельно разрешённый денежный предел:

```bash
gh workflow run cloudru-evidence-refs-v2.yml --repo rengalaxies/agent --ref main \
  -f mode=initialize -f expected_main_sha=ACCEPTED_MAIN_SHA \
  -f new_request_cap=30 -f new_money_microrub=AUTHORIZED_NEW_LIMIT_MICRORUB

# После успешного initialize, отдельная команда на выполнение новой серии:
gh workflow run cloudru-evidence-refs-v2.yml --repo rengalaxies/agent --ref main \
  -f mode=execute -f expected_main_sha=ACCEPTED_MAIN_SHA
```

Эквивалентный runner CLI в уже подготовленной доверенной среде использует
`initialize --source-sha SHA --new-request-cap N --new-money-microrub M`, затем
`execute --source-sha SHA`. Source должен быть clean/pinned; env содержит стандартный
GH_TOKEN и при execute CLOUDRU_FOUNDATION_API_KEY. Это возможность для runner,
не требование настраивать пользователю ПК/CLI/SSH.

Отчёт/manifest загружаются по явному allowlist; private SQLite, headers, environment
и raw provider errors не сохраняются. Проверка secret canary блокирует попадание
значения credential и в Git ledger, и в artifact. Модель не видит GH token.

## Только офлайн сейчас

```bash
PYTHONPATH=src:. python -m unittest discover -s tests/graph -v
PYTHONPATH=src:. python tools/run_evidence_refs_experiment.py prepare --output work/manifest.json
```

Подлинность/авторизация/свежесть и sufficiency оцениваются раздельно. В ограниченном
static profile отсутствие поддержанного доказательства даёт INSUFFICIENT с
`dependency_absence=NOT_ESTABLISHED`, не доказанное отсутствие связи. Даже положительный
результат — UNAPPROVED_CANDIDATE, не verified runtime edge/release approval. Actions
success означает окончание сбора; итог качества — отдельные поля score каждого
нового случая. Исторические результаты не участвуют в новом score.
