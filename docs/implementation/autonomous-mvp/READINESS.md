# Готовность автономного MVP

## M3 checkpoint — 28.10.2026: HOST STOPPED / SUPPORT INVESTIGATION

Позднее владелец сообщил: после попытки перезагрузки ВМ остановлена, инцидент передан поддержке Cloud.ru. Причина не установлена; это не reboot-приёмка M3. Операции с хостом до завершения разбора не выполняются. Ниже — предшествующие наблюдения, не текущая доступность. После восстановления обязательны новая сверка identity/host key, inventory и backup перед установкой.

Main проверен на `d5e25fde5927eca99e574b2ac82be80cd5adfe16`, новых коммитов нет.
Опубликованный архив M1+M2 скачан и проверен локально: SHA256 `95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013`,
manifest VERIFIED, code `14e65e8affe3b64a9ceb647f537e8af6ff7a1138`. Повторного выпуска нет.
В авторизованной Cloud.ru console подтверждены существующая dm-p1-ui/VM ID/FIP,
Ubuntu 24.04, 2 vCPU/4 ГБ/30 ГБ. Это параметры облака, не свободные ресурсы ОС.
TCP22 доступен; предъявленный ED25519 host key не совпал с прежним console pin.
До независимой сверки вход не выполняется; локального SSH ключа dm-p1-ui не найдено.
Полный inventory, backup, box plan/install, loaded/status/logs, restart/reboot,
backup/restore/update/rollback **NOT_RUN на Cloud.ru**. Модель OFF, демо и SG не менялись.
Настоящие App/Jira/HTTPS не готовы; минимальный box требует GitHub credentials даже без Jira.
M2 остаётся PARTIAL / LIVE BLOCKED. [Отчёт, evidence и откат](m3-2026-10-28/README.md).


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
