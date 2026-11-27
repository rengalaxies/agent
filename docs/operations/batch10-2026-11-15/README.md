# ImpactMap10: кандидат, CI и изолированная установка

15–16.11.2026. **Пачка10 целиком остаётся PARTIAL:** для её исходного AC нужны по3 живых цикла change/fix для Jira, Kaiten и Яндекс Трекера на одном релизе. Яндекс07/09 пока отсутствует. Здесь подготовлен и проверен технический кандидат без замены установленного сервиса.

Source: `8153bd1110dd1342329d88b91528d414219d1b4f`; исходная база `8334b6982602ebdd9541bc78736326e754d265a3`. Коммиты:13ea0bd — версии отчёта/CLI tests/A6;5d508a2 — read-only diagnostics; a7970e2 — CI/test dependencies/lint;8153bd1 — scoped process inventory приёмки. Все изменения локальные, без push/merge.

## Что изменено

- Операторские `GET /resources?limit=1..100` и `GET /result?resource_id=...` под существующим Bearer-token. Полный анализ и документ отделены от состояния текущего job и публикации. Предыдущий результат после нового отказа явно STALE; закрытый — CLOSED. Невалидный/отвергнутый raw не выдаётся как совместимый анализ. Нет записи, reconcile, вызовов трекера или файлового доступа по resource ID. Auth проверяется до параметров, ответы новых endpoints no-store/nosniff/no-referrer. Неверный не-ASCII Authorization возвращает401 вместо TypeError.
- Полный отчёт PR получает base/head из совместимого AnalysisRequest. Bitbucket snapshot хранит destination tip, а не merge-base: прежний пустой `base ,` устранён, неизвестные pins обозначены явно. Destination tip отдельно подписан при отсутствии base.
- CLI transport tests используют Python тестового окружения для parser/error/output checks, сохраняя настоящий0.4s deadline и cancellation. Продуктовый GraphCLI не расширял deadline: старая fake shebang запускала system Python через очищенный PATH; проба показала1.027s против0.024s у venv.
- `make test` и Core CI используют пути `src:.:tests:tools`; явно объявлен optional `test-evaluation` с jsonschema4.26.0, CI ставит rg на Ubuntu24.04. Runtime lock17 wheels не менялся. Шесть lint замечаний устранены без удаления обязательного `connector.fetch`; unused imports изменили evaluator component SHA, правила normalization2/scorer прежние. Перед независимой06 нужен новый зарегистрированный freeze, старые результаты не переписывались.
- Приёмка повторной установки считает launch-процессы только своего `--run` каталога. Другие установки на общей ВМ не становятся ложными дублями; два процесса внутри выбранной установки по-прежнему обнаруживаются.

[Инструкция оператора и контракт API](../impactmap-diagnostics.md). Это операторский API одной установки, не готовая админка и не публичная ссылка для всех участников трекера.

## Артефакт и неизменные свойства

`agent-service-0.1.0-g8153bd1110dd-linux-x86_64-cp312.tar.gz`, release ID `0.1.0+g8153bd1110dd.linux-x86_64-cp312`.

- Archive SHA256: `c1261e15ac68430a433c6e4404c8fdb136af5eceba9673a3349b3f0363b648d1`.
- Manifest SHA256: `e4ff78a732db90a65cb3b7083a0755ace281b495962d29fdd940035c422147b4`.
- Две отдельные offline-сборки из одного коммита и17 hash-locked wheels побайтово совпали. Wheels скопированы чтением из прежнего cache, без новых runtime dependencies.
- 85 файлов пакета сверяются с manifest. Box unit tests исключены из runtime release штатным builder; новый test_acceptance_scope выполняется отдельно из source.
- Core `http-requests-9`, output2.2, digest `d4ffae30456713d3280e33278d4e9f3fa9aa33e88167b45c2592d44fe3af30a1`, MODEL OFF. Collector defaults8 000 000 байт/2048 inventory/60s, per-file65 536 байт прежние. Service DB schema1, graph DB schema2 — без новой миграции этой пачки.

