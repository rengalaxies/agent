# MVP delivery plan — Codex as primary implementer

Дата: 28.10.2026. Владелец: Daniil. Основной исполнитель: Codex в текущем чате.
Это рабочий план пачек и критериев приёмки, не заявление о выполнении. Детальные изменения кода определяются после чтения соответствующих интерфейсов.

## Цель и продуктовый контракт
Автономный сервис после однократного подключения репозиториев, Jira/GitHub и runtime-источника сам выдаёт предварительный инсайт в задаче и уточнённый результат по PR. Постоянный оператор или разметчик не входит в продукт.
Опора: docs/product/pilot/OFFER.md, BACKLOG.md; docs/implementation/autonomous-mvp/STATUS.md, READINESS.md; PR #62–#66.

## Исходное состояние, проверенное 28.10
- Main для замороженной серии: f4e6ab7906fe5db5fbce9700bcad6547757bb63e. PR #62–#65 слиты 27.10; #66 открыт.
- 2Б run 40566128227: offline success; три model phase jobs waiting.
- Cloud.ru lock-test 40566211910 waiting; plan 40566228282 пока без jobs.
- Релиз f5c0c36 опубликован; run 40564865262: release и install-published success.
- Readiness 6-r3: синтетика без модели 70/70, человеческие минуты и comparison INCOMPLETE. Это не готовый MVP.
- Состояние ВМ в этом чате заново не проверялось.

## Ответственность и правила
Codex сам читает код, реализует исправления, готовит PR, проверяет доступные тесты/CI, разбирает результаты и поддерживает этот план. Он не ограничивается выдачей промптов.
Локальный Codex — исполнитель конкретных команд SSH, gh dispatch и операций, которых нет у текущего инструментария. Передаётся готовый комплект, не вся исследовательская задача.
Daniil/swan-Dive — разрешение доступа, одобрение защищённых сред и человеческая проверка пользы. Swan-Dive также независимый автор задач/оценщик.
Никаких новых расходов автоматически. Условия старых серий не расширяются молча. Main не двигаем до завершения/явной остановки 2Б на exact SHA.
Работа в отдельных ветках; код/документы на main во время заморозки не меняются. Изменения ВМ выполняет один оператор.
При недоступной проверке статус BLOCKED/NOT_RUN с причиной. Подготовка кода не равна live-приёмке.
Человеческие минуты не генерируются моделью.

