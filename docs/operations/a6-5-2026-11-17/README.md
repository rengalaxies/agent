# A6.5 — отдельный UI-пилот и HTTPS по публичному IP

17.11.2026. **PARTIAL: техническая поставка выполнена; LIVE-переходы из трекеров и личная приёмка владельцем открыты.** Исходные14 основных пачек и A1–A5 не перенумерованы. Пользователь попросил использовать публичный IP Cloud.ru вместо домена/обязательного SSH-туннеля.

Вход: **https://82.202.141.50/ui/login**. Username `owner`; случайный пароль передан с явного согласия владельца только в локальный ignored файл `work/a6-5/private/owner-access.txt`, mode0600. Пароль/QA-пароли/ключи/сессионные cookies в этот отчёт и Git не включены. Первую попытку переноса credentials автоматическая проверка разрешений отклонила; затем пользователь явно разрешил owner-only передачу. QA-пароли с ВМ не переносились.

## Что поставлено

- Source29ed2ad8fc2e; отдельный immutable Linux release,17 hash-locked wheels, Python3.12.3. `/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312`; отдельная unit `impactmap-ui-pilot.service`, service UID `impactmap-ui`, bind127.0.0.1:18092, отдельное состояние `/var/lib/impactmap-ui-pilot`. Операторские файлы `/etc/impactmap-ui-pilot` защищены root:impactmap-ui,750/640; auth/settings остаются service-owned700/600.
- Существующий nginx: IP-specific80 virtualhost обслуживает ACME и redirect,443 даёт только `/ui/` и переходы `/`/`/ui`. `/status`, `/resources`, `/graph`, `/webhooks/...` снаружи404; legacy API не открываются. Backend получает исходный Host, не доверяет forwarded headers. HTTP-логин не предлагается, Bearer в браузер не передаётся.
- Доверенный Let's Encrypt certificate с IP SAN82.202.141.50, проверка цепочки/адреса без исключений. Полученный leaf действителен17–23.11; IP-сертификаты короткоживущие, поэтому включён `impactmap-tls-renew.timer` дважды в сутки. [Официальная инструкция](https://letsencrypt.org/2026/03/11/shorter-certs-certbot). Certbot5.4.0 в отдельном venv `/opt/impactmap-tls/venv`, не меняет runtime dependencies продукта.
- Постоянный executable deploy hook `/etc/letsencrypt-impactmap/renewal-hooks/deploy/20-impactmap-nginx`: nginx -t, reload, несекретная отметка времени. Его используют и timer, и dry-run. Первый dry-run без переданного inline hook **не считается проверкой reload**; исправленный dry-run проверяется отдельно. Будущая реальная production-ротация ещё не произошла.
- BoxConfig.ui.origin теперь явно включает UI и private settings. Наличие старого файла UI не включает. Изменение origin меняет fingerprint в root-owned generated ServiceConfig и activation digest, заставляя перезапустить процесс. Пароли/сессии не входят в этот fingerprint. Bootstrap выполняется существующим task() под service UID; root не пишет в service-controlled UI namespace. Symlinks/чужой owner/private mode отвергаются; временный файл непредсказуемый, O_EXCL/O_NOFOLLOW,0600.
- Backup теперь включает service, graph и `ui/auth.sqlite`. Restore проверяет hashes/integrity/counts, затем **до swap** выключает все восстановленные аккаунты и удаляет sessions/challenges; включение/новый пароль — локальным ui_admin под service UID. Это препятствует возврату отозванного доступа из старой копии. Backup без auth удаляет текущую auth DB и оставляет UI закрытым. Config/origin при restore не заменяются.
- Service формирует фиксированную URL `/ui/result?resource_id=...` только из private validated HTTPS settings; URL не содержит токена. Jira summary и сокращённый Kaiten-комментарий сохраняют ссылку. CLI reconcile получает те же settings до анализа/публикации. Внешний пользовательский document/navigate GET результата и login redirect допускаются; cross-site API/fetch/iframe/mutation по-прежнему403. Session/role/scope проверки сохраняются.

## Какие данные в UI

Это **новые offline-прогоны настоящего CoreAnalyzer по сохранённым авторским pins15.11**, без импорта старых результатов или backfill scope receipts. Installation `impactmap-ui-pilot`, environment `offline-pins-20261115`. Ключи SCM/Jira/Kaiten на UI-пилот не переносились, внешние публикации не запускались. Источники показываются как неподключённые, а не как LIVE PASS.

| Ресурс | Commit Orders | Итог |
|---|---|---|
| bitbucket:offline-pilot/orders#5-change |3386e00625bbed290957f7e384f8c5858ee56fe6|USEFUL / impact_found_within_profile|
| bitbucket:offline-pilot/orders#5-fixed |3883320d4725479f944298c322fa493dfc836457|ABSTAINED / no_supported_delta|

Reporting pin6ebf07174eb9ef4018a98ccf14da1cb94b6a69e3; base Orders5d405f22a0d919dd395fa02339c9170de20a89f7. Статический профиль http-requests-9, output2.2, MODEL OFF. CURRENT относится к локальному поколению этих pins, не к нынешнему удалённому PR. Публикаций0. Новый потребитель/широкий mixed-stack/независимое качество не заявляются.

## Проверки и исправления

