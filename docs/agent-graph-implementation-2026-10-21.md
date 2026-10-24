# Исполняемый HTTP-граф: реализация, модель, ресурсы и границы проверки

21 октября 2026. Продолжение PR №28, исходный HEAD `55c55c88d85e71eda640ab35e5d376519959a448`.
Основание: решения §1.1-1.2 [главного документа](useful-graph-open-questions-2026-10-21.md)
и архитектура v4. Это техническая реализация ограниченного этапа и план
квалификации модели. Эффективность продукта, спрос и готовая GPU-поставка
не установлены. Полноценный аудит безопасности не проводился.

## 1. Выбранный этап и порядок работы

Основной пользователь - coding agent с разработчиком. Специализированный
встроенный агент сопровождает знания и не получает права менять код.
Исполняемый этап: четыре offline-корня Python, поиск HTTP requests без готовых
ребер, versioned context до планирования, сравнение base/head после правки,
предложения знаний и внешние отчеты проверок. Обновление только по запросу.

Порядок выполненной работы: сверка PR/документов/кода -> закрытая грамматика и
контракты -> bounded collector/SQLite/CLI -> модельный transport и цикл
read/propose/finish -> отрицательные проверки -> компонентная серия ->
модель ресурсов и инструкция квалификации. Изменения сохраняются в ветке PR;
merge и production-действия не выполняются.

Явное расширение относительно v4: запись кандидатов/исправлений и внешних
наблюдений, ограниченный модельный цикл и устойчивые лимиты установки. Это
необходимая реализация принятого встроенного сопровождения. Не добавлены
daemon, scheduler, HTTP-сервис, MCP, RabbitMQ-профиль, live collectors и UI.

| Существующий контур | Что проверено и переиспользовано | Почему не объединен |
|---|---|---|
| knowledge-1 / `project_evidence_graph` | Модель provenance, immutable snapshots, разделение нормы/наблюдения | Проекция зарегистрированных записей; неизвестных HTTP consumers не ищет. Ее authority/release semantics не подходят advisory-процессу |
| change_completion | Изучены scoped control plane и HTTP provider, отказ от redirect/implicit egress | Другая задача: подготовка SQL-патчей и разрешение эффектов. Нужен контекст, не executor |
| lab | Изучены `runtime/core.py`, `product/worker.py`, ограниченные model calls | Привязан к SQL/RabbitMQ-сценарию, Cloud.ru и собственному UI/state; общий inference service не доказан |
| Новый `agent_graph` | Отдельный небольшой пакет, существующая зависимость pydantic | Свои advisory-контракты; исследовательские режимы и результаты не меняются |

## 2. Фактический рабочий цикл и контракты

[Код](../src/agent_graph) · [CLI и пример](../examples/agent_graph/README.md) ·
[JSON Schema](../schemas/agent-graph-1.json).

1. Оператор задает policy вне corpus: установка/среда, субъект, capabilities,
   корни и include patterns, revisions, address -> service, approved digests,
   лимиты и отдельно разрешенный inference endpoint. Готовых dependencies нет.
2. Collector без import/exec/network читает разрешенные файлы, фиксирует digest
   bytes и inventory. AST извлекает закрытый HTTP-профиль, код/контракт
   поставщика и синтаксические признаки использования. Политика, текст заметки,
   тест и вывод модели сохраняют разные виды доверия.
3. Двойная сверка источников и CAS generation публикуют новую immutable версию.
   В контексте есть основания, approved requirements, candidates, conflicts,
   gaps, coverage. Полнота внутри профиля не равна полноте компании.
4. Необязательный `investigate` дает модели каталог разрешенных источников и
   пробелы. Модель запрашивает фрагмент, предлагает записи с точными цитатами
   либо завершает работу. Парсеры обслуживают формальную часть; модель может
   исследовать неоднозначное, но сохраняет его кандидатами.
