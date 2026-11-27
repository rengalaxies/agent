# Пачка 06: инструменты и авторская диагностика

14.11.2026. **Техническая подготовка и авторские прогоны выполнены. Независимая оценка НЕ выполнена: NOT_REGISTERED / NOT_RUN.** Реальных экспертов — 0, новых независимых heldout-кейсов — 0. Эти результаты нельзя выдавать за подтверждение качества на внешних проектах или за прохождение пачки 06 целиком.

По поручению «пока всё делай ты» созданы 40 **авторских development-кейсов** в 13 связанных семействах: 20 ломающих, 10 совместимых, 4 без потребителей, 6 вне профиля. Разные route/имена не делают шаблоны независимыми проектами. Ожидания заданы автором вместе с игрушечным контрактом; реальные consumer-check/HTTP-запросы не выполнялись. Все [oracle-файлы](author-oracles/) остаются `lifecycle=draft`, human attestations=false, expert_id=null, source_labels пусты. Техническое поле stage в draft не означает состоявшегося adjudication.

## Полученные наблюдения — только этот авторский набор

| Метод | TP / FP / FN в 34 S-кейсах | Strict precision | Strict recall | FAR на 14 отрицательных | Boundary success в 6 O |
|---|---:|---:|---:|---:|---:|
| ImpactMap, MODEL OFF | 20 / 6 / 0 | 76,92% (20/26) | 100% (20/20) | 42,86% (6/14) | 4/6 |
| LS1, буквальный rg | 20 / 8 / 0 | 71,43% (20/28) | 100% (20/20) | 57,14% (8/14) | 2/6 |

Предложенные precision≥85% и FAR≤10% на этом development-наборе **не выполнены**. Независимого вывода CRITERIA_MET/NOT_MET нет: регистрация и человеческий эталон отсутствуют. Population CI не строится; кейсы коррелированы. Сравнение не доказывает статистическое превосходство графа, применимость на реальных данных, спрос или время экономии человека.

Все 20 положительных ключей нашли оба метода. Шесть FP ImpactMap — DEV-0025…DEV-0030: осторожные адресные `RECHECK_REQUIRED` при явно переданном page_size или пагинации. По заранее заданному протоколу такие предупреждения входят в P, даже если не утверждают доказанную поломку. LS1 дополнительно предупреждает на двух нерелевантных переходах с нейтральным hint. Эти ошибки не убраны из scoring и не исправлены под видимый набор; production `src/` сохранён.

Полнота 100% означает только обнаружение 20 простых положительных шаблонных ключей. Набор имеет один provider/consumer на кейс; он не репрезентирует произвольные системы. Оба метода получили те же task/hints/policy и provider base/head / consumer head. Последовательный, заранее сохранённый порядок — 80 первых назначенных попыток, общий cap 60 секунд. Выводы обеих систем сохранены до чтения oracle в calibration-driver. При этом сам автор/разработчик заранее знает генератор и ожидания: это development, без организационного blind-доступа или отдельных ACL.

[Полная сводка с per-key ошибками, стратами, provenance, origin groups, macro-recall и paired comparison](summary.json). В O основные TP/FP/FN — N/A, а не фиктивные нули; видимые предупреждения и причины ограничения сохранены отдельно. Неперечисленный кандидат в O не считается дефектом полного S-gold. Исправление этого диагностического флага выполнено на development; затем вся контрольная серия повторена на финальных версиях tooling. Основные TP/FP/FN/P/R/FAR не менялись; предварительные raw сохранены отдельно, повтор не увеличивает n.

## Что реализовано

- Строгая проверка existing JSON Schemas, policy-byte SHA, отдельного input TAR и pinned Git inventory; один provider, права и service-map проверяются до чтения источников. Никакого fetch сегодняшней ветки.
- Полные curator content-manifests: `[phase, commit, relative_path, git_mode, kind, content_sha256_or_gitlink_oid]`, порядок `(phase,path)`, compact UTF-8 JSON без перевода строк. Symlink — hash Git blob без следования; gitlink — только OID. Curator-helper требует полных прав на repo. Worker не вызывает его и не читает исключённые blobs ради проверки hash.
- В доступном полностью разрешённом snapshot полный digest пересчитывается. Для недоступных/исключённых entries он остаётся непрозрачным curator hash; реально разрешённые bytes сверяются с packet. При формальной регистрации требуется отдельное подтверждение curator full-manifest/input-integrity проверки. Hash не является обходом прав или доказательством прочтения недоступного файла.
- Packet — детерминированный отдельный TAR с task, policy, hints, budget, manifest, allowed inventory и разрешёнными sources. `input_packet_sha256` хеширует **точные bytes архива**, не содержащий этот hash case-input JSON. Worker не извлекает архив на диск, отклоняет неожиданные/повторные/необычные entries и превышение размера. Поле source_ref служит индирекцией к тому же policy repository ID; несколько services одного реального repo задаются раздельными IDs/непересекающимися include-prefix.
- Реальный CoreAnalyzer и LS1 через `rg --fixed-strings --line-number --no-heading --json -e TOKEN -- FILES...`. Поиск включает допустимые README/literal hits; пустые hints дают query_not_identified без выдуманного запроса. No LLM, AST-классификатора или gold-filter в LS1.
- Нормализация всех конкретных адресных findings/affected/checks/claims. Finding связывается через consumer/callsite/evidence→calls→operation, не произведением deltas×findings. Все raw refs сохраняются; неоднозначность — canonical UNBOUND по consumer. Невалидный документ сохраняет читаемые кандидаты, но не даёт TP.
- Scorer проверяет snapshot/phase/path, границы statement и quote hash. Неверный witness даёт FP+FN; duplicate bundles не увеличивают TP; U дедуплицируется по consumer, его canonical ID проверяется. Новая правдоподобная пара вне полного S-gold требует аудита. Диагностический повтор не заменяет первую primary-попытку.
- Worker отделён процессом с общим hard wall cap. Raw payload сохраняется до normalizer/presentation. `raw_artifact_sha256` относится к неизменяемому **attempt envelope** с payload, stdout/stderr, exit code и timestamps, включая ошибки/timeout. У зарегистрированной серии один заданный в permit SQLite ledger блокирует другой output-dir как способ получить новый primary и контролирует frozen order.
- Freeze gate проверяет code/core/dependencies/rg/argv, runtime/environment, seed, primary/retry rule, budgets, даты и human-role metadata. Он не аутентифицирует реальных людей. Сам по себе REGISTERED_READY — только структурная готовность; итоговый decision требует закрытой проверки gold artifacts и отдельной человеческой проверки prose/прав. Автоматическая проверка охватывает все структурные evidence/visibility, включая неиспользованные refs и исключённые пути; свободный текст не объявлен автоматически безопасным.
- Curator-side helpers проверяют две distinct independent-разметки, hashes, case/stage/date order, expectation artifacts, actual source witnesses и человеческий output-audit с привязкой к raw hash. Их следует запускать в закрытом workspace куратора; метод-worker этот модуль не импортирует. Проверки не создают людей и не доказывают их независимость.