[Независимый source review](review.md):1 Critical,4 Important. Один fix-pass29ed2ad: делегирование UI bootstrap, навигация из трекера, origin activation digest, CLI reconcile link. Постоянный TLS hook исправлен в поставке. Bare /ui404 повышен до Important, поскольку туда ведёт логотип, и исправлен отдельным redirect. Санитизированные nginx/systemd configs и рецепты включены в отчёт. Отложенных новых Minor нет;2 прежних Minor A6.4 не входили в исправление.

RED→GREEN: symlink/victim protection, unchanged-origin digest, external navigation403→303→login→тот же локальный result, cross-site API/iframe/mutation403, CLI reconcile link, persistent deploy hook. Итоговый локальный focused-run99 PASS. Предварительный Linux кандидат659185f:1365 tests PASS/418.631s; box85 PASS; immutable artifact verify и packaged smoke PASS. Финальный29ed2ad: **1368 tests PASS/421.306s (wall423.251s),86box PASS/8.593s**, artifact verify и packaged smoke PASS, nonrootUID1000. Логи в final-* evidence. Первый QA entrypoint был ошибочно назван ci-runner-final.py вместо доставленного ci-runner.py: тесты тогда не стартовали; имя исправлено, окончательный полный прогон завершён. Ошибка запуска сохранена и не маскируется успешным run.

На установленном кандидате проверены через TLS с обычной CA/IP-проверкой:401 без сессии; operator видит2 результата; reviewer получает403 операторских API; Secure/HttpOnly/SameSiteStrict cookie; новый UI restart сохраняет действующую сессию; service+graph+auth backup проверен и восстановлен **в отдельный scratch**, все3 восстановленных аккаунта выключены и sessions/challenges пусты. Это не restore production/старого worker. Старый agent-bitbucket PID60331 и installed a02ffa7854dc сохранились; свежие receipts в evidence.

Первый seed не стартовал из-за0700 QA-каталога, недоступного service UID; скрипт перенесён в разрешённый операторский каталог, повтор прошёл. Shell и встроенный браузер наблюдали перемежающиеся внешние TCP/SSH timeouts; host low load, INPUT ACCEPT, локальный trusted TLS login работает. Это ограничивает заявление о стабильности внешнего входа; конкретный внешний browser outcome записывается отдельно.

## Остаток A6.5

1. Настоящие Jira/Kaiten publication→readback→protected deep-link циклы на конкретном новом release; их не заменяют renderer/ASGI/локальные API-тесты. Доступы и разрешённые цели проверить отдельно; старое разрешение переноса ключа было для08.
2. Личная приёмка владельцем/оператором пяти сценариев из утверждённого дизайна, включая keyboard/focus/zoom и реальные замечания. Авторские проверки не заменяют участие владельца.
3. Наблюдение следующей реальной production-ротации leaf; staging renew/hook не объявлять уже случившейся production-ротацией. Уточнение сетевых таймаутов, если повторятся у владельца.

Яндекс07/09 и общий LIVE gate10 трёх трекеров остаются открытыми. Независимая06, реальные01/11, продуктовые12 и синхронизация13 сохраняются.

## Эксплуатация

`sudo systemctl status impactmap-ui-pilot impactmap-tls-renew.timer`; `sudo journalctl -u impactmap-ui-pilot`; `sudo nginx -t`. Не заменять `agent-bitbucket.service` или его current symlink этими командами. При потере public IP/его смене нужно остановить/перенастроить этот вход и заново подтвердить контроль нового адреса для CA; старый IP-сертификат новый адрес не покрывает.

Пользователи: установленный `python -m agent_service.ui_admin --config /etc/impactmap-ui-pilot/service.json --ui-config /var/lib/impactmap-ui-pilot/ui/ui.json ...` **под `impactmap-ui`**. Пароль интерактивно, не argv/Git. Состояние и закрытые backups остаются на ВМ; приватные ключи TLS — в `/etc/letsencrypt-impactmap`. Новых runtime deps или модельного слоя нет.

Рецепты [reproduce](reproduce/) предназначены для выделенной авторской ВМ/фиксированных путей и pins, не являются универсальным unattended installer. Для обычной box-установки используется BoxConfig.ui.origin и service-owned bootstrap. Все существенные решения: работать в существующем worktree; fingerprint вместо привилегированного чтения UI-файла; отдельный offline pilot до LIVE-доступов; bare /ui исправлен как нормальная навигация. Цена границ — A6.5 PARTIAL, не полная исследовательская/операторская приёмка.


Финальная browser-проверка: внешний trusted HTTPS login owner PASS после ранних сетевых отказов; change USEFUL, fixed ABSTAINED/no_supported_delta, operator ANALYZED:2/outboxнет, connections NOT_CONNECTED, source evidence anchor focus evidence-2, body14px/без horizontal overflow. Снимки browser-*.jpg и browser-verification.json. Keyboard/200%-zoom/contrast и пять сценариев **владельцем** целиком этим не закрыты. Существующий prototype18087 и пользовательские вкладки сохранялись; итоговая вкладка20 оставлена владельцу. Собственная неудачная вкладка19 осталась из-за запрета браузерного инструмента читать его data:error URL; это не обходилось.

После проверок временные qa-operator/qa-reviewer выключены с отзывом сессий; исходный plaintext initial-access.json на ВМ удалён под service UID. Owner и его закрытый локальный файл сохранены. Итоговый loaded receipt подтверждает29ed2ad и constitution_path внутри **того же** release, PID прежнего worker60331. Последний UI restart/readiness PASS.
