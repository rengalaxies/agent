# Ревью tooling 06

Один свежий code-review agent `/root/review_batch06_evaluation`, без чтения реальных скрытых разметок. Найденные P1/P2 приняты и исправлены в одном проходе с regression RED→GREEN:

- Разные output-каталоги позволяли получить повторный primary1. Теперь registered permit задаёт единый SQLite ledger, атомарное назначение каждой пары и порядок; запись не сбрасывается сменой output. Development-campaign хранит свой фиксированный полный порядок и по одному первому output.
- Проверка утечек видела только отобранные candidate witnesses. Теперь проверяются все raw structured evidence/visibility, в том числе неиспользованные refs и excluded path того же repo; leak блокирует boundary credit. Свободный текст требует реального human output-audit, автоматически «проверенным» не объявлен.
- Ошибка normalizer/presentation могла стереть raw и последующие читаемые адресные candidates. Payload сохраняется сразу, malformed entries изолированы, normalized сохраняется до presentation; при worker failure остаются bytes и читаемые диагностические кандидаты. Envelope хеширует stdout/stderr/exit/timestamps/payload; FAILED и SUPERSEDED не дают TP.
- Неполный freeze проходил структурную готовность без environment/seed/primary/retry/argv/нормальной даты. Эти поля теперь обязательны; clean code/runtime/core/dependency/input-hash checks остаются. Структура не аутентифицирует людей и не доказывает их независимость.
- Tree/packet/raw hashes первоначально противоречили annotation-guide. Исправлены на полный tracked manifest у куратора, отдельный source/task/policy/hints TAR и неизменяемый attempt envelope. Worker не читает excluded/denied bytes ради полной curator hash; эта граница раскрыта явно.

Minor: canonical UNBOUND IDs проверяются; добавлены macro-recall/positive-case диагностики. O-кейсам не назначаются primary TP/FP/FN и дефекты полноты S-gold за видимые предупреждения. Последнее исправление O-audit проверено на прежних raw; после всех tooling-коррекций выполнена новая полная контрольная серия на том же development-наборе. TP/FP/FN/P/R/FAR не менялись, n не увеличивался.

Ни один source/core файл продукта не изменён. Авторский toy contract исправлен до окончательного прогона: base20 действительно удовлетворяет authored required20, head10 — нет. Первый ошибочный генератор/предварительные run сохранены ignored и помечены superseded. Curator Git root исправлен на абсолютный путь после диагностированного invalid_source_root. Новые обёртки CLI не нужны: используются фактически исполненные module CLI author_cases/calibrate/runner.

Первичный набор профильных регрессий — 76 OK; финальная evaluation-suite — отдельный журнал. Human attestations в публикуемых oracle false, real expert_id отсутствуют, registration остаётся NOT_REGISTERED. Это ревью кода, а не независимая экспертная разметка и не третье мнение о совместимости.

Дополнительно regression timeout RED→GREEN подтвердил сохранение частичных stdout/stderr и их bytes в base64; финальная контрольная серия выполнена уже с этой версией.