5. Coding agent получает dependencies/requirements/evidence через JSON CLI,
   планирует и правит свой код самостоятельно. После diff `analyze_change`
   сравнивает прошлый контекст с текущими bytes и повторно обследует весь
   разрешенный corpus, включая ранее нерелевантные файлы.
6. Выход: условное влияние с callsite, обеими сторонами оснований, требованием
   при наличии и рекомендуемой проверкой. Черновик не отправляется. Внешний
   отчет о тесте - `EXTERNAL_REPORTED`, не удостоверенный модулем PASS.

Transport выбран CLI, потому что рабочая среда разработчика уже может запускать
локальный subprocess. Python API использует те же модели. JSON сообщения
валидируются pydantic; traceback и provider response body не возвращаются.
HTTP/MCP потребовали бы отдельной аутентификации, жизненного цикла сервиса и
сетевых границ без необходимости для этого этапа. Совместимость с конкретным
корпоративным агентом еще проверяется внешней командой.

Identity операции = installation/environment/service/method/path template.
Source ID включает repository/revision/path/digest. Scope view зависит от read
grants, адресов и trust configuration; смена read grants не дает прочитать
прежние сводки через интерфейс. Это один доверенный OS-пользователь, не SSO.
Policy не принимается из сообщения модели; субъект записи определяется policy.

Существующие approved requirements импортируются по digest и точным selectors
операции/consumer. Произвольные selector expressions, сложное наследование норм,
CODEOWNERS-resolution и собственное согласование не реализованы. Конфликт двух
поддержанных predicates одного consumer не выбирает победителя.

Запись предложения проверяет schema, scope, текущий corpus basis, актуальный
head и точную цитату. Дубли идемпотентны; противоречащие предложения сохраняются.
Human correction требует capability `correct`, может явно supersede запись
того же key и сохраняется в overlay после пересборки. При изменении basis
исправление становится STALE, а не теряется или автоматически переподтверждается.
Оно не заменяет наблюдение парсера/норму без изменения trusted source.
После R1-R7 идентичность предложения не включает context_id: при неизменном
basis/actor/origin возвращается первая публикация, включая прежний ID из
существующего SQLite. Лимит относится к активным записям текущего basis,
история не учитывается. Проверка supersedes, лимита и вставка выполняются
одной транзакцией; разрешенная замена сохраняет слот. Свежесть предложения
проверяется относительно текущего корпуса и TTL запрошенного контекста,
а не только равенством двух сохраненных basis; неудача сверки дает UNKNOWN.

Уточнение аудита архитектуры 22.10.2026 ([DOC-DRIFT](audits/architecture/DOC-DRIFT.md), D6-D7):
basis предложения относится ко всему корпусу, поэтому правка любого файла делает
исправление STALE, даже если процитированные файлы не менялись. Исправления
хранятся в пределах `view_id`; добавление репозитория, адреса или требования
меняет view, и прежние исправления перестают выдаваться.

Свежесть отдельно учитывает digest/inventory и возраст контекста. CURRENT -
сверка на момент запроса, не атомарный snapshot организации. При неизменных
bytes новый контекст может переиспользовать кандидатов; два прохода collector
сами по себе не доказывают отсутствие ABA-гонки. Для воспроизводимого анализа
предпочтительны immutable snapshots. Каждый prepare пока пересчитывает полный
корпус, а freshness перечитывает bytes; инкрементальный extractor еще не готов.

## 3. Модель и inference: принятое техническое решение

**Референс для первого замера: Qwen3-Coder-30B-A3B-Instruct BF16 + vLLM 0.15.1,
16k context, concurrency 1.** Это выбранный кандидат, не квалифицированная
поддерживаемая модель. У него меньше полный объем весов и проще первый стенд,
чем у Next. Первым вариантом клиента остается уже одобренный корпоративный
LLM-сервис, если он проходит наш протокол; вторую модель тогда не устанавливаем.

