# Fresh review — пачка07

14.11.2026. Один отдельный reviewer, без изменений файлов с его стороны. Scope — только07 поверх ea31bbb; независимая оценка06 и production runtime не переоценивались.

Приняты все существенные замечания. Один проход исправлений; воспроизводители сначала запускались на старой реализации (RED), затем исправленная серия (GREEN). Дополнительные валидные current-key aliases и deep JSON проверены в финальной серии.

| Находка | Исправление / регрессия |
|---|---|
| P1: rename журнала не durable перед POST | fsync каталога после replace и parent после mkdir; test_directory_entry_is_durable_before_post |
| P1: Yandex cursor может пропустить строки, overfull/преждевременный конец | Курсор равен последнему raw numeric id; отклонение >perPage; явное исчерпание до пустой страницы; tests_bad_cursor…, yandex_overfull_unique_page…, yandex_missing_link… |
| P1: поколение2 после POST ошибочно доказывает PATCH | Нужна durable update_pending/verified либо собственный PATCH; test_unearned_updated_readback_cannot_skip_patch |
| P2: отсутствующий applied limit Kaiten маскирует неполноту | Header обязателен; test_bad_cursor_and_missing_applied_limit_prevent_any_write |
| P2: malformed nested shape оставляет прежний PASS/traceback | Проверки queue/createdBy/JSON depth, стабильный отказ, RUNNING→FAILED/UNKNOWN; test_malformed_nested_response_invalidates_previous_pass и deep_invalid_json |
| P2: supplied self другой задачи игнорируется | Проверка pinned origin, immutable/current key из GET и native comment ID, без dereference; foreign_comment_self… и valid_yandex_current_key… |
| P2: deleted=true/неверный тип в write reply принимается | Отклонение before success; test_foreign_comment_self_and_deleted_write_reply_are_rejected |
| P2: нет post-write scope check | Финальный GET перед PASS; test_post_write_scope_drift_is_not_pass |
| P2: read-only стирает UNKNOWN записи | Observation отдельно, pending write остаётся UNKNOWN, CLI exit1; test_read_only_resume_preserves_unresolved_write_outcome |
| Дополнение:206 Partial Content не полный list | GET строго200, writes200/201; test_partial_page_status_is_not_complete. Stand Kaiten POST200, Yandex POST201 |

Ранее при авторской проверке также исправлено сохранение старого top-level error после успешного reconcile: текущая ошибка очищается, история неудавшихся операций остаётся в events. test_resume_clears_old_error_after_success RED→GREEN.

Отложенных minor findings нет. Не проверено живое поведение tenant, права/личность bot, задержка видимости/конкурентные ручные правки и отключение питания. Заявлений о закрытии этих границ нет. Глобальной дедупликации разных независимых probe outputs не обещаем: журнал нельзя сбрасывать после неизвестного create.
