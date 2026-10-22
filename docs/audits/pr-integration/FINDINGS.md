# Findings и исправления

Путь, который проверял аудит: выбор версии в UI → `POST /jobs` (`store.enqueue`,
revision CAS) → worker материализует снимок → CLI ядра (`prepare_context`,
`analyze_change`, `dependencies`, `evidence`) → `store.finish` публикует graph и
result в одной транзакции → `GET /graph`, `/jobs/{id}`, `/evidence` → `app.js`.
Отдельно: операторский runner (`run_scenario.py`, `runtime_guard.py`) пишет
receipt под тем же workload lock, UI сопоставляет его с ревизией через
`runtime.applicable`.

Очередь, CAS, отмена, восстановление после убийства процесса и разделение
proposed/running выдержали проверку: гонки закрыты транзакцией `BEGIN IMMEDIATE`
и проверкой `cancel_requested` внутри неё, а сбой после `analyze_change`
восстанавливает файлы и ставит `needs_refresh`, который блокирует correction
до нового обследования. Дефекты нашлись в другом месте: там, где система
сообщает о силе своего вывода.

## F1. Ядро не видит изменение нелитерального default `page_size` (высокий)

**Сценарий.** FastAPI-провайдер объявляет `page_size: int | None = Query(None)`
и меняет на `Query(100)`. Это идиоматичная форма FastAPI. Второй вариант:
`page_size = DEFAULT`, где меняется `DEFAULT = None` → `DEFAULT = 100`.

**Код.** `src/agent_graph/discovery.py`, `providers()`: default вычислялся
`constant(defaults["page_size"], {})`, то есть только literal. Иначе
`default_known=False` без пробела. `src/agent_graph/engine.py`,
`analyze_change()`: delta строится, только если default известен с обеих сторон.

**Последствие.** `deltas=[]`, `findings=[]`, `unknowns=["no_supported_behavior_delta..."]`.
Reporting делает одиночный запрос и потеряет записи 101…250, а система не даёт
ни предупреждения, ни пробела, указывающего на `page_size`. Покрытие при этом
PARTIAL только из-за декоратора FastAPI (см. L1), так что пользователь не может
отличить этот случай от обычного шума.

**Свидетельство.** [repro_page_default.py](repro_page_default.py) запускает
настоящие `discovery` и `Graph.analyze_change` на корпусе в памяти:

```text
# ядро a9385c5
fastapi_query    default_known=False gaps=['unknown_http_client'] deltas=[] findings=[]
module_constant  default_known=False gaps=['unknown_http_client'] deltas=[] findings=[]
# ядро 5d7ee0f
fastapi_query    gaps=['page_size_default_unresolved', 'unknown_http_client'] deltas=['PAGE_DEFAULT_UNRESOLVED'] findings=[('Reporting', 'RECHECK_REQUIRED')]
module_constant  default_known=True deltas=['PAGE_DEFAULT_CHANGED'] findings=[('Reporting', 'POSSIBLE_TRUNCATION')]
```

**Исправление.** `5d7ee0f`: default резолвится через те же однократно
присвоенные module constants, что и URL; иной default даёт пробел
`page_size_default_unresolved`; изменение объявления при неизвестном default
даёт delta `PAGE_DEFAULT_UNRESOLVED` и `RECHECK_REQUIRED` для каждого потребителя.
Профиль поднят до `http-requests-3`: basis включает профиль, поэтому контексты
старого extractor становятся STALE, как это уже сделано при переходе на `-2`.
`84cca17` перезакрепляет демо на это ядро (lock-хеши, `CORE_SHA`, `PROFILE`,
CI, delivery, RUNBOOK).

**Тесты.** `tests/graph/test_discovery_regressions.py`:
`test_r5_unresolved_page_default_change_requires_recheck_not_silence`,
`test_r5_module_constant_page_default_change_is_classified`. Оба падают на
`a9385c5` по выводу repro выше.

## F2. UI называет операторскую проверку независимой (средний)

**Сценарий.** Оператор запускает runner для B, receipt показывает Reporting 100/250.

