# Следующий эксперимент: подготовлен, не запущен

`plan.json` фиксирует одинаковые protocol/schema/system/task, синтетический корпус,
порядок, параметры и критерии для Qwen/Qwen3-Coder-Next и openai/gpt-oss-120b.
Manifest дополнительно фиксирует SHA256 каждого source, файлов ядра, harness и oracle.
Различается только имя модели; контекст, сессия и история у каждой пары новые.
Нет диагностических подсказок, исправлений prompt между моделями, автоматических
повторов и продолжения старых диалогов. Тестовые corpus из PR №31 читаются побайтно;
`oracle.json` отделён от model-visible payload, его содержимое модели не передаётся.

Шесть investigations последовательно: Reporting Qwen/GPT, Export Qwen/GPT,
Status Qwen/GPT. Строгий JSON evidence-refs-v2, temperature 0, stream false,
max_completion_tokens 4096, context 131072, prompt 60000 bytes, до 6 шагов/запросов,
до 60 строк чтения. Native tool calling/reasoning_effort не используются.

Один **непрерывный** deadline серии 1800 секунд и по 300 секунд на investigation;
обе абсолютные даты сохраняются до первого запроса. Effective request deadline —
минимум этих дат и 60 секунд. Нельзя вычитать ручные паузы, продлевать окно после
restart или принимать поздний ответ. Единый durable ledger должен резервировать
каждую попытку до отправки; timeout/unknown usage не возвращают резерв. Token/cost
reserves существующего Store действуют дополнительно, а не заменяются счётчиком.

`RehearsalLedger` в `tools/prepare_evidence_refs_experiment.py` — **офлайн-прототип**
общего счётчика и абсолютных дат; его тесты используют искусственные часы. Он хранит
21 историческую попытку PR №31 (включая unknown timeout) и отдельные `SIMULATED`
записи. Он не отправляет HTTP и не является live runner. Ни код `--live`, ни workflow
с секретом сюда не добавлены.

В proposal бюджета указано 36 новых попыток, то есть lifetime ceiling 57 с уже
потраченными 21. Это **предложение**, не увеличение прежнего разрешения 40 и не
разрешение потратить оставшиеся 19. Денежный лимит и применимость гранта к новому
эксперименту пока не зафиксированы; нужен отдельный следующий запуск по явной
команде владельца. Историческая стоимость остаётся NOT_MEASURED, unknown usage не 0.

До будущего live нужно отдельно реализовать/проверить runner с распространением
общего deadline в transport **и** admission, импортом durable budgets и ledger,
зафиксировать новый SHA и денежный cap. Здесь ChatModel транспорта PR №28 продолжает
использовать `max_tokens` и request-only deadline; его нельзя выдать за готовый
runner этого плана. Cloud.ru adapter должен явно использовать документированный
`max_completion_tokens`, одинаково для обеих моделей. Закрытый runner PR №31 нельзя
переоткрывать или использовать для этой серии.

Оценки записываются отдельно: HTTP/usage, action protocol/finish, provenance,
sufficiency, held-out quality (включая отвергнутые ложные claims). Общий PASS требует
всех критериев; Actions success и отсутствие принятых ложных связей сами по себе не
доказывают успех модели. Это малая синтетическая серия, не сравнительный benchmark.

Только офлайн:

```bash
PYTHONPATH=src:. python -m unittest discover -s tests/graph -v
PYTHONPATH=src:. python tools/prepare_evidence_refs_experiment.py --output work/evidence-refs-v2-manifest.json
```

Workflow `graph-evidence-refs.yml` выполняет эти проверки и сохраняет только manifest,
без секретов, live шага и выполнения кода PR с секретами. Исторические reports и
искусственные positive tests не выдаются за результаты нового эксперимента.