| Кандидат | Первичные свойства | Пригодность и решение |
|---|---|---|
| Qwen3-Coder-30B-A3B-Instruct | 30,5B total / 3,3B active, 262144 native context, Apache-2.0; инструменты заявлены авторами | Референс BF16. Закреплен model revision; ограничиваем рабочий context до 16384. Качество поиска связей еще не измерено |
| Официальный FP8 того же Qwen | Quantized weights; отдельный опубликованный snapshot | Оптимизация для кандидата 48GB, только после сравнения с BF16. Меньше память не означает сохраненное качество |
| Qwen3-Coder-Next | 80B / 3B, hybrid attention/DeltaNet, Apache-2.0, 256k; vLLM >=0.15.0 | Следующий кандидат сравнения при бюджете; 80B необходимо хранить целиком. Native tooling benchmark не доказывает наши задачи |
| DeepSeek-V3.2 open weights | MIT, FP8, другой serving/cache stack | Локально слишком тяжелый первый референс. Возможен корпоративный endpoint; не предполагаем, что публичный API сегодня обслуживает именно V3.2 |

По [актуальной документации DeepSeek](https://api-docs.deepseek.com/quick_start/pricing/)
публичный `deepseek-flash` сейчас относится к V4.1-Flash-1017; это отдельная
конфигурация, не замена измерению V3.2. JSON Output не тождественен нашему
обязательному `json_schema`; без успешной проверки конфигурация не поддержана.

Транспорт реализован без vendor SDK: exact Chat Completions endpoint, TLS для
corporate/HTTP только loopback, отдельная env-переменная секрета. Нет proxies
из environment, redirect, автоматического retry или смены endpoint. Формат
ответа - конечный JSON tool protocol `read_source/propose/finish`, не native
function calling произвольных tools. Это уменьшает набор обязательных
возможностей сервера; качество следования протоколу нужно измерить.

Возможности, требуемые от конфигурации: нестриминговый ответ, JSON Schema,
одна choice, finish_reason=stop, usage с входными/выходными tokens. Обрезанный,
отказной, некорректный или неизвестный tool response не применяется. Время,
bytes, строки tool, число шагов, запросы и общий бюджет ограничены. Единый
monotonic deadline и отмена охватывают DNS, TCP, TLS, send, headers и body;
медленные заголовки не продлевают общий срок. Поток запроса закрывает сокет
и освобождает installation OS-lock только после cleanup. Системный DNS lookup
нельзя принудительно остановить: клиент возвращает PARTIAL в срок, а незавершенный
lookup удерживает блокировку и не может затем отправить запрос. Отдельный
фоновый сервис не добавлен. Закрытие соединения не доказывает отмену генерации
или billing у провайдера.

SQLite резервирует расход **до** запроса; новая ревизия/run не сбрасывают бюджет
установки. Неизвестный исход/некорректный ответ расходуют полную резервацию.
Concurrency=1 проверяется OS-lock общей установки вместе с SQLite lease;
истекший lease не освобождает живого владельца. После crash OS освобождает lock,
durable lease истекает отдельно, деньги не возвращаются. Token units - консервативные bytes + schema/framing + max output,
а не измеренные tokenizer tokens. Для корпоративного маршрута обязательны
денежные лимиты и верхняя ставка; это защита клиента, не биллинг провайдера.
Если провайдер имеет дополнительные категории billing, их верхнюю границу
нужно включить в ставку либо отклонить конфигурацию.

[Локальная комплектация и команды](../infra/agent_graph/README.md) закрепляют
model revision, server version, context, telemetry/offline flags и container
restrictions. Image digest и транзитивное окружение еще нужно получить при
импорте; launcher требует reviewed digest и не скачивает веса/образ. Нельзя
называть этот набор готовой клиентской поставкой до GPU-квалификации.

## 4. Оборудование: расчет, не измерение

Все MoE-веса учитываются, а не только active parameters. Нижняя граница:
`weight_bytes = total_parameters * bits/8`. Она не включает scales, оставшиеся
BF16 tensors, tokenizer, allocator, activations, CUDA graphs и служебные буферы.

| Полный размер | BF16 floor, GiB | FP8 floor, GiB | 4bit floor, GiB |
|---|---:|---:|---:|
| Qwen 30,5B | 56,81 | 28,41 | 14,20 |
| Next 80B | 149,01 | 74,51 | 37,25 |
| DeepSeek checkpoint около 685B по model card | 1275,91 | 637,96 | 318,98 |

Для DeepSeek взят полный опубликованный checkpoint, а не только основной
671B backbone. Mixed precision и дополнительные tensors требуют проверки
реального index. У Qwen30 официальный [index](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct/resolve/b2cff646eb4bb1d68355c01b18ae02e7cf42d120/model.safetensors.index.json)
указывает 61064245248 bytes tensor data. Это metadata поставщика, не замер VRAM.

Для Qwen30 BF16 KV по [config](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct/blob/b2cff646eb4bb1d68355c01b18ae02e7cf42d120/config.json):
`2 * 48 layers * 4 KV heads * 128 dim * 2 bytes = 98304 bytes/token/sequence`.
16k -> 1,5GiB, 32k -> 3GiB, 256k -> 24GiB на последовательность.
Concurrency умножает cache; Next hybrid нельзя рассчитывать этой формулой.

Первый hardware-кандидат: A100 80GB, host 16 CPU/128GiB RAM, 200GiB SSD.
Расчет BF16: 56,81GiB weights + 1,5GiB KV + **допущение** 6-12GiB прочего
-> около 64-70GiB. Это объясняет выбор, но не подтверждает размещение.
FP8 кандидат L40S 48GB требует отдельной проверки kernels и численного качества.
24GB с 4bit и CPU offload не выбран первым стендом: потери качества и latency
пока неизвестны. Имеющиеся CPU-only ВМ 2CPU/2RAM модель не размещают.

Графовый процесс на наших крошечных fixtures не требует GPU. Для ограниченного
пилота предлагаем 2-4 CPU/4-8GiB RAM и 10GiB рабочего места **как резерв**,
не измеренную потребность. Default corpus ограничен 256 файлами / 2MB. Snapshot
хранит источники и историю: на 1000 полных версий 2MB корпус дает примерно
2GB текста до JSON/SQLite overhead. Нужны retention/backup по политике клиента;
автоматическая очистка истории не реализована. Embeddings отсутствуют.

## 5. Вычислительные затраты и кто платит

[Воспроизводимый расчет](../examples/agent_graph/cost_model.py) и
[его результат](../examples/agent_graph/reports/cost-estimates.json).
Цены проверены 21.10.2026 по первичным страницам; это не коммерческое предложение.

| Ориентир | Цена и единица | Источник / граница |
|---|---|---|
| Cloud.ru VM Intel, 30 vCPU/228GB, 2 x A100 80GB NVLink | 732 RUB/час с НДС, тариф 260909 | [Compute GPU](https://cloud.ru/documents/tariffs/evolution/evolution-compute-gpu); это VM целиком, не 366 RUB за доступный одиночный GPU |
| Cloud.ru ML Inference, 1 x A100 NVLink/16vCPU/256GB | 353,8 RUB/час с НДС, редакция 260918 | [ML Inference](https://cloud.ru/documents/tariffs/evolution/evolution-ml-inference); объем VRAM/образ/квоты нужно проверить; это не подтвержденная замена VM |
| Cloud.ru, reference Haiku 4.5 tokens | 196,42 / 982,10 RUB за 1M input/output, с НДС | [Foundation Models](https://cloud.ru/documents/tariffs/evolution/foundation-models), редакция 261015; пример тарифа, не квалифицированная модель этого модуля |
| DeepSeek Flash, peak / cache miss | 0,30 / 1,20 USD за 1M input/output | [Официальный тариф](https://api-docs.deepseek.com/quick_start/pricing/); для off-peak вдвое меньше; billing USD отдельно от RUB |

Нагрузка - **допущения**: 40k input/4k output на изменение, еще 20% на повторы;
начальное обследование и обновления отдельно заданы в script. Это суммарные
tokens нескольких запросов, не один запрос 40k в context 16k. Корпус и число
неоднозначных участков меняют фактический объем; parser не обязан отправлять
все файлы модели. Cache hits в оценке не учитываются.

| Изменений/месяц | Input/Output с cold+updates+retry, M | Reference tokens RUB | Reference Flash USD | Труд при допущениях, часы |
|---:|---:|---:|---:|---:|
| 100 | 5,4 / 0,54 | 1591,00 | 2,268 | 14,67 |
| 1000 | 51 / 5,1 | 15026,13 | 21,42 | 74,67 |
| 10000 | 494,4 / 49,44 | 145665,07 | 207,648 | 674,67 |

Модели в двух тарифных колонках разные и еще не испытаны. Сравнивать только
цену tokens и объявлять победителя нельзя. Доллары не переводились в рубли.
Труд: 8 часов подключения + 3 минуты review/задача + 10% ошибок по 10 минут;
это сценарий, не полученная экономия. При условной ставке 2000 RUB/час труд
на 100 изменениях стоит 29333 RUB, и может быть важнее inference.

Полная стоимость правильного результата:
`(compute + storage/network + setup + review + correction + maintenance + downtime)
 / independently_accepted_correct_results`.
Знаменатель и throughput пока не измерены; цену продукта из этой формулы не
назначаем. Нужно учитывать все попытки и failures, а не только успешные ответы.

| Поставка | Оплачивает | Обязательные компоненты расчета |
|---|---|---|
| Локально у клиента | Клиент - hardware/electricity/admin; продукт и внедрение отдельно | Purchase/amortization или rental, весь простой выделенного GPU, RAM/SSD/backup, maintenance, обновление, квалификация и review |
| Существующий корпоративный LLM | Клиент выделяет capacity/ключ/лимит; существующие GPU не бесплатны | Внутренняя стоимость requests или аллокации, очереди/SLA, quotas, клиентский graph host и труд |
| Вычисления предоставляем мы | Наш инфраструктурный счет; клиенту отдельно согласуется пакет/потребление | Compute+idle+isolation+support+retry reserve+оператор. Никакого безлимита |

VM 2 x A100: 8 часов = 5856 RUB, 730 часов = 534360 RUB без дополнительных
дисков/сети. Предложение отдельного эксперимента: 8h + условный резерв 1000 RUB
= 6856 RUB, **не разрешение расхода**. Свободный слот/квоты и срок оплаты не
подтверждены. Не запускать на весь месяц в рамках прежнего бюджета проекта.

Для выбора важны число изменений, объем неоднозначного текста, длина evidence,
доля повторного использования, concurrency/latency, доля ошибок и данные,
которые разрешено выносить. На низкой нагрузке существующий корпоративный
service предпочтителен для замера, если проходит качество/доступы. При росте
нагрузки считать measured utilization и сравнивать **одинаково правильные**
результаты. Сценарий 20% retries заменить 50%/100%, 16k context - 32k,
concurrency 1 - 2/4 отдельными измерениями до расширения размещения.

## 6. Что проверено, а что еще не измерено

[Компонентный протокол и результаты](../examples/agent_graph/reports/component-results.json)
построены разработчиком из синтетических fixtures, не независимым разметчиком.
12 cases здесь - **другая серия**, не диагностические 12 задач v4 и не E3.

Проверены: обнаружение без готового ребра; decoy адрес; page_size diff и
синтаксический cursor loop; различение approved source/заметки/теста; dynamic
call; исправление consumer; новый файл; недоступный источник; hostile note;
удаление consumer; конфликт норм; изменение approved digest. 12 boundary checks
проходят. В поддержанном профиле пропусков/FP нет на этих fixtures, но общее
число пропусков **2**: dynamic и unavailable consumer. UNKNOWN не записан в TP.
Ни эти результаты, ни mock не подтверждают качество реальной модели.

Unit/integration tests дополнительно проверяют scope/cached view, exact quote,
actor/approval spoofing, TTL, CAS, symlink и secret-pattern rejection,
дубли/конфликты/corrections, external check status, устойчивость бюджета после
restart/revision, единственный inflight, HTTP JSON Schema, redirect, partial
response, timeout/cancel и scrubbed errors. Локальный HTTP stub - транспортная
проверка; scripted replies - только проверка цикла и gate.

Фактические totals/версии/команды проверки сохраняются в
[validation.json](../examples/agent_graph/reports/validation.json).
Реальные LLM-вызовы: NOT_RUN. GPU peak/throughput: NOT_MEASURED.
Не настроены `GRAPH_LLM_ENDPOINT`/`GRAPH_LLM_API_KEY`, `nvidia-smi` отсутствует;
новый платный ресурс не создавался. Отсутствие этих переменных не доказывает
отсутствия вообще всех корпоративных ключей; другие доступы без бюджета не использовались.

Live harness сохраняет raw actions, версии, времена, usage и принятые кандидаты
для ручной слепой оценки. Он **не** считает семантически верным любой валидный
JSON/quote и не рассчитывает автоматически эффективность reasoning. Оценить
смысл proposals, tool selection, пропуски и ложные интерпретации должен
независимый review по заранее закрепленным задачам. Timeout/отказ входит в
знаменатель; переход к UNKNOWN на поддержанном случае не засчитывается.

### Отдельная диагностика v4: 12 задач, еще не проведена

Заранее зафиксировать независимые входы/expected findings/severity для 12
задач: cold discovery, decoy, page limit/single request, cursor use, explicit
page size, literal/template route, исправление consumer, новый callsite,
новый repository, dynamic/partial source, conflicting/changed norm и hostile
material. Не использовать учебный кейс как независимый oracle. Подписать
dataset/config/oracle digests до просмотра ответов; источник approved policies
закрепить отдельно от анализируемого diff.

Три варианта: действующие проверки, сильный корпоративный coding agent с поиском
и notes, тот же агент с модулем. Baseline получает те же исходники, инструменты,
доступы и возможность сохранять notes. Модуль не получает скрытые знания сверх
baseline. Артефакты вариантов изолированы; порядок чередуется по заранее
зафиксированному seed. Freeze не включает измененные после ошибки задания.

Для каждого случая собирать serious FN, FP, evidence correctness, выполненные
полезные действия, все retries/refusals, cold/warm active human minutes обеих
сторон, machine time/wait и tokens/billing. Холодное подключение и обслуживание
входят в сумму. Условия v4 сохраняются: serious FN не больше baseline,
`T_module <= 0.8*T_baseline`; одинаково плохой результат не проходит.
12 диагностических задач не дают статистического доказательства H1 или спроса.
Исследовательские V0/V1-ind/V2, frozen corpus, E3 и тема ВКР здесь не менялись.

## 7. Модель угроз рабочего пути

| Граница / угроза | Реализовано и проверяется | Ограничение / следующая проверка |
|---|---|---|
| Чужой файл/ссылка/команда из corpus | Allowlist roots, no import/exec, openat+NOFOLLOW, обычные files, bounds; symlink tests | Operator roots и OS account доверены; immutable mount предпочтителен. Произвольный Python wrapper не обнаруживается универсально |
| Присвоение новых прав через README/ответ | Finite schema/actions, no network/shell tools; model cannot approve/correct; spoof/hostile-input tests | Правдивость пересказа не доказывается exact quote; live adversarial model test еще нужен |
| Утечка через summary/cache/history | Проверка read capability и namespace полного view до выдачи; revocation/view tests; state 0700/SQLite 0600 | Не многопользовательский сервер. Владелец OS-account может читать/менять DB и policy; для SaaS нужны другие изоляция/auth |
| Секрет в source или provider error | Не читать скрытые/secret-named файлы, распознанный secret-pattern -> gap; ошибки без body/headers; secret tests | Regex не DLP. Подключать очищенные approved snapshots; нестандартный секрет может не распознаться |
| Промпт отправлен не туда | Exact configured endpoint, HTTPS/loopback, no redirect/proxy/fallback; transport tests | DNS/TLS/корпоративный gateway доверены; server-side retention и egress не проверены |
| Некорректный/прерванный inference | Bounded input/output/time/steps, strict parser, PARTIAL, сохраненные кандидаты; negative transport tests | Не доказана остановка server-side billing; резерв расходуется полностью |
| Обход бюджета новой ревизией/процессом | SQLite installation ledger, one inflight, no refund after unknown; restart tests | Local operator может заменить state или лимит; это не billing isolation против него |
| Внешний агент заявил PASS/approval | Digest-scoped `EXTERNAL_REPORTED`, не verified receipt и не owner approval | Подписанный доверенный runner/attestation не реализованы; код и тесты исполняет внешний агент самостоятельно |
| Локальность по всей цепочке | В графе нет embeddings, live connector, tracing, telemetry. В server plan offline+usage opt-out, internal network | Docker/GPU network capture еще не проведен. Внешний cloud coding agent может выносить контекст; его маршрут согласуется отдельно |

Один процесс может содержать parser и model controller. Количество агентов
не увеличивает доверие. В первом этапе один встроенный bounded agent; внешние
coding agents отдельны по роли/правам, не обязательны разные модели.

## 8. Незавершенное: ресурс и точная следующая проверка

| Пункт | Почему не завершен | Ресурс и следующий тест |
|---|---|---|
| Квалификация Qwen30/FP8/Next | Нет GPU/выделенного inference | Reviewed image digest + weights + слот и бюджет; запуск local-reference, пик памяти и одинаковая component/live серия, затем слепая разметка |
| Корпоративный endpoint | Не указан одобренный route/model/лимит | Operator ModelConfig+env secret+data route; schema/usage/tools probe, затем качество. Без auto-fallback |
| Экономия относительно сильного агента | Нет внешнего участника/независимого oracle и наблюдения труда | Согласованные 12 задач v4, baseline с notes, одинаковые доступы; собрать cold+warm minutes и расходы |
| Пользовательский UI / G-07 | Не нужен для исполнения CLI; в выбранный этап не включен | Выбрать реальный агент/developer и сценарий просмотра; отдельно проверить источники, gap и исправление. Markdown не считается UI-приемкой |
| Incremental index, фоновые события, RabbitMQ | Следующий объем, не обязательный HTTP-этап | Внешний case + измеренная стоимость полных сканов; отдельный профиль и replay/unknown tests |
| Совместная эксплуатация / verified test receipts | Один доверенный OS-user, отчеты без attestation | SSO/ACL boundary, изоляция state/derivatives и доверенный CI signer; отрицательные межпользовательские проверки |

## 9. Исправления R1-R7 и повторная техническая проверка

Основание - проверка HEAD `60914d650a8a1609a3023973164a07c5ab54b202`.
Все семь замечаний подтверждены регрессионными тестами до исправлений.
Повторный запуск новых тестов с исходным src этого SHA также воспроизвел
ошибки. Это проверка автора реализации, не независимый review и не серия v4.

| Замечание | Исправление | Регрессионное основание |
|---|---|---|
| R1 | Общий deadline/cancel, закрытие socket, OS-lock до фактического окончания transport; crash lease и charge сохраняются | `test_transport_regressions.py`: DNS/TCP/TLS/send/headers/body, медленные headers, живая и истекшая lease, pending resolver, kill/restart |
| R5 | Проверка типов envelope/choices/message/usage; PARTIAL без traceback, с ранее принятыми кандидатами и полным резервом | Там же: malformed envelope и CLI с успешным первым propose и некорректным вторым ответом |
| R2 | OpenAPI operation parameters заменяют path parameters по name/in до чтения default | `test_discovery_regressions.py`: effective null -> 10 при path default=100, отсутствие default и отдельный header parameter |
| R3 | Консервативный учет binding targets, повторных imports и относительных imports | Там же: def/class/import/except и явный monkey patch не становятся STATIC_RESOLVED; обычные aliases работают |
| R4 | GET positional params отделены от data/json; omitted None/empty values и неизвестные существенные параметры | Там же: None/empty/list, positional GET и POST body, динамические значения/kwargs/дубли |
| R6 | CURRENT зависит от текущей сверки корпуса и TTL; UNKNOWN не маскируется под CURRENT | `test_knowledge_regressions.py`: измененные bytes/inventory, TTL и неудачная сверка; human correction тоже устаревает |
| R7 | Стабильный ID при том же basis/actor/origin, лимит активного набора и замена в одной транзакции | Там же: новые контексты, прежний SQLite ID, архив, correction при cap и конкурентные writers/replacements |

Extractor profile повышен до `http-requests-2`, чтобы контексты старого
извлечения не оставались CURRENT после обновления кода. Идентичность операций
и прежние immutable записи не переписываются. Request schema остается
`agent-graph-1`; описание лимита в опубликованной Policy schema обновлено.
Сравнение с base другого extractor возвращает base_profile_mismatch до
публикации нового контекста; base нужно заново подготовить из закрепленного
снимка. Историческое чтение остается доступно.

Фактическая локальная регрессия: 480 тестов, включая 59 тестов графового
контура. Обязательный Ruff F401/F811/F841 проходит. Demo и компонентная серия
воспроизведены; 12 boundary checks, supported FN=0, общий FN=2, FP=0.
Точные команды, версии, время и контрольные суммы - в `validation.json`.
GPU, реальная модель, независимая серия v4 и экономия труда не измерялись.

Отдельные последующие задачи, без исправления в этой пачке:

- P3-URL: canonical default port/dot segments/unreserved encoding; сейчас
  соответствующие literal URL могут дать unmapped_call и PARTIAL.
- P3-DECORATOR: распознанный FastAPI decorator сейчас может добавить ложный
  unknown_http_client и PARTIAL. Нужно исключить его из consumer pass.

Эти задачи не расширяются UI, фоновыми сервисами или GPU-поставкой.

## Первичные источники моделей и serving

Проверены 21.10.2026. Это model cards/configs и документация поставщиков,
а не независимые доказательства качества нашего графа.

- [Qwen30 model card](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct)
  и [LICENSE](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct/blob/main/LICENSE).
- [Официальный FP8](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8),
  [закрепленный config](https://huggingface.co/Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8/blob/dcaee4d4dfc5ee71ad501f01f530e5652438fde0/config.json).
- [Qwen Next](https://huggingface.co/Qwen/Qwen3-Coder-Next),
  [Next FP8 и граница опубликованных benchmarks](https://huggingface.co/Qwen/Qwen3-Coder-Next-FP8).
- [DeepSeek-V3.2 weights/license](https://huggingface.co/deepseek-ai/DeepSeek-V3.2)
  и [configuration](https://huggingface.co/deepseek-ai/DeepSeek-V3.2/raw/main/config.json).
- [vLLM 0.15.1 structured output](https://docs.vllm.ai/en/v0.15.1/features/structured_outputs/)
  и [usage opt-out](https://docs.vllm.ai/en/v0.15.1/usage/usage_stats/).
