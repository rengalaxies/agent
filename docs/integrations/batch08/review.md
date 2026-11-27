# Fresh review08 и один проход исправлений

Один отдельный reviewer, scope08 поверх0bcde4e; без редактирования с его стороны. Все8 существенных findings приняты. RED воспроизводители в /tmp/impactmap08-review-red*.log; итог GREEN в tests.log.

1. P1 stale locator после relink/dry-run/Jira: get_comment трактует старый/чужой locator как stale, Publisher забывает его и ищет только текущую разрешённую карточку. Update остаётся strict. test_old_locator_is_stale_on_lookup_but_update_strict.
2. P1 stale intent после mark_sending: opt-in expected_intent передаётся Publisher только backend, которому он нужен; generation/lease/version проверяются до операции и callback после preflight. tests_old_intent_cannot_write_even_when_latest_db_matches_latest_source и new_generation_during_sending_does_not_write_old_body.
3. P1 moved board останавливает worker: read_card возвращает closed/unavailable с причиной, prepare отказывает управляемым ClientError. test_moved_card_is_closed_with_visible_reason.
4. P1 deleted/condition archive: явные archived/deleted/condition2–3 закрывают доступ. test_deleted_and_archived_condition_are_not_writable.
5. P2 oversized successful write: 2xx ClientError(response_too_large) преобразуется в unknown TransportError. test_oversize_applied_write_and_unconfirmed_echo_are_unknown.
6. P2 documented rows без deleted: optional flag на чтении, строгий тип при наличии; write reply подтверждается отдельно. test_documented_comment_without_deleted_is_readable.
7. P2 нет публичного readback: полный list подтверждает owned ID/точный текст; невидимость/ошибка readback — UNKNOWN, не DELIVERED. test_echo_without_visible_comment_is_unknown, local real-core/HTTP и real Kaiten hybrid.
8. P2 missing token at poll: token читается/pinned при build; отсутствие fail-fast. test_missing_token_fails_during_build.

Lost applied POST/reconstructed store и source update на sending проверены дополнительно. Начальный race-тест ожидал немедленного нового POST, хотя mark_sending уже включил общий settle window; исправлено только тестовое продвижение Clock, продуктовый retry policy сохранён. Initial fixture issues (неполная карточка без archived, обращение к внешнему вместо внутреннего fixture, marker ID против full marker line) исправлены до заключительного ревью/приёмки.

Отложенных minor findings нет. Real cloud Bitbucket E2E, OS process restart на этой версии, произвольно долгий visibility lag и глобальная координация нескольких клиентов остаются явными границами, не скрытым PASS.
