# Исторический README до обновления ImpactMap

Сохранён исходный текст основной ветки `ed6369f` на 27.11.2026. [Актуальная точка входа](../../README.md). Прежние статусы не являются текущим продуктовым срезом.

# Data Mesh Release Protocol

## Актуальное направление, 24.10.2026

- [Автономный B2B-сервис Jira/PR](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product/pilot/README.md): коробочная установка, открытые модели и конституции, обновляемый граф кода и наблюдаемых вызовов, минимальное участие человека.
- [Короткая презентация: PPTX и PDF](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product/pilot/presentation/README.md), [решения и инженерные задачи](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product/pilot/TRACKING.md), [общая задача #55](https://github.com/rengalaxies/agent/issues/55).
- Сейчас реализованы узкое ядро и синтетическое демо. Автономные интеграции, runtime-граф и новая коробка — следующие инженерные пачки. Постоянный оператор/инженер/разметчик не входят в предложение.

## Локальный показ для первого разговора

[Из чистого checkout: запуск, сценарий, reset/stop и вопросы участнику](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product/pilot/LOCAL-SHOW.md).
Работает существующий HTTP UI/backend: 250 → 100 → 250, затем Export, с цитатами,
diff и историей. Синтетика, MODEL OFF; локальный показ не равен установленному
автономному сервису или клиентской полезности.

## Код, исследование и предыдущие решения

Продуктовые документы 16–21 октября ниже сохраняют историю. Их прежние приоритеты и предложения не заменяют актуальное направление выше.

- [Аудит архитектуры HTTP-графа, 22.10.2026](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/audits/architecture/README.md) - фактическое устройство ядра `src/agent_graph` и демо, измерения, решение по стеку и последовательность перехода к внутреннему инструменту команды. Продуктовый код графа: `src/agent_graph` (ядро, CLI), `src/agent_graph_demo` (HTTP-демо); остальные каталоги ниже относятся к исследованию ВКР и прежним прототипам.
- [Прежний фокус и границы проверки, 20 октября](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product-focus-2026-10-20.md) - согласованные решения пачки 2: контекст последствий для людей и ИИ-агентов, HTTP(S)/API первым сценарием, RabbitMQ следующим приоритетом, уведомления и актуальность подтверждений без блокировки релиза. Это план; новые адаптеры и спрос пока не подтверждены.
- [Интервью RU / EN](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/launch-2026-10/02-STAKEHOLDER-INTERVIEWS-RU-EN.md) - единый discovery-сценарий HTTP/API и RabbitMQ, вопросы о фактической работе агентов, отдельные карточки концепции и шаблон заметок. Облако и демо для беседы не требуются.
- [Историческое предложение для клиента](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/migration-completion-offer.md) - разбор реального межкомандного изменения и ограниченная проверка пользы относительно текущего процесса и сильного агента.
- [План продукта 16–17 октября](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product-rebuild-2026-10-16.md) - история прежней гипотезы автономного исполнителя; актуальные границы первой итерации заданы документом от 20 октября.
- [Архитектура продукта и схемы для обсуждения](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product-architecture-2026-10-20.md) - консультативный HTTP/API и RabbitMQ-модуль для людей и агентов, сбор конституции до работы, источники зависимостей, версии и границы доверия. Редакция 4: компактная постановка для преподавателя, сквозной пример, точные контракты и ограниченный MVP; [прожарка и принятые решения](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product-architecture-roast-2026-10-20.md).
- [Полезный граф: решения и статусы реализации](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/useful-graph-open-questions-2026-10-21.md) - агент в связке с разработчиком, встроенное сопровождение и корпоративные coding agents. В PR №28 реализован ограниченный HTTP-этап; [CLI и запуск](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/examples/agent_graph/README.md), [модели, ресурсы, стоимость и проверки](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/agent-graph-implementation-2026-10-21.md). Реальная модель, UI и преимущество над сильным агентом еще не проверены.
- [Исследовательский интерфейс](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/ui/README.md) можно запустить локально вместе с V2 API: `PYTHONPATH=src python -m services.local_demo` после установки `.[api,distributed,test-api]`. Это существующий синтетический демонстратор, а не новый модуль завершения изменений.
- Этот README описывает **реализованный исследовательский путь в main**, команды запуска и границы результатов. Продуктовый план не меняет автоматически ВКР, frozen-корпус или исследовательские baselines.
- [Локальный распределенный стенд](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/stand/README.md) и [модуль знаний](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/knowledge-module-2026-09-29.md) - технические инструкции к имеющемуся коду.
- [Пакет запуска 13 октября](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/launch-2026-10/00-START-HERE.md) - исторические решения и инфраструктурные инструкции; актуальность конкретного действия проверяется по коду и текущему продуктовому документу.

Исследовательский прототип для ВКР "Проектирование событийно-ориентированной архитектуры управления кросс-платформенными метаданными пользователей на принципах децентрализации (Data Mesh)".

Текущий срез реализует детерминированное ядро и модуль карты knowledge-1:

- форматы `ChangeProposal`, `ConsumerObligation`, `LocalVerdict` и `ReleaseDecision`;
- три синтетических домена: `fintech`, `retail`, `mobility`;
- режимы `V0`, `V1-ind` и `V2`;
- 20 сценариев разработки и отдельный закрытый evaluation-набор из 40 новых сценариев шести семейств;
- физическое разделение входных сценариев, политики V1-ind и эталонных ответов;
- безопасную финализацию `REJECT > NEEDS_REVIEW > ACCEPT`;
- раздельные процессы запуска валидаторов и последующего scoring;
- хеш-связанную цепочку `raw results -> run manifest -> scored results -> score manifest`;
- машинно-читаемый отчёт и фиксированные метрики;
- параметризованную сценарную модель затрат V1-ind и V2 без заявления фактического ROI.

Однопроцессное экспериментальное ядро не требует Kafka, PostgreSQL или LLM. Отдельно реализован optional PostgreSQL audit демонстрационного API; он не является хранилищем нового продукта. Автоматический bootstrap и агентный ремонт еще не реализованы. Трехпроцессный стенд E4 использует собственные SQLite-хранилища доменов. Локальные результаты E4 не подтверждают облачную эксплуатацию.

## Исполняемый продуктовый прототип

[Корпоративная очередь и два профиля](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/examples/product/enterprise/README.md), [неоднородный переход и Git/CI](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/examples/product/contract_change/README.md), [установка и восстановление](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/infra/product/README.md). Это работающий односерверный инженерный прототип; готовность корпоративного UI, SSO и коммерческое преимущество не заявляются.

Прототип исполнения ниже сохраняется как инженерный задел. [Прежняя корпоративная архитектура](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/enterprise-product-design.md) описывает гипотезу автономного исполнителя; действующий продуктовый фокус и границы первой итерации — [анализ API и событийных интеграций](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/product-focus-2026-10-20.md). [Конкурентный разбор](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/competitive-evidence-2026-10-16.md) остается источником прежней проверки, а не доказательством преимущества нового предложения.

[Продуктовый UI и командное согласование](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/examples/product/execution/WEB.md): локальный запуск, роли, история, устаревание результатов и черновики PR/уведомлений. Реальная доставка требует отдельного opt-in gateway.

[Сквозной запуск двух потребителей](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/examples/product/execution/README.md): обследование локального snapshot, вычисляемый patch, реальные SQL-проверки и устойчивый журнал. Это ограниченный внутренний профиль без production-эффектов; исходники и результаты ВКР не подменяются.

## Быстрый запуск

Требуется Python 3.12.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
make test
make pilot
make business-pilot
```

`make pilot` прогоняет 20 сценариев через три режима и сохраняет:

- `results/pilot-raw-results.json` - неизменяемые результаты без эталонных меток;
- `results/run-manifest.json` - хеш raw-файла и состояние validator run;
- `results/pilot-results.json`;
- `results/pilot-metrics.json`;
- `results/pilot-score-manifest.json` - связь raw-файла, oracle, scored results и метрик.

## Структура

- `src/datamesh_release_protocol` - модели, валидаторы, конечный автомат и CLI;
- `scenarios/development` - 20 сценариев разработки;
- `scenarios/evaluation` - 40 зафиксированных сценариев будущего E3;
- `oracles/development.yaml` - отделённые эталонные решения и обоснования;
- `oracles/evaluation.yaml` - отдельный evaluation-oracle, недоступный валидаторам;
- `contracts/base` - базовые продукты трёх доменов;
- `constitutions` - локальные полномочия и безопасное поведение;
- `policies` - федеративные инварианты и фиксированная политика V1-ind;
- `schemas` - JSON Schema ключевых артефактов;
- `tests` - функциональные и fail-safe проверки;
- `experiments` - конфигурация пилота;
- `business/economic-model.yaml` - относительная модель затрат и три синтетических сценария чувствительности;
- `docs/business-problem.md` - бизнес-проблема, ожидаемая практическая ценность и границы утверждений;
- `docs/stakeholders-and-value.md` - карта заинтересованных сторон и ценностное предложение;
- `docs/business-process-as-is.md` - аналитическая базовая модель выпуска без consumer-aware протокола;
- `docs/business-process-to-be.md` - целевой процесс выпуска с локальными вердиктами и детерминированной финализацией;
- `docs/economic-model.md` - формула, связь метрик с затратами, точка безубыточности и границы экономического вывода;
- `src/change_completion` - контракты, verifier и ограниченный исполняемый внутренний профиль; универсального исполнителя нет;
- `tests/product` и `examples/product` - отдельные продуктовые проверки и примеры описаний разных стеков; [offline verification replay](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/examples/product/verification/README.md) сравнивает синтетические observations с независимо одобренными ожиданиями без исполнения candidate;
- `services`, `ui`, `stand`, `deploy` - существующие исследовательские API, интерфейс, стенд и development-размещение; их наличие не означает готовую on-premise поставку.

## Интерпретация режимов

- `V0` проверяет совместимость структуры схемы.
- `V1-ind` применяет замороженную матрицу baseline-возможностей по семействам изменений.
- `V2` передаёт типизированные обязательства каждого активного потребителя единому повторно используемому интерпретатору с фиксированным реестром обработчиков.

`V1-ind` и `V2` являются параллельными стратегиями поверх общей структурной проверки. V2 не наследует автоматически общие запреты V1-ind, если действующее обязательство конкретного потребителя явно допускает изменение. Полные определения и границы режимов приведены в `docs/mode-definitions-0.3.1.md`. Модуль знаний knowledge-1 реализован отдельным полным путём: доменные записи, подтверждение/отзыв, регистрационная полнота, неизменяемый снимок, V2 и проверка актуальности перед commit. Экспериментальное ядро сохраняет прямые входы сценария; это различие явно отражено в [описании модуля](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/knowledge-module-2026-09-29.md).

Ожидаемые метки физически отсутствуют во входных сценариях. Команда `run-catalog` не принимает путь к oracle и создаёт только raw results и run manifest. Отдельная команда `score-results` сначала проверяет хеш и полноту raw results, затем загружает oracle и создаёт новые scored results, метрики и score manifest. Raw-файл не перезаписывается. Полная цепочка зафиксирована в `docs/e3-execution-chain-0.3.1.md`.

## Состояние заморозки

Версия 0.3.0 сохранена как контрольная точка до E3. Внутренний аудит выявил совпадение кодовых путей V1-oracle и V2, поэтому окончательная заморозка 0.3.0 снята до исправления всех блокеров. После решения 29.09 V1-oracle исключён из активных режимов; независимый scoring oracle сохранён. Validator run и scoring выполняются разными командами, а зависимость сценариев учитывается шестью кластерами семейств F1-F6. Это новая рабочая итерация без окончательной заморозки. Критерии H1, 95% интервалы и кластерный парный анализ до следующего freeze описаны в `docs/metrics-0.3.1.md`. Scored E3 на 40 evaluation-сценариях ещё не запускался. Это ещё не независимая экспертная проверка и не подтверждение H1.

`make evaluation-check` проверяет только структуру и изоляцию evaluation-набора. Он не выполняет основной E3 и не рассчитывает его результаты.

`make business-pilot` применяет экономическую модель только к уже сформированным development scored results. Полученный анализ чувствительности не является E3, оценкой фактической экономии или подтверждением ROI.


## Карта и экспертный пакет

- [Модуль знаний: сущности, права, операции и ограничения](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/knowledge-module-2026-09-29.md).
- [Синтетический сквозной пример](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/examples/knowledge/demo.py): `PYTHONPATH=src:. python examples/knowledge/demo.py`.
- [Слепая экспертная анкета и анализ](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/expert/README.md); анкета работает локально, не отправляет ответы.
- Проверки: `make test`; с API extra и test-api выполняются проверки маршрутов; `node expert/smoke-test.cjs` проверяет поведение анкеты.

## Надёжность решений: пакет 1

[Ревизия, устойчивый журнал и границы гарантий](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/package-1-reliability-2026-09-29.md). Решения сохраняются и восстанавливаются; одно изменение получает единственное разрешение, даже при новых run/proposal. Внешняя публикация требует дедупликации release_id у получателя. Пример: `PYTHONPATH=src:. python examples/knowledge/recovery_demo.py`.

## Пакет 2: распределённый стенд

Реализованы три доменных процесса, подписанные события, TTL, устойчивые ответы и журнал решений, два адаптера. Пройдены 588 ускоренных и 37 номинальных локальных испытаний E4, 111 unittest-тестов и семь проверок восстановления. [Отчёт и границы](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/package-2-distributed-2026-09-29.md), [запуск](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/stand/README.md), [сводка результатов](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/results/e4-local-manifest.json). Основной E3 и облачный E4 не проводились.

## HTTP graph demo (batch 2)

Executable Orders/Status and A/B/D/E consumers, a durable CLI-backed queue and a Russian evidence UI are a separate application from the historical research `ui/`. See [runbook and deployment handoff](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/agent-graph-demo/RUNBOOK.md) and [actual acceptance scope](https://github.com/rengalaxies/agent/blob/ed6369f6ff4854ba4f2f3461eaf8b37a828754d9/docs/agent-graph-demo/ACCEPTANCE.md). The graph core is an exact read-only dependency, with no model calls or VM changes in this demo PR.
