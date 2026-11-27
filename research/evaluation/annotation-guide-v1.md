# Инструкция куратору и двум экспертам

Версия: v1, 14.11.2026. Основа: [protocol-v1.md](protocol-v1.md). Состояние: подготовка будущей разметки; реальные эксперты ещё не назначены.

## Роли и порядок

Куратор собирает разрешённые входы, проверяет происхождение и split, выдаёт одинаковые материалы двум экспертам, ограничивает доступ к gold и регистрирует freeze. Два эксперта независимо размечают все cases. Третий реальный специалист нужен только для неразрешённых разногласий. Автор ImpactMap не является независимым экспертом по собственному результату. Модель может помогать форматировать, но не подписывать экспертные метки.

До заполнения формы каждый эксперт получает краткое описание задачи, base/head и список репозиториев/прав, service-map, контрактные ожидания и разрешённые команды проверки. Он не получает blueprint slot, ответы ImpactMap/LS1, другую разметку, желаемые числа метрик и подсказки «этот кейс должен быть положительным». Смысл протокола и критерии профиля известны обоим.

Внешний gold хранить в отдельном закрытом workspace куратора, не в этой Git-ветке. Обычная `.gitignore` не является контролем доступа от агента, читающего весь диск. При работе на одном компьютере не запускать анализатор/агента с доступом к gold. До запуска куратор фиксирует, кому точные cases/gold были доступны.

## Пошаговая разметка кейса

1. Убедиться, что SHA и файлы доступны и соответствуют manifest. Сверить scope доступа. Не делать fetch сегодняшней ветки вместо pin.
2. Прочитать diff и определить меняемые операции. Проверить service-map/host/method/path. При двух подходящих provider пометить неоднозначность, не угадывать.
3. Самостоятельно перечислить фактические consumer-calls и их snapshot/path/statement ranges. Поиск строки — способ найти кандидата, а не доказательство вызова. Для каждого указать, относится ли он к данной операции.
4. Выписать независимое ожидаемое поведение потребителя: что он должен получить, почему именно это ожидание, где источник. Для page_size неизвестное требование полноты означает UNRESOLVED, если иначе нельзя доказать нарушение.
5. Для каждого ключа выбрать AFFECTED / UNAFFECTED / UNRESOLVED; приложить аргумент/контракт/контрольную команду. Различать «использует операцию», «может потребовать ревью» и «этот переход нарушает ожидание».
6. Назначить профиль IN_PROFILE / OUT_OF_PROFILE и конкретную boundary: grammar, semantics, access. Не определять профиль по ответу продукта. Указать ограничения полноты поиска.
7. Для отсутствия потребителей перечислить обследованные snapshots/inventory, способы проверки и основания полноты в разрешённом скоупе. Если часть скоупа недоступна, это не NO_CONSUMERS_IN_PROFILE.
8. Записать допустимые witnesses и source phase. Для удаления endpoint при сохранении потребителя допустим его base-call. Если сам вызов удалён/исправлен в заданном consumer head, не оставлять старую связь положительной без актуального основания.
9. Сохранить собственный reference-label со stage=independent, настоящим expert_id, временем и attestation. После сдачи он неизменяем; исправления — отдельная версия с причиной.

## Согласование

Куратор сначала сохраняет обе исходные разметки и их hashes. Составляется union выписанных ключей; оба эксперта явно оценивают пропущенные у них ключи, всё ещё без вывода систем и без подмены исходных файлов. Затем обсуждаются только конкретные расхождения с просмотром исходников/ожиданий.

Итоговый reference-label stage=adjudicated ссылается на два independent файла и их hashes; хранит разногласия, принятое решение и основание. В согласованных ключах сохраняются accepted witnesses, label и rationale. Если мнения не сошлись, третий эксперт либо UNRESOLVED. Нельзя выбирать вариант, который делает метрику выше.

Если до freeze осталось UNRESOLVED, куратор разбирает причину или заменяет candidate по той же квоте. Журнал отклонённых кандидатов сохраняется. После freeze заменить/исключить case нельзя; отчёт становится INDETERMINATE в части подтверждающего вывода. Вновь найденная зависимость, отсутствовавшая в gold, также требует аудита gold, а не автоматического FP.

## Контракты файлов

| Артефакт | Назначение и обязательное перед запуском |
|---|---|
| `case-input` | Только разрешённый input: opaque case_id, task/hints, pinned repositories/service-map, policy и budget refs. Никаких gold labels/strata. Draft может быть пустым; ready требует pins/rights/hashes. Hints могут быть пустыми; каждый непустой hint имеет basis_kind и hash исходного task/diff |
| Закрытый design catalogue | Связь blueprint slot → case_id → stratum/origin_group, provenance/разрешения/split; отсутствует среди runner inputs. Одна строка — один переход |
| `reference-label` independent | expert_id, самостоятельная разметка, witnesses и подпись аттестации; два файла на каждый case |
| `reference-label` adjudicated | ссылки/хеши обеих independent разметок, итоговое решение и объяснение расхождений; в complete нет UNRESOLVED |
| `normalized-prediction` | raw artifact SHA, method/config/attempt, status, все candidate bundles и invalid candidates, техническая ошибка/limitations/claims. Не содержит gold-match verdict |
| Закрытый freeze manifest | protocol/code/core/deps/runtime/corpus/scorer/baseline/rights hashes, order/budgets, approval и полный список назначенных cases; snapshot manifest не должен содержать секреты |

