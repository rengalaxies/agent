# Офлайн-результат изменения evidence-refs-v2

Новых модельных запросов: **0**. Реальный цикл v2: **NOT_RUN**. Закрытая серия
PR №31 не открывалась; её исторические ответы/quotes не исправлялись. ВМ и
secrets/vars не менялись.

Локально (Python 3.12): **88 tests PASS** (`unittest discover -s tests/graph`):
59 прежних core regressions, 23 новых reference/series/HTTP-stub tests и 6 тестов
подготовки/ledger. HTTP в тестах обслуживает только локальный stub, не Cloud.ru.
Ruff 0.17.1, F401/F811/F841 по src/services/tools/stand/lab и новым тестам — PASS.
Actionlint 1.7.7 для нового offline workflow — PASS (без shellcheck/pyflakes).
`git diff --check` — PASS. Manifest подготовлен офлайн, содержимое фиксируется
исходными файлами и SHA256 в артефакте CI; live runner отсутствует.

| Проверка | Результат |
| --- | --- |
| Корректная ссылка в новой тестовой сессии | Точный текст снимка, исходный validator вызван, UNAPPROVED_CANDIDATE |
| Выдуманный ID / ID другой сессии | invalid_evidence_reference, semantics NOT_ASSESSED |
| Отозванное read/propose право / другой subject/scope | forbidden / evidence_scope_changed |
| Изменённые bytes при прежней revision | stale_context |
| Новый head при прежних bytes / истёкший TTL / unavailable corpus | superseded_context / stale_context |
| Отрицательный, перевёрнутый, вне файла, слишком большой диапазон | invalid_evidence_range / evidence_range_limit, receipt не создан |
| Изменённые metadata receipt | invalid_evidence_reference |
| Точный нерелевантный текст / неправильные direction/service/method/path | provenance проходит, sufficiency INSUFFICIENT; кандидат не записан |
| Scripted Reporting → Orders / Export → Orders | SUPPORTED_WITHIN_PROFILE, только тестовые positive данные |
| Scripted Health → Status | SUPPORTED_WITHIN_PROFILE |
| Status decoy: Health → Orders; Orders/Status → Health; чужой provider при правильном claim | INSUFFICIENT, несмотря на точные доступные тексты |
| Сохранённые модельные quotes Reporting/Export/Status | Исходные quote/range сохранены, v1 по-прежнему evidence_mismatch |
| Полный scripted read/read/propose/finish | COMPLETED офлайн; model_quality_established=false |
| V2 schema через локальный HTTP stub / legacy quote payload в v2 | ReferenceReply / отклонён без преобразования |
| Абсолютные сроки после паузы/restart, shared cap, все попытки/unknown charged | PASS на искусственных часах, SIMULATED_NO_HTTP |

Устранённое препятствие в новом протоколе: необходимость модели побайтно
пересоздавать quote с кавычками и отступами. Дополнительно введён отдельный
bounded static барьер ложных directed claims, включая идентичность сервиса.

Остаются: неверные read ranges/IDs/actions, timeout, step/token/cost caps,
нехватка/нерелевантность основания, неподдерживаемые HTTP wrappers/динамика,
runtime/business semantics и неизмеренное качество реальных моделей. Старый v1
не получает новый semantic gate автоматически. Свежесть и scope проверяются
заново; ссылки их не отменяют. Для следующего live отдельно нужны authorization,
money cap и reviewed runner с общим deadline, как указано в plan/README.

Совместимость, migration и отдельная база PR №28:
[контракт](../../docs/evidence-references-v2.md).
