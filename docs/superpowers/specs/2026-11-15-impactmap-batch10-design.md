# ImpactMap10: техническая подготовка стабильной поставки

Вход8334b69, existing managed codex/impactmap-batch-00 worktree. Владелец поручил10 и добавление будущего обсуждения UI/админки. Метод работы — прежнее автономное inline выполнение; дополнительные дизайн-вопросы не нужны для уже выбранной технической линии. Новая UI/admin пачка только планируется, UI здесь не строится.

## Результат

Получить воспроизводимый локальный release-кандидат с проверяемой идентичностью, тестами, операторским доступом к полному результату и инструкцией диагностики/приёмки. Обновить сверку GitHub/local/runtime. Полное закрытие10 требует живых3 change/fix циклов на каждом из Jira/Kaiten/Яндекс и проверки поставленного pin. Яндекс доступа нет; этот gate остаётся открытым. Подготовка кандидата не равна production deployment.

## Решения исполнителя

1. Исправлять обнаруженные CI-проблемы по воспроизведению, без изменения семантики анализа или author metrics. Изолировать transport error/deadline tests от недетерминированного запуска чужого system Python. Реальные deadline/cancel/core-identity гарантии сохранить.
2. Полный result получать через существующий операторский Bearer-token, read-only JSON endpoint `/result?resource_id=...`, дополненный ограниченным `/resources` списком для обнаружения IDs. Никакого public URL/embedded token/HTML/admin mutation. Показывать выбранное поколение, его version/status и явную stale/closed/current-job информацию; не выдавать старый удачный результат за текущий после нового отказа. Сырые credentials/snapshot descriptions/HTTP receipts/tracebacks не включать. Полный анализ содержит разрешённые evidence: доступ к нему только у оператора установки.
3. Исправить пустой PR base в полной версии комментария: использовать validated analysis snapshots.base, затем явный base_sha, затем честный destination_tip label; не объявлять destination tip merge-base. Отсутствие данных явно обозначать.
4. Использовать имеющийся hash-locked release builder, не новый формат/фреймворк. Собрать Linux artifact из одного source commit и проверить manifest/tree/wheels; текущий release_VERSION0.1.0 допустим с уникальным sourceSHA candidate ID, не менять версии ради маркетинга. No dependency updates. Зафиксировать доступные local/Linux checks, backup/restore инструкции и реальные оставшиеся gates.
5. Обновить roadmap/CHECKPOINT/mirror и добавить A6 UI/admin discussion с собственными AC. Исходные14+A1–A5 не перенумеровывать.

## Границы

MODEL OFF, core profile9/output2.2/defaults8MB/2048/60/per-file65536, normalization2/scorer/oracles/старые raw неизменны. Не менять установленный worker/state/secrets и не выполнять remote writes без конкретного reviewable release/плана. Read-only SSH preflight разрешён задачей. Использовать существующий runtime/dependency cache, никакого раскрытия токенов. Результаты local/injected не называть live acceptance. Полный CI, Linux recovery и реальные tracker cycles имеют отдельные статусы.

## Приёмка технического объёма

- Сохранены исходный и финальный полные test receipts, причины отличий/skip и точные команды/environment.
- API: unauthorized/no token fail closed; bounded resource list, unknown/missing result, current/failed/stale/closed generations; возвращается только выбранный resource, без записи/анализа/публикации. No-store/security headers.
- Versions: реальный analysis base/head используются при наличии, fallback не выдумывает merge-base.
- Artifact: commit/core/contract/state/lock/file hashes проверяемы; безопасная инструкция установки/recovery и matrix исходных AC10 с честными NOT_RUN.
- Один fresh whole-batch reviewer, найденные важные дефекты RED→GREEN; report и передача сохранены локально. A6 есть в roadmap и checkpoint.
