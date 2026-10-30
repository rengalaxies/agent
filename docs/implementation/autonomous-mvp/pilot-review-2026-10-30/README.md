# Проверка локального показа — 30.10.2026

База main 59529b4cfcacae9036420bac3d52c4ce1f104189 после #78. Работа — PR #79,
ветка codex/pilot-review-2026-10-30, без #72. Проверки независимы от алгоритма extractor,
но автор ожиданий — тот же исполнитель: это **авторские случаи**, не held-out или
независимый клиентский benchmark. MODEL OFF. M2 LIVE/M3 остаются BLOCKED.

## Продуктовый путь и исправления

Пользователь — разработчик/ревьюер API, решает кого позвать и что проверить.
Путь: изменение → потребитель → цитата/diff → реальный тест → известное исправление →
новый тест → история. Worker сам обследует код после UI-действия; оператор отдельно
запускает доверенные сервисы/проверку. Исправление в демо заранее подготовлено, не LLM.

Подтверждённый UI-дефект до правки: открыть B, выбрать Reporting quote, открыть
сохранённый анализ при недоступном graph endpoint. В настоящем Chromium получено
old_evidence_still_shown=true, label «reporting/client.py … снимок B», сообщение Failed to fetch.
Предыдущая цитата и findings оставались пригодными на вид. После правки они скрываются
до получения данных; при отказе остаётся неизвестность, correction выключена, есть retry.
Новый корректный ответ восстанавливает граф, старое evidence автоматически не выбирается.
Не ослаблены CSP, freshness, цитаты, схемы, роли и валидаторы.
Полный regression живёт в существующем browser_acceptance.py, не в статическом HTML-тесте.

Названия действий объясняют API/пагинацию/нового потребителя; A/B/D/E — вспомогательные.
Предложенная, запущенная и проверенная версии раздельны. Контекстный следующий шаг
не называет отсутствие находки безопасностью. Diff/история/основания сохранены.
Клавиатура, focus, aria-busy, словесные состояния и viewport 390px проверяются браузером.

## Ожидание отдельно от факта

Ожидания: tests/graph/pilot_expectations.json. Сохраняются в expectations-before.json
до вызова Graph. Факты: observations.json в CI artifact HTTP demo; настоящий FastAPI/requests
по двум loopback-портам фиксирует method/path/port/status и тела ответов.
Policy получает только разрешённые roots и адреса; expected consumer map не передаётся.

| Случай | Ожидание/основание | Факт/ограничение |
|---|---|---|
| GET и POST одного пути | два разных handler; меняется только GET default | Структурные связи различаются, риск только reader |
| Второй порт, тот же путь | другой реальный сервер возвращает [99] | remote_reader связан с remote, не warehouse; поведение не меняется |
| Префикс /edge/v1 и посторонний /edge/v2 | второй запрос реально получает 404 | Не становится связью с объявленной операцией; это не отсутствие вызова |
| DELETE против GET/POST | реальный ответ 405 | Нет положительной связи с этими операциями; данных для другой операции нет |
| Строка @app.get в тексте | Python string не регистрирует API | /ghost не объявлен |
| Wrapper с динамическим target | реально делает тот же запрос | Runtime 6→2, positive static edge отсутствует, gap/unknown; профиль не расширен |
| Требование полноты | явно заданные шесть ID, не customer fact | Reader 6→2: наблюдённое нарушение; static risk оставляет test_executed=false |
| Добавление/удаление caller | исходник реально появляется/исчезает | новые scans меняют зависимости; отсутствие ребра ограничено корпусом/профилем |
| Изменение цитируемого файла | старое основание требует пересмотра | то же proposal ID, STALE, история не удаляется |
| Недоступный root | данных недостаточно | PARTIAL/gaps; не безопасное отсутствие связи |
| Документация, mixed scope, rebound declaration | ожидания отдельно в pilot_boundaries.py | известные main/profile4 ошибки DEFERRED_72, код #72 не перенесён |
| Старый pinned extractor и knowledge | должны стать STALE после смены профиля | main сохраняет CURRENT: DEFERRED_72, отдельное решение/согласование #72 |
| Отрицание GET и изменение POST | только POST | PASS в диагностике |
| Свежий event при фоне | приоритет/справедливость и durable metadata | повторно запускаются существующие #78 tests, не копируются как «новые» |
| Incompatible → корректный результат | rejected не показывается как анализ, следующий работает | существующий demo test расширен recovery реальным CLI; ошибка остаётся в истории |

Отсутствие связи значит «не найдено в этих источниках/грамматике», а не «HTTP вызова нет».
Структурная зависимость, условный риск и фактическое исполнение — три разных результата.
Пять известных DEFERRED_72 не объявляются PASS благодаря зелёному pipeline.