**Код.** `src/agent_graph_demo/web/index.html:118`: "Независимая проверка
сравнивает все 250 ID". Каждый receipt пишется с `origin="operator_runner"`,
`independently_verified=False` (`tools/agent_graph_demo/run_scenario.py`).

**Последствие.** Наблюдение оператора на его же стенде подаётся как независимое
подтверждение. Фраза видна на всех скриншотах приёмки.

**Исправление.** `9374712`: текст говорит, что проверку запускает оператор
отдельным runner, и что это наблюдение, а не независимое подтверждение.

## F3. UI выдаёт нераспознанное использование за одиночный запрос (средний)

**Сценарий.** Потребитель вызывает `requests.get(url, params={**extra})` или
делает запрос в цикле без `next_cursor`. Ядро ставит `UNKNOWN_USAGE` и пробел
`dynamic_parameters`.

**Код.** `app.js`, `renderGraph`: `d.usage === "CURSOR_LOOP_OBSERVED" ? "Обход
страниц в коде" : "Одиночный запрос в коде"`.

**Последствие.** UI утверждает наблюдение, от которого анализатор явно
отказался. Для синтетического демо незаметно: там нет `UNKNOWN_USAGE`. На
клиентском репозитории это основной режим ошибки.

**Исправление.** `9374712`: отдельная подпись для каждого кода, неизвестный код
показывается как "Использование не распознано".

## F4. Панель последствий теряет анализ после человеческого уточнения (средний)

**Сценарий.** A → B: панель показывает "Reporting: возможна потеря части
заказов". Оператор сохраняет уточнение по основанию Reporting.

**Код.** `app.js`, `loadGraph`: брался последний job с `result_ref` на текущей
ревизии. Correction публикуется на той же ревизии (`target_revision` растёт только
у `analyze_change`, `store.py`), поэтому выбирался job уточнения.

**Последствие.** Предупреждение о потере данных исчезает с основного экрана, а
вместо него выводится подсказка версии A "Выберите B для анализа нового лимита".

**Исправление.** `3e473f8`: берётся последний `analyze_change`, и только если
его `context_used_id` равен контексту показанного графа. Без анализа UI пишет,
что для основания анализ не выполнялся. `tests/graph_demo/browser_acceptance.py`
теперь сохраняет уточнение на B и проверяет, что предупреждение осталось.

## F9. Одно человеческое уточнение ломает все следующие job сессии (высокий)

**Сценарий.** A → B, оператор сохраняет уточнение по основанию Reporting на B,
затем выбирает D (успех), потом E или повторное обследование D.

**Код.** `src/agent_graph_demo/worker.py`: после CLI worker выдаёт evidence для
каждой цитаты в graph и result. Граф ядра включает все `proposals` view, а
цитата уточнения указывает на исходник контекста B. Worker искал её только в
контексте текущего графа и, если есть, в `base_context_id` анализа.

**Последствие.** На D анализ проходит (база B). Повторное обследование D и анализ
D → E получают `not_found` и завершаются FAILED. Сессия остаётся только с
reset. Уточнение, которое должно было лишь добавить заметку, выводит показ из строя.