## Пачки
| ID | Результат | Что выполняет Codex здесь | Внешняя операция | Приёмка | Зависимость |
|---|---|---|---|---|---|
| M1 | Модельный профиль либо обоснованный режим без модели | Проверить live-run, manifest и бюджет; разобрать transport/development/evaluation/report; исправить подтверждённые ошибки протокола в отдельной ревизии при необходимости; проверить путь от model hypothesis к пользовательскому результату в core_analyzer/jira_impact/results; подготовить код интеграции и PR, актуализировать #66 после серии | Одобрение среды человеком; dispatch через локальный gh при отсутствии инструмента здесь | Окончательный вердикт модели; профиль проверяется сервисом; полезный вклад/ограничения видны пользователю; деградация проверена | Первая |
| M2 | Живой путь Jira → PR → один актуальный комментарий | Проверить и исправить коннекторы/очередь/публикацию; подготовить webhook HTTPS-конфигурацию и сценарий e2e; проверить дубликаты, перестановку событий, новый head, отказ API, собственный комментарий; разобрать реальные результаты и внести исправления | Человек подключает App/Jira; локальный исполнитель применяет конфигурацию и отправляет пробные события | Задача и PR без ручного анализа получают один актуальный результат; старый head не публикуется | Подготовка параллельно M1/M3, live после M3 |
| M3 | Установленный автономный релиз с восстановлением | Проверить box/provisioning/lock/plan; сравнить reuse существующей ВМ с новой; подготовить точные release/config/update/backup/restore/rollback; исправить код; разобрать измерения и сверить установленное | SSH, lock-test/plan/apply; новый ресурс только по одобренному плану и бюджету | Чистая установка/reboot/update сохраняют очередь и историю; rollback через matching backup сохраняет последующую историю в safety copy без автоматического слияния; измерены ресурсы и реальные минуты подключения | Параллельно M1; выбор model profile до model-enabled установки |
| M4 | Независимое покрытие незнакомого проекта | Исправить известный README/route intent defect; создать регрессии; подготовить подключение кода и access logs/OTel; проверить identity/freshness/revocation; реализовать необходимые адаптеры в ограниченном объёме; оценить независимые случаи | Swan-Dive даёт существующий проект, runtime и ожидаемые последствия, созданные независимо от реализации; локально подключаются источники | Кодовые/runtime-only связи и неизвестность корректны; изменения и отзыв доступа обновляются; не требуется ручное ведение графа | После M2 live; подготовка раньше |
| M5 | Решение о полезности и необходимых UX-исправлениях | Подготовить сравнение с coding agent при одинаковых доступах, инструменты замера и анализ; реализовать исправления комментариев/просмотра оснований по наблюдениям; учитывать подготовку и сопровождение | Люди выполняют задачи, записывают время, оценивают действия и ошибки | Измерены качество, FP/FN, действия и полный труд; есть решение о границах выпуска, без фиктивных бизнес-метрик | M2/M4 |
| M6 | Принятый MVP-релиз и предложение клиенту | Свести readiness, подготовить release PR и runbook, проверить поставку; обновить предложение и существующую презентацию (#49), создать проверенные PPTX/PDF и единый итоговый отчёт | Локально финальная установка; владелец принимает коммерческое предложение | Новый пользователь подключается и получает заявленный результат по инструкции; готовые артефакты и честные ограничения | После предыдущих |

## Checkpoint M4-A + M2-A — 28.10.2026

Позднейший checkpoint уточняет начальную очередь ниже: M4-A OFFLINE PARTIAL, вся M4
UNVERIFIED; M2-A PREPARED, M2 LIVE BLOCKED; MODEL OFF. #72 head `f72c01827f203c2df46df9dc8e9071673df430e0`,
предметное ревью + 883 LOCAL PASS и Core/HTTP/evidence/box CI SUCCESS. Дополнительные
профильные основания/legacy knowledge и documentation edit исправлены с RED→GREEN.
Main `d5e25fd`; #71 M3 `5ac9dbb` не затронута, virtual merge с #72 чистый, ack явно
запрошен и пока не получен. До ack #72 не сливается; новый release/pin не готовится
без отдельного согласования M3 и Published Asset verification. M3 HOST STOPPED /
SUPPORT INVESTIGATION — по сообщению её PR, не наша новая проверка Cloud.ru.

M2-A исполнила настоящий GitHub read API inventory и разрешённую попытку create (403
integration capability). Затем владелец создал private pilot repos/Connector access;
исполнитель загрузил все 6 веток, настоящие API/Git SHA/bytes PASS. IDs 1437522215/1437522551.
Подготовлены два авторских Git bundle, тестовые branches,
LOCAL real HTTP 60→20→60, production-schema/fail-closed config, App/Jira/secret/webhook
параметры и LIVE/cleanup. App создана/установлена владельцем (App 5515659, installation 176298402 из UI; bot 349497413
подтверждён API). GitHub-only candidate schema PASS, App JWT/token exchange BLOCKED без PEM.
Connected service/Jira/HTTPS отсутствуют. Jira пока BLOCKED без повторного запроса всех настроек. Единый список
и evidence: `docs/implementation/autonomous-mvp/m2-a-2026-10-28/README.md`.
Смена профиля не запускает автоматически повторную публикацию unchanged resources;
для будущего upgrade уже используемого сервиса нужна отдельная проверка reanalysis.
Историю не удаляем. Новая приёмка начинает отдельный согласованный test installation/state.

## Контрольные риски
- Модель работает, но её вывод не даёт пользователю дополнительной полезности: M1/M5 проверяют выход, не только вызовы.
- Повторные/запоздалые события публикуют старый результат: M2 проверяет настоящие endpoints.
- Восстановление теряет данные или требует постоянного оператора: M3.
- Совпадение маршрутов/адресов, stale runtime или отзыв доступа дают ложную связь: M4.
- Качественная синтетика выдаётся за пользу, человеческая работа скрывается: M4/M5/M6.

## Очередь и статусы
- [x] M1 — DONE / MODEL OFF: серия 2b-r1 закрыта после transport, все три модели DISABLED. Код #68 слит как `1ef7eaca9b66256478022945eef7f8b205571dd2`, проверенный head `6d6d7d1a6f52e5eb619c7d580f577e892cfe3086`. CI: 838 основных + 152 runner-теста; HTTP-демо, evidence и systemd приёмка PASS. 55 целевых publication/qualification/result тестов прошли; повторное независимое агентное ревью без Important/Critical. Реальной модельной квалификации нового кода нет; M1 принят как обоснованный режим без модели. #66 актуализирован. Доказательства: docs/implementation/autonomous-mvp/m1-2026-10-28/README.md.
- [ ] M2 — PARTIAL / LIVE BLOCKED: [PR #69](https://github.com/rengalaxies/agent/pull/69), код `7a624ed431ac2c3d7b8488985ca3cdc6e34147c7`; подтверждённые ошибки исправлены, 19 новых проверок и 9/9 условий LOCAL core-сценария PASS. Владелец подтвердил отсутствие установки M3, тестовых App/Jira/HTTPS/credentials. Модель OFF. Отчёт: `docs/implementation/autonomous-mvp/m2-2026-10-28/README.md`; точный handoff M3 рядом. До LIVE пачка не DONE.
- [ ] M3 — TODO / READY FOR CONNECTION: актуальный релиз M1+M2 `agent-service-0.1.0-g14e65e8affe3` проверен после публикации с systemd, pin #70. Дальше — выбрать/обследовать хост, определить тестовые App/repositories/Jira, доставить credentials, подготовить HTTPS, установить и пройти LIVE. Нужен новый plan вместо pending f4e6ab7; без apply до конкретного плана и бюджета. Единый список в M2/HANDOFF-M3.md.
- [ ] M4 — TODO: кодовая регрессия и запрос независимого проекта.
- [ ] M5 — TODO.
- [ ] M6 — TODO.

На каждом завершённом этапе обновлять строку, SHA, PR, фактически выполненные проверки, следующий шаг и блокер. Пачки выполняются самим Codex в текущем чате; пользователь не обязан передавать каждый промежуточный ответ другого агента.
Начальная версия плана зафиксирована отдельно от main, чтобы не ломать серию 2Б.

## Checkpoint M1 — 28.10.2026

51 live-запрос в исходной серии; известная оценка 26,395201 ₽, ledger с unknown worst-case 30,287335 ₽, фактический биллинг не измерен. Оригинальные manifests/report/ledgers не переписывались. Заморозка main для закрытой 2b-r1 больше не нужна. Новый код не имеет live-квалификации; старые current-code checks должны отказывать. ВМ, секреты и релиз не менялись. Следующий исполнительский шаг Codex после CI/merge — M2 inventory, параллельно подготовка M3 в режиме без модели.

Финальная проверка M1: [Core](https://github.com/rengalaxies/agent/actions/runs/40668612946), [HTTP demo](https://github.com/rengalaxies/agent/actions/runs/40668612932), [evidence](https://github.com/rengalaxies/agent/actions/runs/40668612994), [systemd box](https://github.com/rengalaxies/agent/actions/runs/40668612955) — все SUCCESS на финальном head #68. Сервисный qualification.check отклоняет настоящий report для каждой модели как model_not_qualified. Человеческая/клиентская полезность и финальная установка на Cloud.ru этим не подтверждены.

## Checkpoint M2 — 28.10.2026

Репозиторий/инструменты обследованы, исходная main `47b774d`; GitHub connector и gh доступны,
Jira/App service credentials не настроены. Lock-test 40566211910 waiting, plan 40566228282 pending;
apply и ВМ не запускались. dm-p1-ui не считается M3. Основной agent не тестовый контур.
Нужны выбор/обследование хоста, согласованные тестовые repositories/project и App installation,
доставка секретов штатным способом, DNS/TLS/webhook и фактически установленный актуальный релиз.
Старый pin f5c0c36 не включает M1/M2; выпуск и скачивание нового asset проверяются существующим
release workflow до нового pin. Все действия владельца собраны в HANDOFF-M3.md.

Pre-send/post-send checks не дают атомарности с внешним API: старое тело может успеть
появиться; LOCAL подтверждает stale notice → новый result и durable recheck при ошибке.
Без API/worker верхней границы окна нет; live длительность не измерена.

### M2 integration checkpoint

#69 слит как `14e65e8affe3b64a9ceb647f537e8af6ff7a1138` (head `f488380b9a003368b365cf2b52c5e98adeab4ca8`);
Core CI 40692584761: 858 + 152 PASS, box 40692584737: 11/11 systemd PASS.
Релиз `agent-service-0.1.0-g14e65e8affe3`, archive sha256 `95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`,
run 40693796501: release + install-published SUCCESS, опубликованный asset VERIFIED
и установлен на CI. Актуальный pin — [#70](https://github.com/rengalaxies/agent/pull/70); LOCAL pin tests 58 PASS, 1 skip без Terraform. Не повторять выпуск этого
тега; M3 нужен новый plan вместо старого pending f4e6ab7 и фактическая установка.
M2 **PARTIAL / LIVE BLOCKED**, MODEL OFF; ВМ и настоящие App/Jira/HTTPS не проверены.

## Checkpoint программы закрытого пилота — 29.10.2026

Исполнитель Claude (аккаунт swan-Dive) по поручению Daniil от 29.10. Строки выше не
переписаны. Индекс результата: `docs/implementation/autonomous-mvp/pilot-2026-10-29/README.md`.

| Пачка | Подэтап | Статус |
|---|---|---|
| M2 | Понятный переход после исправления, воздержание без «нет данных» (#75) | DONE LOCAL, слит `731fa80` |
| M2 | Проверка App-аутентификации без ВМ (#74) | PREPARED; настоящий запуск BLOCKED без PEM в environment |
| M2 | LIVE GitHub/Jira | BLOCKED |
| M3 | Новый релиз с #72 | NOT_RUN: нет ack M3 |
| M3 | Установка на хост | BLOCKED: хост остановлен, разбор у поддержки |
| M4 | Переход profile 4 → 5 на существующем state | DONE LOCAL с #76; на установке NOT_RUN |
| M4 | Независимый проект | PREPARED: запрос данных и шаблон; NOT_RUN |
| M5 | Локальный показ с настоящим backend (#75) | DONE LOCAL |
| M5 | Протокол пилота | PREPARED; пороги ждут согласования владельца |
| M5 | Измерение пользы | UNVERIFIED |
| M6 | Предложение, колода PPTX/PDF, подключение и выход | DONE как материалы; условия пилота не утверждены |

#74, #76, #75 слиты 29.10 с подтверждения владельца (main `731fa80`). Следующий шаг:
#72 после ack M3; затем релиз и pin. MODEL OFF.

## Самостоятельное исполнение 30 октября и доступы

Codex возобновил реализацию на main b9e7cc9: исправляет справедливость выдачи
фонового пересчёта, начальный бюджет задания и выбор действительно показанного
результата для сравнения комментариев. ВМ, pin и модель не меняются. План и
RED/GREEN: docs/superpowers/plans/2026-10-30-pilot-queue-and-result-history.md;
отчёт с матрицей доступа: docs/implementation/autonomous-mvp/pilot-queue-2026-10-30/README.md.
37 целевых проверок PASS; финальный Core/box CI и интеграция проверяются в PR.

Без ВМ доступны код/регрессии/CI, совместимость №72, локальный UI/показ,
пилотные материалы, независимые случаи и их оценка с участником. App probe
не требует ВМ, но требует PEM в доверенном environment и его одобрения.
Согласование №72 и выпуск/проверка нового релиза тоже не требуют ВМ.
Установка, loaded SHA, restart/reboot, backup/restore и откат требуют
восстановленного доверенного хоста и одного оператора M3. Для настоящих
webhooks нужен работающий сервис и HTTPS/App/Jira; SSH не нужен каждому
тестирующему. M2 LIVE и M3 до этого не закрываются.

## Локальный путь участника — 30.10.2026, PR #79

Отдельная ветка от 59529b4 после #78. Existing HTTP UI, worker, guarded Docker runner;
не новая копия интерфейса. Изменение → потребитель → основания → запуск → исправление →
повторная проверка/история. Исправление stale evidence при graph failure; новая авторская
HTTP matrix и отдельные ожидания. Известные ошибки #72 не перенесены и не объявлены PASS.
LOCAL проверки частичные до потери среды; восстановленный код квалифицирует CI точного
SHA #79. Пока CI/ревью не завершены — не принято. MODEL OFF, ВМ/релиз/pin/секреты неизменны.
Человеческая оценка/реальный проект/M2 LIVE не выполнены. Сценарий и параметры разговора:
docs/product/pilot/LOCAL-SHOW.md. Полный отчёт и таблица работ без ВМ:
docs/implementation/autonomous-mvp/pilot-review-2026-10-30/README.md.

Продолжение checkpoint #79 после восстановления среды: чистое дерево приложения
1c8e44b проверено LOCAL Docker/Chromium PASS — A 250, B 100 (Billing 250), D/E 250,
пять показов, ноль sandbox после stop; 38 backend/CLI tests и новая HTTP matrix PASS.
Документированные init/serve/run/observe/stop/reset/serve LOCAL PASS, история сохранена.
Реальные снимки до/после и JSON сохранены в pilot-review-2026-10-30/evidence.
Точный финальный head/CI/merge — PR #79; до его зелёных проверок интеграция не принята.
Это готовность технического локального показа для разговора, не готовность внешнего
пилота: participant/client/VM/external NOT_RUN, пять DEFERRED_72 остаются, MODEL OFF.

## Кандидат пилота и отдельное согласование — 30.10.2026

База этапа main e84e913 (после принятого #79). Самостоятельная ветка
codex/pilot-candidate-evidence-2026-10-30 исправляет CURRENT сохранённого demo graph/knowledge
после profile change и передачу UNAVAILABLE code source в существующий basis-reconciliation
gate; PARTIAL не подсказывает «показ завершён». Есть RED/GREEN и отрицательные контроли.

Отдельное объединение #72 f25e82f с main и новыми fixes: profile6, PENDING_APPROVAL.
Пять DEFERRED_72 заново FAIL на main и PASS в кандидате. Новая ошибка прямого setattr
в положительном AST исправлена только в pending ветке; profile4/5 bases требуют пересмотра.
Явного M3 ack в #71/#72 нет; их refs, pin/release14e и ВМ не изменялись. Предложение
и точные финальные SHA/CI находятся в собственных PR, интеграция #72 до ack запрещена.

LOCAL: full core/service 917 PASS + runner 152 PASS; новый HTTP/intent/schema corpus;
actual old/new processes 4→6→4→6, unavailable
source, restart после ANALYZED, fresh head, те же 3 comment IDs и история; build twice
identical/manifest VERIFIED; настоящий Docker/Chromium UI. Последний PARTIAL hint проверяет
финальный CI. Existing #76/#78 basis reconciliation действительно переиздаёт unchanged
resources; при source failure basis checkpoint теперь ждёт восстановления. DB/API не
атомарны, outage/stale window не ограничено SLA. Целевой rollback старого release14e NOT_RUN.

Полный отчёт: docs/implementation/autonomous-mvp/pilot-candidate-2026-10-30/README.md.
Handoff M3 рядом, протокол участника docs/product/pilot/PARTICIPANT-SESSION.md.
MODEL OFF. M2 LIVE/M3 BLOCKED, независимая M4/M5/клиентская полезность UNVERIFIED;
participant/VM/external NOT_RUN. Green CI не снимает PENDING_APPROVAL и не подтверждает LIVE.


## Checkpoint 31.10.2026 — интеграция profile6

По явному поручению владельца техническое согласование M3 выполнено здесь. #81 exact
head e217599 слит в 5f60a0fb88369f1e1e7da00b960f6b6ed462c614; дерево совпало с
CI-проверенным. #72 автоматически merged через историю. 48 targeted, 6 boundaries,
HTTP matrix и real process migration PASS; семь CI runs exact head success.
[Протокол](../../implementation/autonomous-mvp/profile6-integration-2026-10-31/README.md).

Прежний gate согласования кода снят. Отдельный recovery gate остаётся: rollback при
schema-compatible state делает release_only и запускает старый writer; downgrade
profile6→release14e не квалифицирован. Следующая работа без ВМ — проверить matching
backup/recovery с контролем публикации, затем новый published asset. Установка после
восстановления хоста отдельно. Participant/client/VM/external NOT_RUN; MODEL OFF.


## Recovery и выпуск — 31.10.2026, #83

Работа без ВМ от main 89391a6. Воспроизведён реальный unsafe release_only к published
release14e; новый manager использует schema + exact semantic contract, matching backup/config,
переживает прерывания, не оставляет orphan SQLite writer и удерживает publisher до сверки.
LOCAL 14e→candidate→restored14e→candidate, API/source outage, exact duplicates/restart PASS;
71 box, 917 core/service, 152 runner PASS. Финальные CI exact head и выпуск связывает #83.
[Единый отчёт и матрица](../../implementation/autonomous-mvp/release-recovery-2026-10-31/README.md),
[операторский handoff](../../implementation/autonomous-mvp/release-recovery-2026-10-31/HANDOFF-M3.md).

Gate прежнего CLI не снимается: старый неизменяемый box/launch не получает новую защиту.
Matching restore возвращает старый snapshot; новая локальная история сохраняется в safety
copy, не обещается автоматическое слияние. После принятия main — штатный release workflow
с expected_main_sha, build twice, download/verify/install-published и exact recovery-published.
Deployment pin и #71 не меняются. M3 target VM/reboot и M2 external LIVE отдельно NOT_RUN;
модель OFF, participant/client benefit UNVERIFIED. Действия владельца/M3 сведены в handoff.
