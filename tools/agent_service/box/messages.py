"""Reason codes → what the owner should do. Codes only; no secret value or raw provider text reaches here."""

from __future__ import annotations

TEXT = {
    "service_not_live": "Сервис не отвечает на /healthz. Смотрите journalctl -u agent-service -n 50.",
    "loaded_identity_missing": "Процесс не записал загруженную версию (run/loaded.json): он не стартовал или "
                               "отклонил собственный релиз.",
    "loaded_identity_from_other_process": "Файл загруженной версии оставлен другим процессом: сервис перезапускается.",
    "running_release_differs_from_active": "Работает не тот релиз, который активен в журнале box. Выполните box install.",
    "running_core_differs_from_manifest": "Загруженное ядро не совпадает с manifest релиза: релиз изменён на диске.",
    "running_config_of_other_release": "Процесс прочитал конфигурацию другого релиза, а не сгенерированную активным "
                                       "релизом. Выполните box install активного релиза.",
    "running_code_version_differs_from_release": "code_version в результатах анализа не совпадает с активным "
                                                 "релизом. Выполните box install активного релиза.",
    "running_constitution_differs_from_release": "Загруженная конституция не совпадает с конституцией активного "
                                                 "релиза (или constitution_file из box.yaml).",
    "state_missing": "Файла очереди нет: сервис ещё не запускался или состояние удалено. box не создаёт пустую "
                     "очередь сам; восстановите копию (box restore) или запустите box install.",
    "restore_copy_differs": "Копия базы при восстановлении не совпала с резервной копией: текущее состояние оставлено.",
    "status_endpoint_unavailable": "Не отвечает /status сервиса.",
    "status_token_rejected": "/status отклонил токен AGENT_SERVICE_STATUS_TOKEN из secrets.env.",
    "graph_empty": "Граф пуст: начальное построение не нашло ни одной связи. Проверьте зеркала и service_addresses.",
    "connection_unauthorized": "Провайдер отклонил учётные данные (401/403). Проверьте токен в secrets.env и его права.",
    "rate_limited": "Провайдер ограничил частоту запросов (429). Сервис повторит позже сам.",
    "provider_unavailable": "Провайдер отвечает 5xx. Сервис повторит позже сам.",
    "not_found": "Ресурс не найден или у учётной записи нет к нему доступа (404).",
    "provider_rejected": "Провайдер отклонил запрос (4xx). Проверьте адреса и ключи проектов в box.yaml.",
    "outcome_unknown": "Нет связи с провайдером (сеть, DNS, TLS). Проверьте доступ ВМ к адресу из box.yaml.",
    "secret_missing": "В secrets.env нет нужной переменной.",
    "git_credentials_rejected": "Git-хостинг отклонил учётные данные при fetch. Проверьте GitHub App/токен в secrets.env.",
    "git_repository_not_found_or_no_access": "Репозиторий не найден или у учётной записи нет доступа на чтение.",
    "git_host_unreachable": "Git-хостинг недоступен с ВМ (сеть, DNS, прокси).",
    "git_branch_not_found": "В репозитории нет ветки, указанной в box.yaml.",
    "git_fetch_failed": "git fetch завершился ошибкой. Повторите box sync-mirrors; если повторяется, смотрите doctor.",
    "git_repository_owner_mismatch": "Владелец каталога зеркала не совпадает с пользователем сервиса.",
    "github_secret_missing": "Для доступа к GitHub не задан секрет (токен или ключ App) в secrets.env.",
    "sync_already_running": "Синхронизация зеркал уже идёт.",
    "model_disabled": "Модель выключена: квалификация 2Б не подтверждена для загруженного кода (см. doctor сервиса).",
    "graph_source_unavailable": "Часть источников графа недоступна: связи сохранены, но помечены как несвежие.",
    "reconcile_failed": "Сверка с провайдером не удалась; события, пропущенные webhook, подтянутся после восстановления.",
    "graph_reconcile_failed": "Обновление графа по веткам по умолчанию не удалось.",
    "install_phase_degraded": "Шаг установки завершился с предупреждением",
    "task_crashed": "Внутренняя задача box завершилась без результата.",
    "release_file_modified": "Файл релиза изменён после сборки: релиз отклонён.",
    "missing_release_file": "В релизе не хватает файла из manifest.",
    "unexpected_release_file": "В релизе есть файл, которого нет в manifest.",
    "backup_not_found": "Резервная копия с таким именем не найдена (box backups).",
    "backup_file_modified": "Файл резервной копии изменён или повреждён.",
    "backup_integrity_failed": "SQLite в резервной копии не прошёл integrity_check.",
    "restore_counts_differ": "После восстановления число записей не совпало с копией.",
    "state_semantics_mismatch": "Профиль/идентичность состояния не совпадает с целевым writer. Запуск запрещён; "
                                "используйте новый manager и matching backup.",
    "state_identity_unreadable": "Идентичность состояния не читается. Не удаляйте marker; сохраните state и "
                                 "проверьте matching backup новым manager.",
    "unknown_legacy_state_semantics": "Legacy manifest не имеет известного recovery-контракта. Запуск по "
                                      "совпадению SQLite schema запрещён.",
    "unknown_recovery_contract": "Recovery-контракт релиза не поддерживается этим manager; запуск запрещён.",
    "backup_configuration_mismatch": "Конфигурация backup не соответствует релизу или путям этой установки.",
    "backup_manifest_state_differs": "Schema/counts backup не совпадают с его manifest; рабочее состояние не заменено.",
    "recovery_marker_unreadable": "Marker восстановления повреждён. Не запускайте старый CLI и не удаляйте marker; "
                                  "сохраните диагностику и safety backup.",
}


def explain(reason: str) -> str:
    """'notice:kind:detail', 'probe:source:code', 'source_stale:id', plain codes."""
    head, _, rest = reason.partition(":")
    if head == "notice":
        kind, _, detail = rest.partition(":")
        code = detail.split(":")[-1] if detail else kind
        return f"{TEXT.get(kind, kind)}" + (f" ({detail}: {TEXT[code]})" if code in TEXT and code != kind else
                                           f" ({detail})" if detail else "")
    if head == "probe":
        source, _, code = rest.rpartition(":")
        return f"Проверка {source}: {TEXT.get(code, code)}"
    if head.startswith("source_"):
        return f"Источник {rest}: свежесть {head.removeprefix('source_')}. Связи сохранены, но могут быть устаревшими."
    if head == "install_phase_degraded":
        return f"{TEXT[head]}: {rest}. Подробности в отчёте установки и в box doctor."
    if head == "model":
        return f"Модель: {rest}. Сервис работает без модели; гипотезы модели не выдаются."
    if head == "graph":
        return f"Граф не читается: {rest}."
    return TEXT.get(reason, reason)
