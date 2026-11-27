# A6.5 — постоянный живой Kaiten-пилот,22.11.2026

**Технический цикл Bitbucket→Kaiten→защищённый UI пройден. A6.5 остаётся PARTIAL: Jira LIVE UI link и пять сценариев личной приёмки открыты.** Продолжение утверждённого плана, без изменений production source29ed2ad. Исходные14 основных и A1–A5 сохранены; это уточнение A6.5.

Вход: [ImpactMap](https://82.202.141.50/ui/login). Username `owner`, прежний локальный пароль в ignored `work/a6-5/private/owner-access.txt`,0600. Пользователь самостоятельно вошёл22.11; author/browser-проверки ниже не заменяют его приёмку всех сценариев.

## Что работает постоянно

- Immutable release `/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312`; unit **impactmap-ui-kaiten.service**, enabled, bind127.0.0.1:18093. nginx переключён после успешных backend/public проверок. Прежний offline UI18092 оставлен для отката; основной Jira/Bitbucket worker не заменён.
- Отдельные `/var/lib/impactmap-ui-kaiten` и `/etc/impactmap-ui-kaiten`; namespace `impactmap-kaiten-cloud-20261115 / acceptance`, scope14683aa9d8fc. Queue08 сохранена online SQLite backup ради прежнего marker/nativeID; graph построен заново. Новые trusted receipts7–9 созданы реальными анализами; старые raw не получают backfill доступа.
- Единственная привязка: Bitbucket `agent-pilot-orders` PR5, ветка `impactmap-kaiten-cloud-20261115` → Kaiten board1982649/card74759475. Reconcile60s. Main и PR4 не изменялись; PR5 остаётся OPEN.
- Пользователь явно разрешил **постоянный** пилот и сохранение ключа22.11. Kaiten-key передан по SSH stdin в root-only0600 `/etc/impactmap-ui-kaiten/secrets.env`; существующие Bitbucket read credentials скопированы внутри ВМ. Значения не включены в Git/argv/отчёт. Systemd передаёт credentials процессу UID impactmap-ui: root-only файл не скрывает их от root/того же UID. Два UI-процесса используют один UID, поэтому отдельные состояния не являются отдельной Unix security boundary.
- Owner password сохранён внутри ВМ, sessions/challenges не мигрировали; QA accounts отключены. Публичные диагностические API404; anonymous UI API401. Данные доступны после scoped login, без токена в ссылке.

## Проверенный цикл

| Шаг | Head / generation | Анализ | Публикация |
|---|---|---|---|
| Исходное исправленное состояние |3883320d4725 /7|ABSTAINED, no_supported_delta|DELIVERED/update|
| Новый child: page_size100→20 |241600aaba9f /8|USEFUL, POSSIBLE_TRUNCATION у reporting|DELIVERED/update|
| Новый child:20→100 |5759f4d415b3 /9|ABSTAINED, no_supported_delta|DELIVERED/update|
| Systemd restart и последующий polling |тот же5759f4d415b3 /9|job/DONE, состояние прежнее|те же ID/digest/intents|

На всех шагах native comment **93817019**, marker **50f72df743af8977**, actual marker count **1**. Два других исторических комментария на карточке принадлежат иным диагностическим markers; их не удаляли и не выдавали за дубли PR5. Latest digest `c87a673dbd62cdf5395d5318adf771f448031dc30dc5f68703a8d6c77e49a0f4` совпал с реальным readback.

В g8 owner-browser показал USEFUL,100→20, reporting/POSSIBLE_TRUNCATION, pinned evidence241600aaba9f и DELIVERED. В g9 Kaiten показывает исчезновение прежней находки, а не доказанную совместимость. Native browser: клик **настоящей ссылки из комментария Kaiten** открыл login с локальным next того же PR5; пользователь вошёл, затем виден g9/ABSTAINED/CURRENT/DELIVERED. Во встроенном браузере клики по собственному комментарию открывали редактор; изменения не сохранялись, редактор отменён. Для фактического перехода использован уже авторизованный обычный Yandex browser, без изменения DOM/настроек безопасности.

Restart отдельного UI PID3569007→3572398 сохранил результат и comment. После следующего polling `live-fixed-final.json` и `live-replay-final.json` полностью совпали. Это штатный restart/reconcile, не новый SIGKILL или reboot proof. Основной worker PID60331/releasea02ffa/configSHA71dd9a7b… сохранился; main orders5d405f22/reporting6ebf0717 и PR4head01b6ebfa/OPEN совпадают с15.11.

## HTTPS: закрыт остаток production-ротации

Это уже **фактическая production-ротация**, а не dry-run: nginx hook20.11 21:16:10UTC, новый leaf действителен20.11 20:17:37–27.11 12:17:36UTC. Serial `05F5E00855DE62A4AEBCC552E08BCC974D84`; внешний leaf SHA256 `295cf2e3bf90040e999194a271933cfd823797a6336d9ffaa5fddeaf996f423c`, доверенная CA/IP SAN82.202.141.50 проверены. Timer active, последний run success. Заметка17.11 о ещё не случившейся ротации теперь историческая.

На Mac первоначальный GET Kaiten не прошёл из-за CA bundle локального Python3.13; тот же запрос с installed certifi CA и включённой проверкой TLS прошёл. Trust store и продукт не изменялись. Временная QA-проверка сначала обратилась к `analysis.raw`, хотя UI intentionally возвращает `analysis.result`: исправлен только проверяющий helper; первый запуск остановился до переключения nginx. Промежуточный g9/RUNNING readback не засчитан финальным.

## Эксплуатация и остаток

Проверка: `sudo systemctl status impactmap-ui-kaiten impactmap-tls-renew.timer`, `sudo journalctl -u impactmap-ui-kaiten`, `sudo nginx -t`. Secrets не печатать. Для управления пользователями запускать установленный `agent_service.ui_admin` **под impactmap-ui** с новым `/etc/impactmap-ui-kaiten/service.json` и `/var/lib/impactmap-ui-kaiten/ui/ui.json`.

Откат только UI: остановить `impactmap-ui-kaiten`, вернуть сохранённый root-only `/etc/impactmap-ui-kaiten/rollback-upstream.conf` в nginx snippet, проверить nginx -t/reload; offline18092 сохранён. Это возвращает прежнее offline scope/состояние и требует соответствующего входа. Основной `agent-bitbucket` и его current не менять. Новый live state/auth и постоянный key сохраняются для возврата; их production restore/reboot этой работой не проверялись. Старый auth backup17.11 относится к offline-пилоту, не к текущей live очереди.

Следующий технический шаг — отдельный scoped Jira publication/readback→protected UI на том же release, без замены основного worker. Затем личная приёмка пяти сценариев владельца. Яндекс07/09 и исходный общий10 трёх трекеров остаются открыты; независимые06/01/11 требуют реальных участников. Ни качество на независимом корпусе, ни экономия человеческого времени этим авторским сценарием не измерялись.

Receipts — [evidence](evidence/), использованные операционные scripts — [reproduce](reproduce/). Scripts фиксируют пути авторской ВМ, требуют ручного выбора/доставки и полномочий; prepare/activate/switch одноразовые, повторное выполнение намеренно остановится, если состояние уже существует. Файлов credentials/auth DB/raw tokens нет. Полный1368-run и86box PASS относятся к17.11/source29ed2ad; сегодня исходники не менялись, выполнены целевые live/API/TLS/browser/restart проверки. Один ограниченный fresh review scripts/receipts не нашёл Critical/Important; независимой runtime-приёмкой он не является.
