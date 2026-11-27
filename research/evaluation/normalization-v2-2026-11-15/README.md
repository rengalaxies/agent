# ImpactMap: versioned evaluation normalization2

15.11.2026. Исправлена привязка предупреждений к изменённой операции и её локальным доказательствам. Source `1954f493c5892f55954e47fc1164ddb935388a80`, база `0841a90de3be4860bdb92d9ff9531ac2776f4409`. Это техническое продолжение development06. **Независимая06: NOT_REGISTERED / NOT_RUN, новых независимых кейсов0, реальных экспертов0.**

## Поведение и границы

При замене `GET /orders` на `GET /{resource}` текущий calls edge указывает новую route, а предупреждение относится к прежней изменённой операции. v1 ошибочно использовал новый target. v2 связывает типизированный subject с scoped delta и проверенным provider evidence; caller witness берёт только из соответствующей формулировки/места вызова. Несколько старых операций, агрегированных в одном новом calls edge, сохраняют отдельные ключи и строки вызова.

Несогласованный subject, off-delta alternative, несовместимый scope, отсутствующие или конфликтующие доказательства дают канонический UNBOUND/manual audit. Адресованная нагрузка не исчезает при malformed-first, пустых affected refs или ошибочном evidence.repository. Проверяются commit/path/range/content SHA/blob/visibility. Декларация provider не становится caller witness, включая случай одного сервиса с обеими ролями. Для PR/replay требуется delta; предварительный Jira-result без delta сохраняет ограниченное прежнее сопоставление. Это структурная нормализация, без чтения gold, интерпретации текста claim или нового семантического анализа source.

Новая идентичность: `impactmap-normalization-2`, [protocol-v2](../protocol-v2.md), protocol SHA/normalization version/evaluator SHA в configuration и freeze. Старые freeze не соответствуют новым компонентам. Формат normalized1.0, operational packet1, scorer, знаменатели, author40/oracles и схемы прежние. LS1 lexical-функция идентична базе по AST; configuration SHA изменён для явной идентичности оценщика.

Core не менялся: `http-requests-9`, output2.2, digest `d4ffae30456713d3280e33278d4e9f3fa9aa33e88167b45c2592d44fe3af30a1`, MODEL OFF. Defaults8 000 000 байт/2048 inventory/60s и per-file65 536 байт прежние. Внешних API, публикаций, обновления установленного worker или policy ВМ в этой пачке нет.

## Два разных сравнения

1. [Replay](replay/comparison.json): ровно40 неизменных прежних core envelopes из removal-серии. v1 загружен из Git базы; его40 результатов точно совпали с сохранёнными normalized. Оба оценщика получили один payload и один Registry, метки открыты после нормализации. У20 положительных кейсов v2 сузил witnesses до нужного callsite; ключи и итоговые TP20/FP0/FN0 остались прежними. Это повторная обработка старого output, **не новые попытки**.
2. [Свежая авторская серия](author-v2/summary.json):80 первых назначенных попыток на тех же40 входах, seed20261114, тот же порядок/60s cap/oracles/scorer; post-tuning явно указан. Никаких замен неудачных результатов и повторов ради улучшения метрик. Все80 receipts,80 normalized и40 core raw envelopes сохранены; LS1 raw остаётся в приватном work, его hashes есть в [индексе](author-v2/raw-index.json).

| Метод, свежая серия | TP | FP | FN | Precision | Recall | FAR на14 отрицательных | Обозначена граница вне профиля |
|---|---:|---:|---:|---:|---:|---:|---:|
| ImpactMap static |20|0|0|100%|100%|0/14|5/6|
| LS1 literal search |20|8|0|71.43%|100%|8/14|2/6|

Авторские метрики не улучшились относительно предыдущей серии: исправлен способ оценки других случаев. DEV-0039 сохранён FAILED/commit_unavailable, это единственная техническая ошибка ImpactMap вне профиля; продукт не доказывает отсутствие потребителей при недоступном PR. [Сравнение по каждому случаю](author-v2/per-case-changes.json) и исходные per_case в summary позволяют проверить изменения. Это знакомый development-набор13 коррелированных семейств, не независимое доказательство качества и не основание объявлять пороги утверждёнными. Суммарное wall время80 попыток92.837s приведено как receipt metadata, без сравнения производительности.