## Выполненные проверки и восстановление среды

LOCAL до потери executor: новая HTTP matrix PASS; 38 demo backend/CLI tests PASS;
rejected→good sequence 2 tests PASS; node syntax и Ruff PASS. Ожидания корпуса не менялись.
Первый запуск harness с относительным root был отклонён invalid_source_root; исправлен
путь harness, не validator. Отдельная диагностическая policy сперва не содержала обязательное
addresses; добавлено пустое поле. Это ошибки запуска, не успех анализатора.

Настоящий UI открыт Chromium. Сняты initial, B desktop/mobile и failed-graph before.
В after-проверке сняты baseline, B desktop/mobile и graph-unavailable. Regression очистки/
retry и mobile overflow прошли; весь Docker acceptance был FAIL на устаревшем сравнении
названия запущенной версии, до D/E. Сравнения переведены на raw data-version, реальные
runtime oracle assertions не менялись. Не выдаём этот неполный прогон за PASS.

Managed executor затем стал unavailable (exec-server transport disconnected).
Локальный commit d5d6ab95c2fa3213d34d6b3b078dd2a9816de45e и дальнейшие незапушенные
правки недоступны. Реализация восстановлена GitHub API от актуального main.
Точное восстановленное дерево проверяет **CI PR #79**, а не прежний LOCAL.
Среда позднее восстановилась. Создан отдельный чистый worktree точного remote head
1c8e44beff9c947e8f72cddf0f0c05bbe3d619ab; прежние незавершённые worktrees сохранены.
Повторены 38 backend/CLI tests PASS (24.658s), авторская runtime matrix PASS,
unittest нового случая PASS, node syntax и Python compile PASS. Для первого повтора
не хватало requests; установлен прежний hash-lock из offline wheelhouse в отдельную venv.
Ruff после восстановления отсутствовал локально; он выполняется HTTP CI, прежний LOCAL
Ruff остаётся отдельным историческим результатом. Просмотрены настоящие E desktop
и состояние отказа graph; это визуальный проход исполнителя, не тест с участником.

Точный окончательный head, ссылки на Core/runner, HTTP demo и artifact со скриншотами/
ACCEPTANCE.json — в PR #79 и его Checks. Сохраняется 14-дневный CI artifact:
baseline.png, desktop-B.png, mobile-B.png, repair.png, desktop-E.png, mobile-E.png,
graph-unavailable.png. Если run FAIL, артефакты являются диагностикой, не приёмкой.
До зелёного CI точного окончательного head работа не принята и не сливается. После
восстановления среды снимки до/после и безопасные JSON сохранены в evidence/.
В Git нет паролей, auth/web config, SQLite, runtime registry или Docker receipts вне отчёта.
Даты исторических manifests/2b-r1/6-r1..6-r3 не изменены.

Проверки: PYTHONPATH=src:. python tests/graph/ci_unittest.py discover -s tests -v;
отдельно tools/autonomous_mvp/tests; HTTP workflow выполняет graph/demo suites,
новую runtime matrix, Docker/browser и пять последовательных показов с zero sandboxes.
Отдельный CI smoke исполняет документированные init/serve/run A/observe/stop/reset/serve
на чистом каталоге, настоящем Docker и backend; проверяет сохранение history после рестарта.
Одноразовый пароль передаётся только дочернему configure, не публикуется в artifact.
Это автоматическая проверка команд; человеческое прохождение остаётся NOT_RUN.
Повтор из чистого checkout и сценарий: docs/product/pilot/LOCAL-SHOW.md.
CI не подтверждает ресурсы Cloud.ru, LIVE или пользовательскую пользу.

## Отдельный проход корректности

Проверены invalidation всех производных views, late-response tokens, отсутствие старых
correction citations, retry на текущем результате, сохранение rejected job, границы
expected data/Policy, cleanup только своих ресурсов. Селекторы кнопок ограничены button,
чтобы отображаемый data-version не становился элементом управления. Прежний профиль/коннекторы/очередь
#78 не переписаны. Независимого человека/второго ревьюера здесь не было.

## Уровни и риски

| Уровень | Состояние |
|---|---|
| Код | изменения в PR #79; итог интеграции — PR metadata |
| LOCAL | частично проверено до потери executor, границы выше |
| CI | обязательные Checks точного head; ссылки в PR, не подмена LOCAL |
| Человек/участник | NOT_RUN; машинное время не человеческие минуты |
| Целевая ВМ | NOT_RUN; доступа нет и здесь не нужен |
| Настоящие App/Jira/webhooks | NOT_RUN; не создавались |

