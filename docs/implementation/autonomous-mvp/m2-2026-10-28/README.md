# M2 — Jira → PR → актуальный результат, 28.10.2026

**PARTIAL / LIVE BLOCKED. MODEL OFF.** Код и локальная приёмка готовы; настоящие
Jira/GitHub endpoints не проверены. Владелец подтвердил отсутствие установки M3,
согласованных тестовых repositories/App installation/Jira project, credentials и HTTPS.
Демо dm-p1-ui не обследовано как M3. Новые ВМ, облачные ресурсы и модельные вызовы
не создавались. Основной agent используется только для разработки и PR.

Изменения: [PR #69](https://github.com/rengalaxies/agent/pull/69).
Исходная main `47b774d16ac121a7e03c17c96ff1f78775c3538d`; код исправлений и тестов
`7a624ed431ac2c3d7b8488985ca3cdc6e34147c7`. [Хеши файлов](code-files.json).
Фактически установленная версия M3: **NOT_INSTALLED / NOT_VERIFIED**.
Старый release pin `f5c0c36` не является версией M1/M2.

## Подтверждённые дефекты и регрессии

`tests/service/test_m2_regressions.py`: 18 воспроизведений ошибок и одна положительная
проверка installation/ping. Первые 13 тестов красные на исходном коде: [исходный
прогон](regressions-before.log). Дополнительно исправлена [ложная Jira ссылка внутри слова](regressions-before-link.log);
несколько полных ключей остаются списком. Ещё [2 ошибки](regressions-before-extra.log) найдены
при ревью восстановления, ещё [2 ошибки](regressions-before-auth.log) — при ревью API.
[Окончательный прогон](regressions-after.log): 19/19 PASS. Signed malformed payload
раньше мог давать HTTP 500; traceback в исходном логе — результат воспроизведения.

| Ошибка | Исправление |
|---|---|
| HMAC корректен, но событие из другой App installation | ID из App auth сверяется до enqueue; repository allowlist и Jira project проверяются отдельно. Токеновый режим не выдаётся за App; ping остаётся допустимым |
| Движение base при том же head сохраняло прежний вывод | Версия PR включает оба SHA, target branch и явные Jira keys; freshness проверяет те же входы |
| Ошибка GET после успешного внешнего POST/PATCH скрывалась | Notice `postsend_check_failed` + durable synthetic recheck, обычные bounded retries/reconciliation; повторный POST для проверки не нужен |
| Усыновление комментария с тем же digest пропускало post-send проверку | Тот же post-check выполняется и для найденного комментария после потерянного ответа |
| Ограниченные листинги считались полными | При достижении потолка GitHub/Jira reconciliation/comments — видимый отказ, cursor не двигается, blind create запрещён |
| Jira outage >7 дней обрезал восстановление | Query использует весь интервал сохранённого checkpoint с overlap, без семидневного clamp |
| Известная Jira-задача удалена/перемещена и пропала из search | Reconciliation перечитывает известные отсутствующие в выборке ресурсы; fetch проверяет project и доступ |
| Ключ ORD-12 внутри ORD-12suffix считался ссылкой | Проверяются границы полного ключа; allowlist проектов и множественность сохраняются |
| Force-push A → B → A терялся из-за уже виденного synthetic ID | Synthetic ID учитывает текущее поколение/closed; предыдущая версия не является вечным dedup ключом |
| Изменение после 20 000-го символа Jira не меняло версию | Digest полных смысловых полей, ограничение display отдельно, `jira_fields_truncated` виден как gap |
| Постоянный 422 на ingest/prepare повторялся; 401 prepare крутился без паузы | Постоянный отказ сразу FAILED/notice; auth pause 900s; Retry-After учитывается при подготовке анализа |

Первая Jira discovery ограничена последними 7 днями; давние задачи до начала
наблюдения требуют согласованного импорта/изменения. Потолки одного прохода: GitHub
4 × 50 PR, Jira 20 × 100 задач, комментарии 10 × 100; достижение потолка теперь
видимо блокирует неполную выборку, а не доказывает её полноту.

Очередь, publisher и коннекторы сохранены; схема SQLite остаётся 1. Нового брокера,
оркестратора, механизма reconciliation или горизонтальной обработки не добавлено.

## Уровни доказательств

| Уровень / проверка | Результат | Граница |
|---|---|---|
| LOCAL: исходный сервисный набор на main | PASS, 141 тест | Настоящий HTTP на 127.0.0.1, scripted analyzer и отдельные тесты настоящего core |
| LOCAL: регрессии M2 | PASS, 19/19 | Воспроизведения исходных дефектов, фальшивые GitHub/Jira HTTP endpoints |
| LOCAL: понятный сценарий, настоящее ядро Orders/Reporting | PASS, 9/9 условий | [Артефакт](local-scenario.json): event/request ID, Jira version, полные base/head, тела комментариев и history; synthetic repositories/tasks |
| LOCAL: runner без внешней модели | PASS, 152 теста | Тесты runner, не модельная квалификация |
| LOCAL: box unit tests | PASS, 46 тестов | Не установка на ВМ |
| LOCAL: lint F401/F811/F841 | PASS | Версия ruff 0.17.1 как в CI |
| LIVE: Jira → PR → fixed head, дубли, API error, self-loop, race/restart | NOT_RUN / BLOCKED | Нет установки M3 и согласованного контура; [пустая форма доказательств](live-record.template.json) |

Общий LOCAL набор на исходном исправлении `4a23d7c54f1128cd6c238f58f944df6c129af035`: **857 тестов PASS** (230,358s машинного времени).
[Машинный реестр](validation.json), [полный лог](full-tests.log), [runner](runner-tests.log),
[box](box-tests.log). Дополнительные установки/некорректный запуск без PYTHONPATH
не считались успешными проверками; итоговый запуск использовал env как в Core CI.
Сеть/loopback сначала были недоступны в sandbox, тесты повторены с разрешёнными
локальными сокетами; первый post-change прогон был прерван перезапуском окружения.

Актуальный кандидат `agent-service-0.1.0-g7a624ed431ac-linux-x86_64-cp312` собран локально
дважды с одинаковыми байтами; sha256
`9d665121216a54589aed02f319fa83c46ddebc6ed7bf19de80273a64b637f2ed`,
manifest verify PASS. [Сборка](release-build.json), [повтор](release-build-second.json),
[verify](release-verify.json). Это не установленная версия M3 и не обновлённый cloud pin.
Финальные целевые regression/flow/core-scenario проверки на `7a624ed`: 22 PASS
([лог](final-targeted-tests.log)); regex-правка после общего набора проверяется также
полным CI финального head. Финальный CI: 858 основных + 152 runner-теста и 11/11 systemd-сценариев PASS (см. ниже). Зелёный CI не закрывает LIVE/M2.

## Что реально показывает пользовательский сценарий

Локальная задача ORD-12 даёт предварительный вывод по указанной операции и ограничения.
PR с явным ключом ORD-12 меняет default 100 → 20; статический путь Reporting и основания
по Git commit/path видны отдельно от гипотезы. Следующий head возвращает поведение 100
и сохраняет только README-изменение: в том же comment ID больше нет прежнего риска,
текущий ответ `no_supported_delta`. Инъекция HTTP 503 на PATCH восстанавливается.
Повторы тех же delivery ID и старый payload с новым ID не дают новых jobs/записей.
Comment events не запускают цикл; неоднозначный GET /orders (Orders/Billing) даёт
`intent_unclear`. Детерминированность явно указана в пользовательском комментарии.

Это исполненный тест настоящего core, но данные и endpoints локальные. Сервис
**не запускал тест потребителя**: статически найденная связь/риск не называется
измеренной поломкой. Фактический PASS сценария записан в evidence, отдельно от текста
предварительной гипотезы и статической связи. Jira ↔ PR: только явные разрешённые
project keys в title/branch, без угадывания по названию сервиса; несколько ключей
сохраняются списком, без выбора единственного. Содержимое Jira по ссылке из PR не
подтверждается этим механизмом, наличие ключа не доказывает реализацию задачи.
Основания в комментарии — проверяемые refs commit/path/line; UI не запускает их
повторную проверку и не превращает их в подтверждение runtime-теста.

## Гонка «проверили → ресурс изменился → отправили»

БД и внешний API **не атомарны**. Pre-send GET выполняется до поиска комментария и
POST/PATCH. Внешний head/поля могут измениться после GET. Старое тело тогда реально
принимается внешним API: тест `NewHeadTest.test_new_head_during_send_is_replaced_by_a_stale_notice_and_then_the_new_result`
фиксирует последовательность старый result → stale notice → новый result, с одним POST.
M2 добавляет post-check также для adopted/unchanged comment и durable recheck при ошибке GET.

После подтверждённого write: receipt в SQLite → post-send GET. Если версия другая,
открывается поколение; при следующем worker step старый комментарий заменяется stale
notice, затем новым результатом. При ошибке GET уже подтверждённый write не повторяется:
notice и synthetic event переживают restart, обычный ingest перечитывает ресурс.
При падении **до** receipt SENDING восстанавливается как UNKNOWN, author+marker/digest
находят существующий комментарий. При падении **после** receipt и **до** post-check
нового outbox события ещё нет; webhook или очередная periodic/startup reconciliation
обнаружит изменение. Это окно сохраняется и честно не названо exactly-once.

В здоровом процессе окно включает внешний write, контрольное чтение и доставку stale
notice; численного SLA нет. При потерянном webhook/crash — до следующей reconciliation
(по умолчанию 900s) плюс обработка/backoff. При недоступном API, запрете публикации,
задержанной индексации комментариев или остановленном worker верхняя граница **не
гарантирована**: внешнее старое тело нельзя отозвать транзакцией нашей БД. После возврата
доступа и работы worker восстанавливается актуальный результат. Закрытый/удалённый
ресурс прекращает новые публикации; исторический комментарий с прежними версиями
не удаляется. Установленную LIVE длительность этого окна не измеряли.

Идемпотентность create зависит от author+marker и видимости списка. После неизвестного
create сервис ждёт `create_settle_seconds` (по умолчанию 30s); бесконечно задержанная
видимость внешнего API может нарушить отсутствие дублей. Потолки листинга теперь
fail closed. Второй долгоживущий worker не является поддержанной архитектурой;
истёкшая lease не запрещает уже отправленный внешний запрос старого процесса.

## Повторить и подключить

```bash
PYTHONPATH=.:src:tests:tools python -m unittest discover -s tests/service -t . -v
PYTHONPATH=.:src:tests:tools python -m tests.service.test_m2_scenario --output work/m2/scenario.json
PYTHONPATH=.:src:tests:tools python tests/graph/ci_unittest.py discover -s tests -v
```

[Готовый handoff M3](HANDOFF-M3.md): точный build/release, конфигурация без секретов,
GitHub App/Jira/HTTPS, status/журналы, LIVE-порядок, rollback, единый список владельца.
Ручные действия здесь: чтение/ревью кода и CI, запуск локальных стендов, правки,
commit/PR и подготовка конфигурации/инструкций. Действий человека в live контуре не
выполнялось. Человеческие минуты **NOT_MEASURED**, машинное время тестов ими не считается.

## Ревью

Ревью кода и diff выполнено основным исполнителем: проверены derivation installation ID
из настоящего App auth, одинаковый состав PR version в webhook/fetch, полный digest Jira
при ограниченном display, durable recheck/UNKNOWN adoption, cursor при pagination error,
повтор A → B → A, retry pause и видимые постоянные ошибки. Существенные найденные дефекты
исправлены с исходными воспроизведениями. Не заявляется независимое агентное ревью.
Ограничения single worker, неизвестного внешнего write и недоступного LIVE сохранены явно.

## Интеграция и поставка

[PR #69](https://github.com/rengalaxies/agent/pull/69) слит: merge **`14e65e8affe3b64a9ceb647f537e8af6ff7a1138`**,
проверенный head `f488380b9a003368b365cf2b52c5e98adeab4ca8`. На этом head
[Core CI](https://github.com/rengalaxies/agent/actions/runs/40692584761) — **858 + 152 PASS**,
[systemd box](https://github.com/rengalaxies/agent/actions/runs/40692584737) — **11/11 PASS**.
[Сохранённый systemd report](ci69-systemd-acceptance.json), [manifest](ci69-manifest.json)
и [core summary](ci-core-summary.txt). Установленный в PR CI commit — синтетический
merge `db6bebfdcb721c0f2bb3da6d8217b10b873bf72e`; это не SHA установленного M3.
Ранние runs на промежуточных heads не используются как финальная приёмка.

[Новый релиз](https://github.com/rengalaxies/agent/releases/tag/agent-service-0.1.0-g14e65e8affe3)
из main `14e65e8affe3b64a9ceb647f537e8af6ff7a1138` заменяет старую поставку f5c0c36:
`agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312`. Archive sha256 **`95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`**.
[Release workflow](https://github.com/rengalaxies/agent/actions/runs/40693796501): `release`
и `install-published` SUCCESS; скачанный опубликованный asset установлен с systemd,
`fresh_install` и `end_to_end_on_installed_release` PASS. [Отчёт](ci-published-install.json).
[Независимое скачивание/manifest verify](published-verify.json) также VERIFIED.
Pin в `infra/cloudru/box/release.json`: [PR #70](https://github.com/rengalaxies/agent/pull/70).
Проверка pin: LOCAL 58 tests PASS, 1 skip без Terraform ([лог](pin-tests.log)). Старый pending plan
на f4e6ab7 не подтверждает этот pin; M3 нужен новый review/plan, apply не выполнялся.

Все эти установки — **CI**, модель OFF. Фактическая установка на dm-p1-ui/иной VM,
настоящие Jira/GitHub webhooks, live race и человеческие минуты остаются NOT_RUN /
NOT_MEASURED. **M2 PARTIAL / LIVE BLOCKED**, не DONE.