Архив остаётся в `work/batch10/candidate-final/` этого checkout; в Git сохранены manifest/receipts/hashes. Числовой VERSION0.1.0 — прежняя схема поставки; точная идентичность определяется SHA/release ID, это не объявление полного стабильного релиза10.

## Проверки и причины повторов

Финальный source8153: **1291/1291 Linux tests, без skips;78/78 installer tests; все5 installation/recovery scenarios PASS**. Архив отдельно прошёл verify-tree, packaged smoke и core identity. На действительно установленном prefixv3 проверены401 без operator-token, два полных результата под token и no-store. Prefix остановлен после проверки; тестовые HTTP-стенды закрыты. Production postflight: active/PID60331/commit a02ffa7/config SHA71dd9a7 совпали с preflight.

[Финальный Linux status](linux/status.json), [пять сценариев](linux/install-acceptance-v3.json), [установленные API](linux/installed-api-release.json), [матрица оставшихся AC](acceptance-matrix.json). Это техническая приёмка кандидата, не закрытие внешнего LIVE gate10.

Сохранены промежуточные неуспехи, а не только лучший прогон:

1. Mac baseline прерван после990 начатых тестов:82 наблюдённых failure/error markers (81 legacy SQL/product и1 CLI),4 Linux skips. Это не завершённая suite. RLIMIT_AS256MB на этом Mac отдельно даёт ValueError; защиту worker не ослабляли. В Linux legacy SQL проверки проходят.
2. Первый runner на Linux остановился до тестов из-за пропущенного tarfile import. Исправлен только test runner, исходный статус/лог сохранены.
3. Первый полный Linux прогон:1241 tests/17 errors/9 skips из-за отсутствующих test HTTP client/rg, root-контекста demo guard и отсутствующего tools в PYTHONPATH. Среда дополнена теми же pinned HTTPX0.28.1/httpcore/certifi; rg14.1.0 извлечён **внутри тестового каталога** из Ubuntu package с SHA256 `c5ae63c7bee915b1cfc9f0bd07c55b4ce7f2bcd1133cba4da56719aac26101a4`. Системные пакеты/guard не менялись. [Starlette описывает отдельную зависимость TestClient](https://starlette.dev/testclient/); переход runtime на новый HTTP-клиент здесь не проводился.
4. После исправления среды source5d508a2 прошёл1291/1291 без skips; box74 и packaged smoke/identity PASS. Финальный8153 затем проходит отдельные gates на том же Linux/Python3.12.3, обычный UID1000/GID1002, точный source pin.
5. Установкаv1 корректно отказала до старта без подготовленного файла **синтетических** stand secrets. В новом prefixv2 они заданы0600; fresh/end-to-end/recovery/backup-restore прошли, reinstall ложнопровалился из-за глобального подсчёта3 host-процессов. Raw FAIL сохранён; исправление scoped inventory закреплено4 RED→GREEN controls, включая обнаружение настоящего дубля одного prefix. Финальный prefixv3 новый, с новым архивом8153.
6. Mac box78 имеет3 platform errors (нет Python3.12, два теста readiness ticks);4 новых scope controls проходят. Авторитетный installer gate — Linux78. Global Ruff F401/F811/F841 прошёл; focused77, service61, CLI/version30, legacy import6 — дополнительные проверки, они пересекаются с полной suite и не суммируются как независимые кейсы.

SSH был нестабилен; ВМ повторно проверена самим исполнителем. Передачи тестовых архивов завершены через SFTP с SHA-проверкой; новые ключи/IP не создавались. Тестовый каталог `/var/tmp/impactmap-batch10-5d508a2e301d-20261115` — namespace всей сессии, **не SHA финального кандидата**. Source/release identity берутся из manifest/status. Там сохранены старые состояния; production directory не использовался для испытаний.

## Границы приёмки10

| Исходный пункт | Что подтверждается здесь | Что остаётся |
|---|---|---|
| Один выбранный pin и инструкция | Source8153, reproducible archive, lock/core/state identities, операторский API | Применение к реальной installation policy и всем трём трекерам |
| По3 change/fix цикла Jira/Kaiten/Яндекс без дублей | Unit/injected и loopback проверки; свежих external LIVE циклов этого pin0/0/0 | Яндекс07/09, затем все3 серии на общем release |
| Перезапуск и восстановление | Linux-only unit cases и отдельный process-supervisor prefix | systemd/reboot нового pin и production recovery не проводились |
| Backup/restore | Изолированное тестовое состояние того же candidate | Production restore/downgrade a02ffa7 остаются отдельным открытым gate |
| Сверка стенда | Read-only GitHub/local/loaded runtime и config hash | Установленный worker не заменён новым кандидатом |

`publication=live` внутри loopback stand означает HTTP к **локальной эмуляции**, не запись в настоящий Jira/Kaiten. Process supervisor восстанавливается повторным installer run, не объявляется systemd autostart. Существующая08 cloud acceptance остаётся исторической, не засчитывается как три свежих цикла10. GitHub Actions на этой локальной ветке не запускался; Linux CI здесь выполняется в изолированной копии exact source. Real06 всё ещё NOT_REGISTERED / NOT_RUN,0 новых независимых случаев/экспертов. Author40/scorer/oracles не перенастраивались.

## Безопасная поставка и продолжение

1. Проверить manifest/archive hash и полный журнал gates. Выбрать явный release/policy, не ставить по одному слову «latest».
2. Для реальной установки отдельно согласовать Bitbucket/Jira/Kaiten configuration, mirrors/pins, grants, bindings, URL/TLS и операторский token. Явные policy2MB сохраняют своё значение при кодовом default8MB. Секреты только в закрытом конфиге окружения; этот отчёт их не содержит.
3. Сделать backup конкретного работающего pin, проверить scratch restore, затем применять выбранный release на выделенном стенде с планом возврата. Не направлять приведённые prefix/process команды на `/` и не перезапускать установленный worker автоматически.
4. После09 пройти три свежих цикла каждого трекера и полный systemd/recovery gate. До этого10 не помечать DONE.

Добавлена [A6: обсуждение UI/админки](../../product/roadmap-2026-11-14/UI-ADMIN-BATCH.md). Исходные14+A1–A5 сохранены; теперь6 дополнительных пачек. После технической части10 можно обсуждать интерфейс и роли, не ожидая Яндекса. Интервью01 и независимые06/11 продолжают требовать реальных участников.

## Проверка сохранённых данных

Из корня checkout, стандартный Python:

```sh
python docs/operations/batch10-2026-11-15/reproduce/verify.py
python docs/operations/batch10-2026-11-15/reproduce/verify.py --archive work/batch10/candidate-final/agent-service-0.1.0-g8153bd1110dd-linux-x86_64-cp312.tar.gz
```

Verifier проверяет полный набор/hash файлов, manifest/current runtime bytes, сохранность прежних research/scale artifacts, строгие counts/outcomes и набор всех5 installation scenarios, installed API и неизменность установленного worker. Это проверка инженерных артефактов, не независимая оценка продукта. Для будущего изменённого кода проверять в отдельном checkout соответствующей версии отчёта.

Для новой сборки нужен тот же source8153 и существующий venv с runtime dependencies:

```sh
python tools/agent_service/box/release.py build --commit 8153bd1110dd1342329d88b91528d414219d1b4f --platform linux-x86_64-cp312 --output work/batch10-rebuild-fresh --wheelhouse work/batch10/wheels
```

`reproduce/*runner*.py`/linux_driver — точные контроллеры этой сессии с конкретным приватным SSH profile и namespace, **не универсальный установщик**. Не выполнять bootstrap поверх существующей сессии или слепо повторять завершённые сценарии. Исходники, receipts и [решения ревью](review.md) сохраняются для аудита; для нового стенда подготовить отдельные paths/порты и только его тестовые secrets.