Полное описание ограничений и полей — в JSON Schemas. Пустые [input](templates/case-input.template.json), [reference](templates/reference-label.template.json) и [prediction](templates/normalized-prediction.template.json) проходят только draft-ветвь схем. Это **не готовые cases/labels/results**.

Хеши файлов/артефактов — SHA256 точных сохранённых bytes, до передачи системе, с явным форматом/кодировкой; нельзя хешировать переотформатированный JSON и сверять его с исходными bytes. `input_packet_sha256` относится к отдельному архиву разрешённых исходников/task/policy/hints, **не** к содержащему это поле case-input JSON: циклического self-hash нет. `raw_artifact_sha256` — hash неизменяемой записи попытки с stdout/stderr/exit/timestamps; он существует и при FAILED без корректного AnalysisResult.

`tree_sha256` — собственный content-manifest digest, не Git tree SHA-1. Куратор сохраняет manifest всех tracked entries обоих назначенных provider snapshots либо consumer head. Строки — `[phase, commit, relative_path, git_mode, kind, content_sha256_or_gitlink_oid]`, отсортированные по `(phase, relative_path)`; digest — SHA256 UTF-8 JSON списка строк с `ensure_ascii=False, separators=(",", ":")`. Для blob/symlink хешируются bytes Git blob без следования symlink, для gitlink записывается только его OID; файлы извне репозитория не читаются. Такой manifest может существовать у куратора до отключения доступа в boundary-кейсе, но в input нельзя передать сами запрещённые bytes/пути. В runner-пакете остаётся только разрешённая metadata/hash; Git mode и недоступность не превращаются в прочитанный файл. Схема проверяет лишь формат digest, фактическое соответствие manifest — обязанность evaluator 06.

### Дополнительные проверки между файлами

JSON Schema недостаточно для следующих условий; будущий evaluator 06 обязан их проверить и записать evidence:

- в input нет case stratum/slot/expected answer; input-packet не содержит файл, чьё имя/контент раскрывает gold;
- case IDs уникальны, все 40 назначены по нужным квотам закрытого каталога; origin group целиком в одном split; к прежним evaluation/development нет запрещённого пересечения;
- repository names уникальны; один service на file-prefix; у provider base/head, у consumer назначенный head; provider flag и operation hints согласованы; входные hashes совпадают с полученными bytes;
- claims/witnesses gold относятся к case и его snapshot; repository/path внутри allowed inventory; line_start ≤ line_end и в пределах файла; quote/hash совпадают с bytes; доступ отдельно учитывает отсутствующие репозитории;
- каждый AFFECTED/UNAFFECTED key однозначно соответствует operation hint/service-map; duplicate keys не дают добавочных TP; для AFFECTED есть expectation и witness; отсутствие строк label не доказывает UNAFFECTED;
- в adjudicated complete нет unresolved keys, профиль/stratum согласованы, 20 positives имеют G≠∅, 10+4 negatives G=∅; у NO_CONSUMERS есть scope-completeness rationale;
- два independent expert_id различны, реальные люди, не developer/case author; аттестации подтверждены людьми. Дата independent до adjudication, adjudication/gold-freeze до первого output;
- prediction config/method/case_id/raw hash и attempt соответствуют registration, выбран первый primary attempt, один primary на method-case; status не скрывает concrete candidates;
- evidence candidates не приписывается операция декартовым произведением deltas×findings; неоднозначные кандидаты попадают в invalid_candidates;
- повторные unbound-предупреждения группируются по case и нормализованному обозначению consumer, canonical candidate_id проверяется по правилу раздела 6 протокола; все raw_refs сохраняются, повторные bucket IDs не увеличивают FP;
- модель выключена, права/бюджеты одинаковы, LS1 policy не менялась по gold; обе системы не читали закрытый каталог/эталон;
- source/runtime/docs SHA и identity записаны раздельно; все неудачные attempts, отклонённые случаи и изменения gold доступны в журнале куратора.

Невыполнение — причина NOT_REGISTERED/INVALID_PROTOCOL/INDETERMINATE по протоколу, а не автоматическое заполнение недостающего поля.

## Проверка пользовательского вывода

После сохранения gold и outputs эксперты либо отдельный проверяющий отмечают по заранее заданным правилам: верны ли цитаты; не выдаёт ли summary отсутствие находок за совместимость; не заявляет ли запуск тестов, которого не было; названы ли реально недоступные источники; нет ли данных за пределами прав. Все нарушения сохраняются с точным фрагментом output и source artifact hash. Это проверка представления результата, не изменение gold-меток совместимости.

Общий advisory-дисклеймер сам по себе не даёт credit за обнаружение конкретной unsupported grammar/access boundary. В O нужно фактическое ограничение. Напротив, честное PARTIAL на положительном S не исключает оставшиеся FN.

## Шаблон заключения эксперта

«Я, [реальный expert_id], оценил [case_id] по входам [hashes] до просмотра результатов обеих систем. Профиль [значение, причина]. Полный доступ [да/нет, scope]. Положительные ключи [список], отрицательные [список], неразрешённые [список]. Для каждого основания и допустимые witnesses приложены. Известные конфликты интересов [описание]. Дата/подтверждение [заполняет человек]».

Квадратные скобки не заполнять именами вымышленных респондентов. Без двух реальных expert attestations метрики можно получить только как авторскую диагностику, не как независимую оценку.