P1: ошибки intent/declaration/profile на main до согласованного #72; не использовать этот
показ как квалификацию незнакомого проекта. P1: M3/LIVE недоступны. P2: runtime observation
истекает за 120s, требуется observe. P2: очередь на диске не ограничена, есть нагрузочный
риск #78. Документированные команды проходят отдельный CI smoke; интерактивное прохождение
новым участником остаётся NOT_RUN. Нет SLA stale window, atomic DB/API или доказанной пользы.

| Следующая работа | Можно без ВМ | Доступ/участники | Критерий завершения |
|---|---|---|---|
| Участник смотрит локальный показ | да | разработчик, обычный локальный Docker | понимает риск/тест, записаны решения и обратная связь |
| Независимый корпус/ожидания | да | владелец проекта, отдельный автор | ожидания зафиксированы до анализа; FP/FN и unknown измерены |
| #72 | да | явное согласование M3 | отдельный проверенный merge, не включён молча сюда |
| Показ новому участнику | да | обычный локальный Docker, участник | init/serve/run/stop/reset без ручной SQLite и понятный следующий шаг |
| App probe | да | доверенный PEM и одобрение environment | настоящий installation-token/read API PASS |
| Установка/восстановление | нет | один оператор M3, восстановленный хост | loaded SHA, restart, restore/rollback |
| Настоящие webhooks/комментарии | работающий сервис | HTTPS, App/Jira, тестовый контур | M2 LIVE сценарий с дублями, новым head, API error и self-loop |

## Сохранённые доказательства

- [До: ошибка оставляет старую цитату](evidence/screenshots/before-failed-graph.png),
  [до: B desktop](evidence/screenshots/before-B-desktop.png),
  [исходное браузерное наблюдение](evidence/before-browser.json). Код до: main 59529b4.
- [После: отказ скрывает основания](evidence/screenshots/graph-unavailable.png),
  [после: E desktop](evidence/screenshots/desktop-E.png),
  [после: E mobile](evidence/screenshots/mobile-E.png). Код приложения: 1c8e44beff9c947e8f72cddf0f0c05bbe3d619ab.
- [Ожидания до Graph](evidence/expectations-before.json),
  [фактические HTTP наблюдения](evidence/observations.json),
  [пять нерешённых границ #72 и контроль отрицания](evidence/deferred-boundaries.json).

Источник ожиданий и корпуса — автор; независим только способ проверки через
действительные HTTP ответы и заранее заданное требование. Исторические исследовательские
корпуса не менялись. Все screenshots — реальные captures работающего приложения.

## Итог LOCAL после восстановления

Полный Docker/Chromium сценарий **PASS** на коде приложения 1c8e44beff9c947e8f72cddf0f0c05bbe3d619ab,
image sha256:ef592b1ce21121c64a19e05168583662d33e49598c3d6f01494d963ad2d19178.
A PASS (250), B ожидаемый FAIL (Reporting 100/Billing 250), D PASS (250),
E PASS (Reporting/Billing/Export 250), Status negative control PASS. Пять UUID, история
сохранена, sandbox_projects_after_stop=0. [Полный LOCAL отчёт](evidence/LOCAL-ACCEPTANCE.json).
[38 backend/CLI tests](evidence/demo-tests.log).

Отдельно точные команды init/serve/run A/observe/stop/reset/serve **LOCAL PASS**;
история открывается после рестарта без SQLite правок.
[Команды и сохранённые UUID](evidence/LOCAL-SHOW.json). Код wrapper совпадает с 1c8e44b;
добавленная правка smoke лишь различает LOCAL и CI в отчёте. В финальный browser CI
добавлено явное page.reload с сохранёнными E и анализом B; до прохождения этого CI
новая проверка не считается LOCAL PASS.

CI приложения 1c8e44b: [HTTP + commands PASS](https://github.com/rengalaxies/agent/actions/runs/41103411947),
[P1/runner/systemd](https://github.com/rengalaxies/agent/actions/runs/41103411858),
[evidence](https://github.com/rengalaxies/agent/actions/runs/41103411878),
[workflow syntax/security](https://github.com/rengalaxies/agent/actions/runs/41103411920),
[Core](https://github.com/rengalaxies/agent/actions/runs/41103411812).
Финальное дерево дополнительно включает эти доказательства, metadata LOCAL/CI и reload
assertions; его точный head и обязательные CI зафиксированы в PR #79 перед merge.

Начальное состояние, B/D/E, отказ/retry, исторический результат и мобильный layout
увидены в настоящем браузере. PARTIAL/недоступный root и rejected→good проверены
через backend/CLI; отдельного визуального сеанса со всеми PARTIAL и queue states нет.
Человеческий участник, клиентский корпус, целевая ВМ и внешние интеграции **NOT_RUN**.
Технический локальный показ воспроизводится; понятность участнику ещё не измерена.
