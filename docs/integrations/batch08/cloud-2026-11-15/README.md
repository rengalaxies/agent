# Пачка08: настоящие Bitbucket Cloud и Kaiten, Linux worker

15.11.2026. Изолированная приёмка кандидата поверх e22413a; adapter c44a3c6. MODEL OFF. Установленный runtime a02ffa7 не заменялся. **AC08 закрыты в изолированном cloud-профиле**; ограничения403/удаления описаны ниже. Итоговые статусы — в acceptance.json; файлы receipts сохраняют все завершённые этапы без отбора лучшего результата.

## Источник и результат

- Созданы отдельная ветка `impactmap-kaiten-cloud-20261115` и [PR5](https://bitbucket.org/rengalaxies/agent-pilot-orders/pull-requests/5). PR остаётся OPEN, merge не выполнялся. Авторские учебные приложения, не данные заказчиков.
- Change `3386e00625bbed290957f7e384f8c5858ee56fe6`: default `page_size` 100→20. Реальные Bitbucket API/Git/CoreAnalyzer/queue/Publisher/Kaiten дали USEFUL/POSSIBLE_TRUNCATION. Base orders `5d405f22a0d919dd395fa02339c9170de20a89f7`, consumer reporting `6ebf07174eb9ef4018a98ccf14da1cb94b6a69e3`.
- Fix `3883320d4725479f944298c322fa493dfc836457`: 20→100, один изменённый параметр; `/orders/summary` сохранён. ABSTAINED/no_supported_delta, находок нет. Это отсутствие поддерживаемого delta, не доказательство общей совместимости.
- Result native comment **93817019** на [основной карточке74759475](https://rengalaxies.kaiten.ru/space/941235/lists/card/74759475?focus=comment&focusId=93817019) обновился на месте. Повторы change-replay/corrected-replay: steps=[], прежнее generation/ID/digest, по одному результату на marker `50f72df743af8977`.
- На основной карточке также остались два ранее созданных диагностических комментария с другими markers (API probe и local-source hybrid); это отдельные источники/назначения, не дубли PR5.

## Реальное прерывание и восстановление

Worker PID1622223 был приостановлен после подтверждённого публичным чтением результата, до локального delivery commit. Записаны PID/start ticks, SENDING intent/lease, remote scoped ID/digest и device/inode SQLite. Контроллер заново проверил эту точку и отправил SIGKILL только этому процессу.

После штатных300s lease (без изменения SQLite/часов/настроек очереди) новый PID1627786 на той же БД восстановил sending=1, intent прошёл UNKNOWN→DELIVERED. Receipt wrote=false, steps=[publish:unchanged], прежние native ID93817019/digest. Повтор не записал комментарий и не создал поколение. Это проверка process crash/restart, не reboot VM или отключение питания.

## Жизненный цикл настоящих целей

Явно разрешённая владельцем disposable-карточка74807549 без parent/child связей. Relink primary→secondary создал один scoped result93817124 (generation3). Удаление только доказанного marker/author/native-ID/digest результата + явное изменение description вызвали следующий анализ: один новый result93817131 (generation4). Это восстановление при новом семантическом событии, не фоновый контроль удаления в простое. SQLite не редактировалась.

condition2 реально архивировало карточку; worker сохранил closed=true, шаг ingest:closed, без нового intent/записи. condition1 восстановило её; generation5 обновило тот же native comment93817131.

После единственного DELETE карточки follow-up GET вернул **403**. Контроллер, ожидавший404/condition3, остановился; этот первоначальный контроль НЕ объявлен PASS и DELETE не повторялся. Дополнительный read-only probe подтвердил исправный ключ (users/current и основная карточка200), недоступность только тестовой цели403. UI также показал «Карточка #74807549 стала недоступной». Тело успешного DELETE до follow-up не было записано: доказана недоступность после попытки удаления, не наблюдение condition3/404 и не отсутствие данных в серверном хранилище.

Настоящий Service.reconcile/run_until_idle с этой целью завершился управляемо: reconcile_failed заметен, очередь jobs/intents неизменна, steps=[], внешних записей нет. 403 сохраняется как connection_unauthorized, поскольку код не различает удаление и отозванный доступ. Автоматически считать такой ресурс удалённым небезопасно; смена корректной привязки восстанавливает обработку. Отдельные404/deleted/condition3 ветки остаются локальными тестами. [Официальные DELETE](https://developers.kaiten.ru/cards/delete-card) и [Retrieve](https://developers.kaiten.ru/cards/retrieve-card) документируют403/404; обещания обязательного404 после удаления в использованном контракте нет.

Возврат primary→основная карточка дал generation6, тот же native ID93817019 и один текущий result; reconcile_errors=[] после прежнего403. Изолированный binding снова74759475. Установленный worker active, PID60331, SHA a02ffa7854dcc38cecc7fe5c5317466059926cd9, хеш service.json прежний; тестовая копия secrets.json удалена под acceptance lock.

## Тесты и provenance отказов

- Linux: **157 тестов, 0 пропусков**, в том числе4 настоящих process SIGKILL cases; [сводка](linux-tests-summary.json).
- Helper:12 тестов, из них review repros для изоляции, manifest/pins, current intent/readback и подлинности recovery. [Разбор ревью](review.md).
- Настоящий Kaiten GET users/current с заведомо неверным тестовым Bearer вернул HTTP401 / connection_unauthorized; реальный ключ не отзывался/не портился.
- 429/5xx, потеря applied write/readback, source races и foreign/off-board относятся к локальным HTTP/injected тестам из ../tests.log и Linux suite. Настоящий API не перегружали и серверный отказ не имитировали как live.

## Изоляция и воспроизведение

session.json фиксирует sandbox, resource ID, local-anchored manifest SHA и состояние установленного runtime перед тестом. Ровно506 файлов кандидата проверены по байтам; модульные origins должны вести в app этого sandbox. Собственные policy, constitution, mirrors, SQLite, installation/environment и явная привязка только PR5. Runtime/model context извне запрещён.

Git mirrors скопированы **внутри dm-p1-ui**, без вывоза Git/исходников со стенда. Родительский `git -c safe.directory` не дошёл до upload-pack; разрешение exact source path передано непосредственно дочернему upload-pack. Глобальный/production Git config не менялся. SSH имел connect timeouts; после подключения использовано pinned-host multiplexing.

Ключ передан только после отдельного согласия владельца по SSH stdin, тестовый secrets.json mode0600, root0700. Production env/config/state не публикуются. Финальное удаление тестовой копии подтверждает cleanup.json. Локальная исходная копия ключа остаётся в ignored private каталоге владельца; сам ключ в Kaiten не отзывается.

`control-driver-used.py`, `resume-bootstrap-used.py`, `lifecycle-driver-used.py` — точные журнальные scripts этого запуска, **не универсальный установщик**: они ссылаются на приватный SSH профиль/локальный private token и конкретные pilot IDs. Не запускать bootstrap повторно поверх существующей session, не сбрасывать очередь/marker после неизвестной записи. Контроллер возвращает фиксированные квитанции/сводки, generic raw file read отсутствует. Для нового запуска нужны отдельная санкционированная тестовая цель, новый run ID и manifest текущего candidate; secrets не передавать в аргументах/логах.

Это один технический авторский cloud цикл; независимая оценка06, три последовательных цикла всех трекеров10, установка нового release, reboot/production restore и пользовательская польза этим запуском не подтверждаются.

Проверка интерфейса: [снимок PR5](bitbucket-pr-created.png), [исправленный комментарий](kaiten-result-visible.png). Скриншот комментария снят на generation2; финальное возвращение generation6 подтверждено receipts/returned-primary.json. В компактной строке PR поле base пока пустое; правильный base присутствует ниже в списке snapshots и квитанции. Исправление этой строки — задача представления/диагностики10.