**Свидетельство.** Нашёлся новым шагом browser acceptance из F4: CI run
[39816507144](https://github.com/rengalaxies/agent/actions/runs/39816507144),
`ACCEPTANCE.json`: `TimeoutError` в `browser_acceptance.py:146`, ожидание E.
Тот же журнал без шага уточнения (#41) проходит.

**Исправление.** `d407ade`: цитата уточнения ищется сначала в контексте графа,
затем в контексте самого предложения, затем в базе анализа; на evidence
записывается basis выбранного контекста. Тест
`test_correction_on_b_does_not_fail_later_rescan_and_analysis` в
`tests/graph_demo/test_graph_cli.py` проходит A → B → уточнение → D → rescan → E
на настоящем CLI и проверяет, что основание уточнения осталось привязано к B.

## F5. ACCEPTANCE.md утверждает непроверенное (низкий)

`docs/agent-graph-demo/ACCEPTANCE.md:23`: "контейнеры не накапливаются и не
возрождаются". `tools/agent_graph_demo/accept.py` останавливает sandbox и
проверяет inventory, но Docker не перезапускает. Исправлено в `fddb1c2`.
На ВМ рестарт Docker выполнялся (отчёт #38), но повторный receipt после него в
пакет не попал, есть только строка `explicit_reconcile_and_rerun: "PASS"`.

## F6. Workflow lint на main красный (низкий)

`actionlint` с shellcheck: `cloudru-foundation-models.yml:37: SC2129`.
Шаг публикует диагностику через `gh issue`, поэтому причина не видна в UI
проверок. Исправлено в `205bbd7`.

## F7. Отчёт #35 не разделяет статический и модельный вывод (низкий)

`dependency_sufficiency` (`src/agent_graph/evidence_refs.py`) выдаёт
`SUPPORTED_WITHIN_PROFILE` только claim, совпадающему с ребром, которое уже
нашёл статический extractor. Таблица отчёта писала "PASS / PASS" и "два цикла
подтвердили". Исправлено в `f8cb0e1` с обновлением `files-sha256.json`.

## F8. Отчёт #38: мелкие неточности (низкий)

Неподкреплённое "независимый review подтвердил", потерянный Export в
`acceptance-summary.json` (все пять E receipts: Export 250), нераскрытая правка
`allowed_session_ids` в `/etc/agent-graph-demo/auth.json` на ВМ, заголовок
RUNBOOK "подготовлено, не выполнено". Исправлено в `71a0626` с обновлением
`files-sha256.txt`.

## Ограничения, не исправленные в этом аудите

- **L1. Покрытие всегда PARTIAL.** Ядро считает `@app.get(...)` вызовом
  неизвестного HTTP-клиента. С любым FastAPI-провайдером ярлык покрытия не
  несёт сигнала, настоящие пробелы видны только в списке gaps. Тест
  `test_graph_cli` закрепляет это как ожидаемое. Исправление меняет приёмочные
  ожидания и должно идти отдельной правкой ядра.
- **L2. Модельный цикл не расширяет граф.** По F7 принятый кандидат evidence-refs-v2
  всегда повторяет статическое ребро. Модель полезна здесь как ассистент
  объяснения, не как обнаружение.
- **L3. `task` у `analyze_change` молча теряется.** API принимает поле, worker его
  не передаёт, CLI ядра берёт task базового контекста.
- **L4. Отмена QUEUED job ставит `needs_refresh`**, хотя ничего не исполнялось.
  Это консервативно, но требует лишнего обследования.
- **L5. Новый потребитель не считается изменением.** В E Export появляется в
  графе, а анализ D→E пустой (`no_supported_behavior_delta`). Анализ сравнивает
  только объявления провайдера.
- **L6. Локальная приёмка слабее спецификации.** Один полный показ A→B→D→E и
  четыре сессии только с A. Пять полных показов выполнены только на ВМ (#38).
- **L7. Пароли Basic auth хранятся как несолёный SHA-256.** Для закрытого показа
  через SSH tunnel приемлемо, для внешнего доступа нет.
- **L8. Ядро и демо работают только на Linux** (`fcntl`, `O_NOFOLLOW`, `dir_fd`).

## Качество тестов

- Сильные стороны: демо-тесты вызывают настоящий CLI ядра, убивают реальный
  процесс worker, CI гоняет Docker и Chromium. Это ловит поломки протокола
  очереди и публикации, а не повторяет реализацию.
- Слабое место, через которое прошёл F1: все тесты изменения default используют
  literal `None`/`100` или OpenAPI. Fixture задаёт ровно тот синтаксис, который
  понимает грамматика, поэтому тесты подтверждают известный пример, а не
  контракт "неизвестное не выдаётся за неизменное".
- Ни один тест не сохранял уточнение и затем не менял версию. F9 поэтому жил
  в main незамеченным, пока новый шаг приёмки не дошёл до E.
- UI не имеет проверок формулировок силы свидетельств. Browser acceptance
  проверяет только позитивный путь fixture, где нет `UNKNOWN_USAGE` и нет
  уточнения после анализа. F3 и F4 поэтому проходили зелёный CI.
- `test_graph_cli` закрепляет шумный PARTIAL как инвариант (L1).
