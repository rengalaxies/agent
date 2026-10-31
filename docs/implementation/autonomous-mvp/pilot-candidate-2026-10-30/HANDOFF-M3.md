# Передача M3 — код принят, установка не квалифицирована

## Обновление 31.10.2026

#81 согласован по поручению владельца и слит в `5f60a0fb88369f1e1e7da00b960f6b6ed462c614`.
#72 автоматически merged через его историю. Код profile6 принят; новый release не опубликован.
[Протокол проверки](../profile6-integration-2026-10-31/README.md).

**Recovery blocker:** текущий `box rollback` при одинаковой schema выбирает release_only
и запускает старый сервис. Инструкция «остановить публикацию» ниже не означает, что
эта команда сохраняет остановку. Code-only rollback к release14e на новом profile6 state
не квалифицирован. До установки отдельно проверить matching pre-update backup/recovery
до старта старого writer и контроль публикации; не выполнять такой downgrade по этому
документу. Pin, ВМ и #71 прежние. Остальной текст — исторический handoff кандидата,
его PENDING_APPROVAL снят только в отношении кода, не установки или LIVE.

Не команда установки. #71/#72 не изменялись и не сливались. Хост/Cloud.ru не обследовались.
Никаких старых IP, SSH pins, host keys или credentials в этом handoff нет.

## Версия на согласование

- База main этапа: e84e91395a8846e2f43df3a1a6e402e3487e7a27, #78/#79 включены.
- #72: f25e82f9a83f4e15bdfeb16088fdf1fc6d335bee.
- Дополнение: прямой setattr/delattr инвалидирует положительное binding; профиль **6**,
  а не прежняя 5. Source-status, demo profile guard и PARTIAL next action исправлены отдельно.
- Service payload проверен на 99ce1f0ecd39c838b0a8613d64311655c743321f;
  окончательный integration head и CI находятся в описании собственного draft PR.
  Ack должен явно относиться к этому финальному SHA/составу. При новых product changes — новая сверка.
- SQLite state schema 1 и result schema 2.1 сохранены; model/qualification OFF.
- Действующий pin остаётся agent-service-0.1.0-g14e65e8affe3-linux-x86_64-cp312,
  archive 95648b846da2dd8fbdfdf76942d1c9563bc4be5d3f2cbfad3987ec3eade8a013.
  Это проверенный прежний published asset; его фактическая установка не установлена.

Текст для передачи (в описании PR заполнен точным окончательным head):
«M3, прошу согласовать указанный integration SHA: #72 f25e82f + новые минимальные fixes,
profile4/5→6, без schema/deployment/pin/installer/credentials изменений. Старые contexts,
knowledge/code bases становятся STALE до rebuild; existing basis reconciliation обновляет
те же comments, deferred source не принимает basis. LOCAL/CI и ограничения приложены.
release14e остаётся прежним checkpoint; это не разрешение устанавливать на остановленный
хост. После ack — reviewed merge и отдельный новый release из фактического main. Подтвердите
SHA/состав либо перечислите возражения». Сам запрос не является согласием.

## Сборка и передача

В чистом checkout согласованного SHA, Python 3.12/Linux x86_64:

```bash
python -m pip download --only-binary=:all: --require-hashes -r infra/agent_service/requirements.lock --dest work/candidate-wheels
python tools/agent_service/box/release.py build --commit EXACT_SHA --wheelhouse work/candidate-wheels --output dist/candidate-A
python tools/agent_service/box/release.py build --commit EXACT_SHA --wheelhouse work/candidate-wheels --output dist/candidate-B
cmp dist/candidate-A/*.tar.gz dist/candidate-B/*.tar.gz
(cd dist/candidate-A && sha256sum -c ./*.sha256)
mkdir -p work/candidate-extracted
tar -xzf dist/candidate-A/*.tar.gz -C work/candidate-extracted
python tools/agent_service/box/release.py verify work/candidate-extracted/agent-service-*
```

До ack архив остаётся локальным, статус PENDING_APPROVAL; binary release assets не публиковались.
CI хранит только безопасные manifest/checksum/проверки. После accepted main использовать
существующий agent-service-release.yml с expected_main_sha=фактический полный main SHA.
Он требует main, строит дважды, не заменяет существующий тег, скачивает published asset
и проверяет его с install-published. Новый SHA меняет имя/manifest/archive; нельзя ставить
старый checksum из этого отчёта к новому архиву. Pin здесь не обновляется.

## Обновление состояния

Старые contexts/profile4/5 и proposals (включая legacy без config digest) становятся STALE.
История остаётся. Default-branch graph перестраивается; source unavailable должен быть
виден через status/doctor и блокировать basis checkpoint до восстановления. Wrapper/другая
неподдержанная грамматика означает PARTIAL, но не потерю доступа к repository.

Existing version/basis reconciliation после чистого graph reopens открытые Jira/PR,
не меняя resource versions и comment IDs. LOCAL это подтверждено с 3 комментариями,
новым head и restart после ANALYZED до send. Не удалять queue/core SQLite и не править их
вручную. Закрытые/удалённые источники и роли сохраняют существующие ограничения доступа.

БД и внешний API не атомарны. Во время недоступности worker/API/source старое тело может
оставаться до stale notice и нового result. Не обещать автоматическое мгновенное исправление
или ограниченное число секунд. Наблюдать очереди/intents/notices и фактические версии.

## Проверки оператора после восстановления хоста и отдельного разрешения установки

1. Самостоятельно заново установить доверие к хосту, сделать инвентаризацию и matching backup
   действующих конфигураций/queue/core state средствами box. Один оператор; incoming events
   и публикация не должны идти параллельно switch/restore.
2. Проверить exact archive checksum и manifest, выполнить box plan с подтверждённой config.
   Никаких догадок о credentials/URLs. Пройти штатный update: backup предшествует открытию
   state новым кодом, graph task предшествует start и должен отказать при UNAVAILABLE.
3. box status/doctor должны показывать ожидаемые loaded code_version/release/core/profile,
   manifest/binding совпадение, process_ready и отсутствие graph_source_unavailable.
   Сверить очередь/историю и явное завершение basis reconciliation по version/base/head.
4. Пройти реальный restart/reboot, потерю API, новый head, дубликаты, own-comment и
   восстановление очереди; сохранить IDs, request/event IDs и длительность stale window.
5. Откат: использовать штатные backup/backups/rollback/restore и matching schema backup.
   Прямое открытие нового state старым кодом может ложно показать CURRENT до rebuild;
   старый release14e этим не квалифицирован. Держать публикацию остановленной до проверки
   loaded identity, graph и reconciliation. Восстановить поток только после этих проверок.
6. Подтвердить остальные M3 ресурсные/backup/restore проверки на целевом хосте. CI systemd
   не заменяет ВМ; локальные stands не заменяют настоящие Jira/GitHub.

Наша virtual merge с #71 5ac9dbb выявила content conflict только сохранённого плана
docs/superpowers/plans/2026-10-28-mvp-delivery-ownership.md; STATUS/READINESS auto-merge.
M3 разрешает свой конфликт в своей ветке, сохраняя stopped-host/support и новые evidence;
мы #71 не редактировали. Перед действием повторить сравнение актуальных heads.

Участник, реальный проект, ВМ, service App/Jira/HTTPS и LIVE остаются NOT_RUN.
