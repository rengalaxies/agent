# Пачка 1: интеграция и реальная серия Cloud.ru, 22 октября 2026

Интеграция завершена. Новая серия выполнена один раз на принятом `main`
`a9385c565d5471698da62987b226dcff4cbdea86`. Полный цикл прошли **2 из 6** сочетаний:
GPT OSS на Reporting и Export. Qwen — 0/3, GPT OSS — 2/3. Успешный статус Actions
означает завершение сбора всех шести результатов, а не успех всех сценариев.

## Интеграция и проверки

| Изменение | Принятый head | Merge commit |
| --- | --- | --- |
| [№28: ядро](https://github.com/rengalaxies/agent/pull/28) | `f1c4546725e759ffc06ca0281f7103132dbcfe73` | `614e19ec3cf004918fee94bcfb914863007661f9` |
| [№32: evidence refs](https://github.com/rengalaxies/agent/pull/32) | `4354ef613e187e4244984b9ad09e0672792b0714` | `54fc6f8854e7003bc89a02b39067567306f117a7` |
| [№34: остановка при transport failure](https://github.com/rengalaxies/agent/pull/34), включён в №33 | `af15c6ce429c366f73b4d954829cefc6867c2eea` | `0d655494db0d04cb9776df9f620d345780922e0e` в ветке №33 |
| [№33: deadline, sufficiency и runner](https://github.com/rengalaxies/agent/pull/33) | `0d655494db0d04cb9776df9f620d345780922e0e` | `a9385c565d5471698da62987b226dcff4cbdea86` |

Исходный проверенный head №33 `9c62add55c5ce907d5e80b6b436809a72a0a5166`
изменён только на небольшой diff №34: regression и остановка серии после первого
timeout/HTTP/неопределённого транспортного сбоя. Известный HTTP 200 с usage и
некорректным действием модели остаётся результатом для оценки следующего случая.
[RED](https://github.com/rengalaxies/agent/actions/runs/39735294034) воспроизвёл
четыре провала; [GREEN](https://github.com/rengalaxies/agent/actions/runs/39735442558)
прошёл 116 graph-тестов. Отдельное узкое ревью №34 не нашло блокеров.
Исправление принято **до initialize**, условий во время серии не меняли.

У обновлённого №33 прошли core, offline, P1 verify/configuration.
На интегрированном main заново прошли [core — 541 тест](https://github.com/rengalaxies/agent/actions/runs/39736085178)
и [graph — 116 тестов, manifest](https://github.com/rengalaxies/agent/actions/runs/39736088286).
Новые workflow проверены actionlint. Общая проверка workflow сохранила прежний
[SC2129 style finding](https://github.com/rengalaxies/agent/issues/8) в
`cloudru-foundation-models.yml:37` из №30; это не ошибка нового runner.
Локальный Windows не поддерживает существующий POSIX Store (`fcntl`); runtime
проверки выполнены на Linux Actions без имитации OS-lock.

Родительские PR перенесены merge-коммитами с сохранением ancestry; ядро включено
один раз. №31 целиком не сливался: сохранённые fixtures и provenance взяты через
№32. Исторические отчёты не изменялись. №29 не сливался в этой пачке.
AGENTS.md в checkout, Git-деревьях и доступных родительских каталогах не найден.
Работа выполнена в отдельном worktree, остальные checkout и ветки сохранены.

## Запуск и неизменные условия

- [Initialize — 39736283575](https://github.com/rengalaxies/agent/actions/runs/39736283575), SUCCESS.
- [Execute — 39736391432](https://github.com/rengalaxies/agent/actions/runs/39736391432), SUCCESS сбора, 6/6 результатов.
- [Immutable final ledger](https://github.com/rengalaxies/agent/blob/677c7488f32119aa3a552336600a7aac70839282/ledger.json).
- Artifact `evidence-refs-v2-safe-reports`, ID `12407880399`, GitHub archive digest
  `sha256:c8bbeeab8aa36534728d60d2ec8d4eccad9c8bd7ec94496919cef2444edd6d7b`.

Перед initialize и execute проверен полный SHA main. Initialize ledger проверен
отдельно: `INITIALIZED`, 21 историческая попытка, 0 новых, request cap 30,
money cap **100000000 micro-RUB = 100 RUB**. Execute использовал тот же SHA.
Секрет Foundation Models получен только внутри Actions; initialize не получает
его. Значения секретов не извлекались и не переносились локально. Новые облачные
ресурсы не создавались, ВМ/SSH не менялись.

Обе модели использовали один протокол evidence-refs-v2, system/task/schema,
corpus, temperature=0, stream=false, `max_completion_tokens=4096`, context=131072,
prompt cap 60000 bytes, до 5 шагов/случай, до 60 строк/чтение, 0 retries,
1 случай одновременно. Порядок: Reporting Qwen/GPT, Export Qwen/GPT, Status Qwen/GPT.
Все перечисленные источники, включая decoy, должны быть прочитаны до первого
propose. Oracle читает evaluator; зависимости и готовая карта модели не передавались.

Manifest digest во время prepare/initialize/execute совпадает:
`bbe773c16ee200867020d8df355ac64ac6b008426ce5b9aebebb10a07cefabf8`.
[manifest.json](manifest.json) содержит hashes всех файлов корпуса, ядра, runner,
system/schema и oracle. Hashes сверены с Git-объектами принятого SHA, без зависимости
от CRLF локального checkout. Исходные подготовительные поля `live_enabled=false` /
`RUNNER_PREPARED_NOT_RUN` в неизменном manifest не являются статусом выполненной
серии: фактический статус находится в [report.json](report.json) и ledger.

Серия: **09:49:38–09:53:33 МСК**, 235,08 с, включая очередь и setup от `created_at`.
Абсолютные пределы сохранены: 2100 с на серию, 300 с на случай; HTTP ограничен
оставшимся временем и максимумом 60 с. Сроки и лимиты не продлевались.

## Раздельная оценка шести результатов

| Модель | Случай | Запросы | HTTP / typed JSON | Action-протокол и finish | Связь, направление, сервис | Подлинность / достаточность evidence | Валидатор | Полный цикл |
| --- | --- | ---: | --- | --- | --- | --- | --- | --- |
| Qwen3-Coder-Next | Reporting → Orders | 3 | 200 / PASS | FAIL: `invalid_model_action` при propose | Не оценено | Не оценены | До admission не дошёл | FAIL |
| GPT OSS 120B | Reporting → Orders | 5 | 200 / PASS | PASS | reporting → orders, GET /orders, PASS | PASS / PASS | `UNAPPROVED_CANDIDATE` | PASS |
| Qwen3-Coder-Next | Export → Orders | 3 | 200 / PASS | FAIL: `invalid_model_action` при propose | Не оценено | Не оценены | До admission не дошёл | FAIL |
| GPT OSS 120B | Export → Orders | 4 | 200 / PASS | PASS | export → orders, GET /orders, PASS | PASS / PASS | `UNAPPROVED_CANDIDATE` | PASS |
| Qwen3-Coder-Next | Status /orders, decoy Orders | 4 | 200 / PASS | FAIL: `invalid_model_action` при propose | Не оценено | Не оценены | До admission не дошёл | FAIL |
| GPT OSS 120B | Status /orders, decoy Orders | 4 | 200 / PASS | FAIL: `invalid_model_action` при propose | Не оценено | Не оценены | До admission не дошёл | FAIL |

Все 23 ответа имели HTTP 200, `finish_reason=stop` и прошли typed JSON parsing.
Во всех случаях выполнено чтение полного корпуса до propose. Этого недостаточно
для успеха: четыре случая остановились на проверке action до assessments/admission.
Булевы `provenance_passed=false` / `sufficiency_passed=false` для них означают
непройденный критерий, **не доказанную подделку или недостаточность конкретного evidence**.

Сохранённый audit не содержит полей отвергнутого propose. Код `invalid_model_action`
здесь ограничивает причину непустыми source-полями либо пустым proposals, но не
позволяет определить конкретное поле, восстановить семантический выбор модели или
приписать ей неверный сервис. Это ограничение наблюдаемости указано явно; догадка
о причине не подменяет свидетельство.

В Status правильный положительный вывод — **health → status**, а health → orders
запрещён. `orders/api.py` и `status/api.py` побайтно одинаковы. Совпадение `/orders`
само по себе не определяет сервис: нужен адрес `https://inventory.test` и операторское
соответствие status. Ни одна модель не завершила этот контроль. Ложное ребро не
допущено, но отказ до семантической проверки не означает прохождения контроля.

Два принятых предложения GPT отдельно проверены по typed claim, сессионным refs,
range/source hashes и покрытию callsite + provider declaration. Они остаются
`UNAPPROVED_CANDIDATE`, `STATIC_PROFILE_ONLY`, `runtime_verified=false`.
Refs не добавляют прав: ядро сохраняет проверки subject/view/session, snapshot/basis,
актуальности и range, затем отдельно оценивает достаточность для направленной связи.
Default quotes-v1 и старый интерфейс сохранены; регрессии входят в прошедший CI.

## Запросы, usage, время и расчёт стоимости

| Модель / случай | Input tokens | Output tokens | Время шагов, с | Оценка, ₽ |
| --- | ---: | ---: | ---: | ---: |
| Qwen / Reporting | 3363 | 541 | 25,84 | 0,5422900 |
| GPT / Reporting | 6595 | 1798 | 37,28 | 0,2142747 |
| Qwen / Export | 3488 | 705 | 24,21 | 0,5975560 |
| GPT / Export | 4600 | 1418 | 36,71 | 0,1594540 |
| Qwen / Status | 6287 | 430 | 26,80 | 0,8719340 |
| GPT / Status | 5260 | 1782 | 44,71 | 0,1921256 |
| **Новая серия** | **29593** | **6674** | **235,08 wall time серии** | **2,5776343** |

Время шагов — сумма `event.seconds`, включая учёт runner/transport; это не отдельное
измерение чистой сетевой latency. Время серии дополнительно включает setup,
контексты и прочие промежутки.

- Новые: **23 запроса**, IDs **22–44**, Qwen 10 / GPT 13; unknown usage **0**.
- Исторические: **21 попытка**, известные input **24208**, output **4301**;
  usage попытки **№15 неизвестен**, полные исторические token totals остаются null.
- Lifetime: **44 попытки**. Исторические результаты не участвуют в новом score.
- Новый необратимый консервативный резерв: **76,630396 ₽ из 100 ₽**.
  Остаток лимита не даёт права rerun: ledger закрыт `COMPLETED_NEW_SERIES`.
- Оценка известных новых токенов: **≈2,58 ₽**. Известная часть истории при тех же
  опубликованных ставках — ≈2,664003 ₽, **без неизвестного №15**.
  Это оценка, **не фактический биллинг**; `actual_billed_cost=NOT_MEASURED`.

Для оценки использован [каталог Cloud.ru](https://cloud.ru/products/evolution-ai-factory/catalog-foundation-models),
проверенный 22.10.2026: Qwen 122/244 ₽, GPT OSS 15,86/61 ₽ за миллион input/output
токенов. [pricing.json](pricing.json) фиксирует ставки. Резерв использует более
консервативные 244 ₽/миллион для обоих видов токенов обеих моделей и не возвращается
после ответа; он отличается от оценки по наблюдаемому usage.

## Цитаты и рекомендация для закрытого демо

Необходимость пересоздавать точный текст цитаты моделью устранена **механизмом refs**:
модель возвращает receipt разрешённого чтения, доверенный код извлекает точный текст
из snapshot и передаёт старому exact validator. Два полных реальных цикла GPT это
подтвердили на Reporting/Export. Это не означает, что решены все ошибки протокола:
четыре других случая не дошли до evidence validation.

Для закрытого показа рекомендован **GPT OSS 120B только на воспроизводимых
Reporting/Export**, с просмотром источников и ручным подтверждением кандидата.
Допустима демонстрация детерминированного HTTP-графа и двух сохранённых модельных
результатов. Интерактивную автоматическую инвентаризацию произвольных зависимостей
и Status-контроль пока нельзя считать готовыми: полного отрицательного контроля нет.
Qwen в текущем неизменном протоколе для модельного цикла не рекомендован (0/3).

Следующее техническое действие — сохранить безопасные поля отклонённого typed action
и проверить согласованность action-specific null/proposals ограничений схемы и
исполнителя офлайн. Изменение протокола и новая оплачиваемая серия должны быть явно
отдельными условиями; эта серия не исправлялась и не повторялась. По шести небольшим
синтетическим случаям вывод о преимуществе продукта над coding agent не делается.

## Воспроизведение оценки без модельных вызовов

Из этой папки, с Python 3:

```bash
python analyze_batch1.py report.json manifest.json final-ledger.json pricing.json --output analysis-recomputed.json
```

Скрипт проверяет manifest digest, совпадение отчёта с ledger, исходные 21 записи,
лимиты, последовательность новых IDs и заново вычисляет usage/стоимость. Он не
импортирует runner и не делает сетевых вызовов. [verification.json](verification.json)
дополнительно фиксирует сверку корпуса с Git и 15 read receipts, а также ссылки
двух assessed claims на receipts своей сессии.

[safe-dialogues.json](safe-dialogues.json) содержит system/task/schema, действия,
receipts/ranges и assessments. Тексты чтений восстановлены из закреплённого корпуса
и помечены как reconstruction. Это безопасный audit диалога, не полный HTTP wire dump;
отвергнутые propose payload в исходном runner не сохранялись. Private SQLite,
credential headers и raw provider errors в пакет не включены.

[files-sha256.json](files-sha256.json) закрепляет файлы пакета. Полная интеграционная
метаинформация и ссылки проверок находятся в [integration.json](integration.json).