## Контроль замены и ошибка старого артефакта

[Пять новых pinned controls](replay/fixtures/index.json) получены реальным Graph/change_result с правильным `dump_document` и не включены в author40. Single: v1 `/{resource}` → v2 `/orders`; merged: v1 один новый target → v2 `/orders` и `/invoices` с раздельными строками; self-service: старая операция с настоящим caller witness; no-proof: UNBOUND; bad-blob: ключ не получает ни одного witness. Никакого TP/FP улучшения на этих нелабелированных controls не заявляется. Raw, обе нормализации, Git pins и проверяемый текст источников сохранены.

Прежний `removal-2026-11-15/replacement-diagnostic/output.json` сериализован через `model_dump` без alias и содержит **`schema_id` вместо `schema`**. Он структурно невалиден у обеих версий; обе сохраняют `invalid_analysis_document`, без права на TP. [Disclosure](replay/historical-diagnostic/disclosure.json) фиксирует SHA и старый путь. Исторический файл/старый отчёт не исправлены задним числом. В начальном рабочем описании этой пачки поле ошибочно называлось `schema_`; проверка реальных байтов исправила это название, не исходный артефакт. Первое выполнение recipe дошло до этой ошибочной assertion и остановилось; [лог](tests/replay.log) сохранён, отдельный [завершающий запуск](tests/replay-historical.log) прошёл. Source/tooling не менялись между replay и новой серией.

## Проверка и ревью

- 27 целевых regressions GREEN, включая реальные pinned output и malformed/ambiguity controls; RED и промежуточные ошибки сохранены в [tests](tests/).
- Финальный performance suite102/102 (65.351s; обязательный task gate102/102,66.745s), contracts/removal/catalogue58/58 (0.457s). Строка `{passed:false,remote_load_failed}` после unittest OK — stdout ожидаемого отрицательного CLI-теста, exit0; это не итог suite.
- Один свежий reviewer, один substantive RED→GREEN проход: проверка caller blob, per-anchor конфликт direct claims, сохранение пустых affected, устойчивость к нестроковому repository. [Решения и итог](review.md).
- Verifier проверяет точный набор/hash артефактов,922 прежних core/research/scale/scorer файла против базы, полноту80 уникальных receipts и40 replay outputs, одинаковые назначения, provenance и raw hashes. С `--current-tools` заново нормализует сохранённые fixture sources без Git; с `--private` пересчитывает80 оценок и80 replay scores по прежним author-oracles, проверяет обе серии v2 normalization и все private raw. Это не новые анализы.

Общий проектный CI в этой пачке целиком не запускался и зелёным не объявляется: известная проблема graph_demo CLI с deadline0.4s остаётся следующей технической задачей10. Реальные01/06/11 и Яндекс07/09 по-прежнему отдельные незакрытые AC.

## Воспроизведение

Из корня checkout, Python существующего venv с `PYTHONPATH=src:.:work/batch06-quality/validator` и `PYTHONDONTWRITEBYTECODE=1`:

```sh
python research/evaluation/normalization-v2-2026-11-15/reproduce/verify.py
python research/evaluation/normalization-v2-2026-11-15/reproduce/verify.py --private
python research/evaluation/normalization-v2-2026-11-15/reproduce/evidence.py replay --target work/normalization-replay-fresh
python -m tools.impactmap_eval.calibrate --corpus work/batch06/development-v2 --output work/normalization-author-fresh --post-tuning
python research/evaluation/normalization-v2-2026-11-15/reproduce/evidence.py publish --campaign work/normalization-author-fresh --target work/normalization-published-fresh
```

Target обязан отсутствовать: существующие измерения не перезаписываются. Replay/private режимы требуют исходные локальные Git-corpora и author входы; portable hash check и сохранённые receipts доступны без скрытых данных. Исходная40 и время первой назначенной серии не заменяются новым запуском. Полная идентичность компонентов/исходников — [source-identity](replay/source-identity.json), [freeze](author-v2/candidate-freeze.json), [manifest](author-v2/campaign-manifest.json). Следующий шаг — общий CI, диагностика/full result и подготовка локального release-кандидата10; Яндекс07/09 после появления доступа, независимые входы06 параллельно.
