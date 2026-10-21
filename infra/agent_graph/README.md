# Локальная конфигурация inference

Это подготовленный кандидат для квалификации, не проверенная GPU-поставка.
Референс: Qwen3-Coder-30B-A3B-Instruct BF16, закрепленный revision в
[local-reference.json](local-reference.json), vLLM 0.15.1, контекст 16 384,
один запрос. FP8 остается отдельным кандидатом сравнения качества.

1. В разрешенной зоне подготовки загрузить официальный snapshot указанного
   revision, включая tokenizer/chat template, LICENSE и все shards. Например,
   `hf download Qwen/Qwen3-Coder-30B-A3B-Instruct --revision b2cff646eb4bb1d68355c01b18ae02e7cf42d120 --local-dir /approved/weights`.
   Сверить происхождение и хеши в принятом процессе организации. Это загрузка
   весов, не часть обычного анализа исходников; здесь она не выполнялась.
2. Импортировать образ `vllm/vllm-openai:v0.15.1`, проверить и закрепить digest.
   Реальный digest еще не получен; `latest` не допускается. Убедиться, что
   UID 10001 может читать веса. Нет `trust_remote_code` или mount Docker socket.
3. Оператор создает сеть: `docker network create --internal graph-inference-internal`.
   Подготовить план командой ниже. Без `--launch` контейнер не запускается.

```bash
python infra/agent_graph/serve_local.py \
  --weights /approved/weights \
  --image 'vllm/vllm-openai:v0.15.1@sha256:REPLACE_WITH_REVIEWED_DIGEST' \
  --output /approved/qualification-plan.json
```

После проверки плана повторить с реальным digest и `--launch`.
План хеширует все локальные веса; это затратная проверка, не запрос графа.
Ограничения: конкретный GPU/driver/CUDA, импорт образа, его транзитивные
зависимости, права UID, запуск в internal network и readiness еще не испытаны.
Если ограничения контейнера мешают запуску, фиксировать причину; не заменять
их автоматически privileged/host network. Измерить пик VRAM, RAM, cold start,
latency, ошибки и качество на одинаковом корпусе. Записать digest образа,
хеши весов, версии GPU driver и фактическую конфигурацию рядом с результатами.

```bash
PYTHONPATH=src python examples/agent_graph/evaluate.py \
  --live --model-config infra/agent_graph/local-model-config.json \
  --state /approved/graph-eval-state --output /approved/qwen30-raw-results.json
```

Каталог state создается модулем с 0700 либо заранее оператором с такими правами.
Единый бюджет установки: до 2,5 млн консервативных token units на всю серию;
до 196 608 на случай, до 12 шагов, один активный запрос. Нулевая ставка
относится к локальному учету tokens; часы GPU оплачиваются и ограничиваются
отдельно. Команда live может потреблять оплаченные вычисления; ее запуск
требует выделенного ресурса и согласованного бюджета. В этой ревизии не запускалась.

Если у клиента уже есть LLM-сервис, этот контейнер не нужен: оператор добавляет
в policy проверенный `ModelConfig` с точным HTTPS endpoint, allowlist,
именем переменной секрета, `route=corporate`, разрешением передачи данных,
максимальной ставкой и денежными/токенными лимитами. Сначала пройти
транспорт/схему и эту компонентную серию, затем независимую оценку ответов.
Отсутствующая поддержка `json_schema`, usage или finish_reason означает
неподдержанную конфигурацию; скрытого fallback на текстовый режим нет.

Код графа не использует embeddings, live connectors, трассировку или телеметрию.
Сервер запускается offline с выключенными usage stats; это нужно дополнительно
проверить сетевым наблюдением после запуска. Корпоративный gateway и внешний
coding agent имеют собственные маршруты данных: локальность графа их не меняет.