## Доказательства и версии

[Dataset index](dataset-index.json), [80 normalized outputs](normalized.jsonl), [80 receipts](receipts.json), [предварительно сохранённый порядок и method-run components](campaign-manifest.json), [source/runtime/tooling disclosure](execution.json), [кандидат freeze](candidate-freeze.json), [готовность регистрации](readiness.json), [приёмка подготовки](acceptance.json), [журнал ревью](review.md).

[Raw index](raw-index.json) различает точные [Core envelopes](raw-core/) и [производные LS1 observations](search-observations.jsonl) с заменой только локального materialization prefix на `<attempt>`. Производные не называются raw и не имеют original raw hash. Все исходные неизменённые envelope/rg stdout/диски/packets/policy с локальными roots остаются в ignored `work/batch06/`; их оригинальные SHA сохранены и сверены. Для реальных внешних данных публиковать source-bearing artifacts без отдельного разрешения нельзя.

Входной core source anchor — commit 8d45b0f5c22fc652c704bc38a787b88d94663d7f, без правок `src/` и product defaults. Candidate freeze создан после development, статус NOT_REGISTERED, loaded_runtime_sha/curator/experts/gold/dates/approval пусты. Method-run и release-candidate components совпадают: итоговая контрольная серия выполнена после исправлений O-audit, dependency lock, timeout capture и закрытых verifier helpers. Это development-калибровка tooling, не замороженная независимая серия. Прежние результаты помечены в [superseded.json](superseded.json); исходные primary attempts не заменялись лучшими повторами.

76 профильных регрессий были OK; после последних curator/диагностических уточнений отдельная полная evaluation-suite — см. [финальный журнал](logs/evaluation-final.log). Старые schemas/арифметика/документные контракты проверяются отдельным отчётом без изменения исторических файлов 02. Все tests — технические проверки, не новые эксперты/кейсы качества.

## Воспроизведение авторской калибровки

Из корня checkout. Использован Python `/Users/user/Documents/ChatGPT/ВКР/.private/bitbucket-read-venv/bin/python`, jsonschema 4.26.0 из существующего target 02; зависимости приложения не менялись. [Точные зависимости](dependency-lock.json) и [pip requirements](requirements.txt). На другой машине создать отдельное окружение/target с этими версиями, а не менять установленный сервис.

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.:/tmp/impactmap-batch02/validator python -m tools.impactmap_eval.author_cases --output work/batch06/corpus-new
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.:/tmp/impactmap-batch02/validator python -m tools.impactmap_eval.calibrate --corpus work/batch06/corpus-new --output work/batch06/calibration-new
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src:.:/tmp/impactmap-batch02/validator python -m unittest tests.performance.test_evaluation_tooling -v
```

Output должен быть новым. Git source commits и toy facts воспроизводимы; policy roots, process timestamps, packets с локальными policy и raw hashes зависят от расположения/запуска, поэтому повтор сравнивает семантику и counts, а не обещает идентичные process envelopes. Реальные данные в эти author-генераторы не передаются.

Финальные локальные материалы: `work/batch06/development-v2/` и `work/batch06/author-run-release/`. Отдельный публичный input не получает stratum, expected label, rationale, oracle или curator catalogue. Точный порядок/receipts — до scoring; raw ошибки не исключаются из назначенного набора.

## Что осталось для полного AC 06

1. Реальный куратор и два независимых эксперта, разрешённые **новые** exact cases с origin split. Эти 40 уже видны разработчику и не могут стать независимыми через переименование или подпись задним числом.
2. Две слепые разметки и adjudication до outputs, expectation evidence, source/rights manifests, closed catalogue и журнал раскрытия. Полнота gold и подлинность людей не выводятся из hash/JSON.
3. Реальное согласование порогов/цены ошибок, зарегистрированный immutable source/tool/runtime/dependency/input/gold freeze и порядок/общий budget.
4. Первые outputs обоих методов на новом heldout, закрытый scoring и human-audit публикационных утверждений/прав, отчёт о реальном результате и ограничениях.

Ни один пункт не заполнен вымышленными людьми. Следующая доступная техническая линия — 07 (API/контракт Kaiten и Яндекс Трекера); независимое завершение 06 остаётся отдельным открытым обязательством. Авторская диагностика указывает на нужду отдельно разбирать адресные RECHECK в совместимых сценариях, а не снижать FP фильтрацией scorer после просмотра gold.
