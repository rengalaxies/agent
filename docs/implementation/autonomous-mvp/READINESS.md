# Готовность автономного MVP

Оценка по фактам из [STATUS.md](STATUS.md) на 28.10.2026. Техническая готовность и польза для
команды разделены. Полная готовность требует всего списка ниже; пока хоть один пункт не
проверен live, итог ограниченный.

## M2 — PARTIAL / LIVE BLOCKED, 28.10.2026

[PR #69](https://github.com/rengalaxies/agent/pull/69), код `7a624ed431ac2c3d7b8488985ca3cdc6e34147c7`:
Общий LOCAL набор 857 PASS, runner 152 PASS, box units 46 PASS;
19 регрессионных/положительных проверок и локальный настоящий core-сценарий 9/9 PASS.
Это LOCAL, не настоящие endpoints. Гонка GET → изменение → POST/PATCH реально допускает
устаревшее тело; post-check/reconciliation исправляет его, при outage время не ограничено.
[Отчёт и evidence](m2-2026-10-28/README.md), [готовый комплект M3](m2-2026-10-28/HANDOFF-M3.md).
Владелец подтвердил отсутствие установленного M3 и согласованных App/Jira/HTTPS.
Установленная версия NOT_VERIFIED; старый pin f5c0c36 не включает M1/M2. Модель OFF.
M2 остаётся открытым до LIVE Jira → PR → новый актуальный результат с дублями, новым
head, API error и self-loop; зелёный CI не меняет этот вердикт.

## Текущий вердикт

**NOT READY: детерминированный сервис проверен на синтетике и локальных стендах, модель не прошла транспортный допуск; коробка
в облаке, живая интеграция и польза для компании не проверены. Для следующих пачек — модель OFF.**

| Слой | Состояние | Доказательство и граница |
|---|---|---|
| Детерминированный сервис (Jira, PR, граф, очередь, один комментарий) | проверено на L1/L2 | 6-r3 held-out без модели 70/70, technical и quality PASS (`batch-6.md`); исправления D13 и прежние регрессии. Результат 6-r3 относится к старому коду (`f4e6ab7`), не к обновлённому продукту. M1 (#68) слит как `1ef7eac`. M2 (#69) — merge `14e65e8`: финальный CI 858 основных + 152 runner-теста, 11/11 systemd PASS; новый локальный core-сценарий 9/9 PASS. Это не LIVE Jira/GitHub. Формулировки 6-r3 писал тот же исполнитель |
| Модельная автономность | допуск не пройден; модель OFF | 2Б transport завершён на `f4e6ab7`, run 40566128227: GPT 0/3, Qwen Coder 0/3, Qwen 3.6 1/3 error-free циклов при требуемых ≥2. Все DISABLED; development/evaluation и model-enabled readiness NOT_RUN. Публикационные исправления #68 слиты после офлайн/CI-проверок, без новой live-квалификации. [Доказательства](m1-2026-10-28/README.md) |
| Коробочная поставка: install, update, rollback, restore | проверено на раннере GitHub с systemd | M2 #69: 11/11 на финальном head `f488380`; актуальный релиз `agent-service-0.1.0-g14e65e8affe3` содержит M1/M2. Run 40693796501: опубликованный asset скачан, VERIFIED и установлен с systemd (`fresh_install`, `end_to_end_on_installed_release` PASS); pin #70 заменяет старый f5c0c36. Установки M3 нет |
| Cloud.ru: одна ВМ | не проверено | код в `main`; lock-test и plan запущены 27.10 и ждут одобрения сред, apply не запускался, ничего не создано |
| Живая интеграция (GitHub App, Jira, runtime-источник клиента) | не проверено | нет тестовых ресурсов, разрешения публикации и доступа к runtime-источнику; локальные HTTP-стенды это не заменяют |
| Сравнение с обычным агентом | не проверено | ворота comparison INCOMPLETE: живой baseline не запускался; `naive-search` только нижняя проверка pipeline |
| Человеческие минуты подключения и работы | не измерено | ворота human INCOMPLETE: 0 из 70 записано; машинное время и отсутствие вмешательств не считаются минутами человека |
| Польза для компании | UNVERIFIED | нет корпоративной истории изменений, реальных потребителей и FN; синтетика её не заменяет |

70 из 70 в 6-r3, 65 из 65 в 6-r2 и 47 из 60 в 6-r1 получены на разных корпусах по разным
правилам и не образуют ряд улучшений на неизменном benchmark.

После M1 код изменён: оригинальные 2b-r1/6-r3 сохраняются как замороженные свидетельства;
их current-code manifest checks намеренно отказывают. Тесты целостности истории не являются
новой live-приёмкой. Для новой live-серии нужна отдельная ревизия и бюджет.

### M2 integration checkpoint

#69 слит как `14e65e8affe3b64a9ceb647f537e8af6ff7a1138` (head `f488380b9a003368b365cf2b52c5e98adeab4ca8`);
Core CI 40692584761: 858 + 152 PASS, box 40692584737: 11/11 systemd PASS.
Релиз `agent-service-0.1.0-g14e65e8affe3`, archive sha256 `95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`,
run 40693796501: release + install-published SUCCESS, опубликованный asset VERIFIED
и установлен на CI. Актуальный pin — [#70](https://github.com/rengalaxies/agent/pull/70); LOCAL pin tests 58 PASS, 1 skip без Terraform. Не повторять выпуск этого
тега; M3 нужен новый plan вместо старого pending f4e6ab7 и фактическая установка.
M2 **PARTIAL / LIVE BLOCKED**, MODEL OFF; ВМ и настоящие App/Jira/HTTPS не проверены.

## M4-A / M2-A — доступная подготовка, не LIVE, 28.10.2026

#72 `f72c018` после ревью: 883 LOCAL PASS; Core, HTTP demo, evidence и box CI SUCCESS.
Profile 5 инвалидирует прежние contexts/knowledge/persistent code bases с сохранением
истории. До ack M3 интеграции нет; подготовленная M3 поставка остаётся 14e65e8/profile4.
Общая M4 и клиентская полезность UNVERIFIED; это авторские регрессии, MODEL OFF.

После начального integration403 владелец создал private pilot repos и добавил Connector.
Исполнитель загрузил все 6 веток, реальные API/Git SHA/bytes PASS (IDs 1437522215/1437522551).
Это Codex Connector auth, сервисная App не доказана. Два Git bundles, реальное loopback
HTTP 60→20→60, schema/fail-closed config с независимым GitHub-only режимом, App/Jira permissions,
secret-delivery схема, LIVE/redelivery/API-error/self-loop/race/cleanup готовы.
App 5515659 / installation 176298402 получены из UI, bot ID 349497413 подтверждён API;
App JWT/read scoped repositories NOT_RUN без PEM. Jira site/project/credentials и HTTPS не назначены,
connected-to-service=false; M3 сообщает stopped host/support. **M2 PARTIAL / LIVE BLOCKED**.
[Доказательства и конкретные оставшиеся действия](m2-a-2026-10-28/README.md). Ни green CI,
ни authored HTTP fixture не засчитываются за внешний Jira → PR → обновлённый результат.

## Программа закрытого пилота — 29.10.2026

Вердикт не меняется: **NOT READY** для закрытого технического пилота. Добавлено:
пересчёт открытых ресурсов после смены основы анализа (#76, CI 865 + 152 PASS; LOCAL
переход state profile 4 → 5 обновляет те же комментарии), понятный переход после
исправления и локальный показ (#75, LOCAL), защищённый путь проверки App (#74,
настоящий запуск NOT_RUN). Релиз с #72, App auth, установка M3 и LIVE не выполнены.
Польза UNVERIFIED, MODEL OFF. [Индекс и внешние действия](pilot-2026-10-29/README.md).

## Локальный показ — checkpoint 30.10.2026

PR #79 от main 59529b4: исправляется показ старых цитат/findings при отказе загрузки
графа, уточняются версии и следующий шаг. Новая авторская матрица различает method,
origin/port/prefix/route и реальное исполнение wrapper. Это не независимый benchmark.
Известные пять границ intent/declaration/profile на main остаются DEFERRED_72;
код #72 не включён и требует отдельного согласования M3.
До сбоя LOCAL: 38 demo tests PASS, новая HTTP matrix PASS, compatibility recovery PASS.
Полный локальный Docker прогон был неполным FAIL из-за старого текстового assertion.
После потери managed executor изменения восстановлены GitHub API: приёмка требует
зелёных Checks точного финального SHA #79. Никакого LIVE/человеческого тестирования/
целевой ВМ нет. MODEL OFF. M2/M3 BLOCKED, M4/M5/клиентская полезность UNVERIFIED.
[Отчёт и риски](pilot-review-2026-10-30/README.md),
[сценарий первого разговора](../../product/pilot/LOCAL-SHOW.md).

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
