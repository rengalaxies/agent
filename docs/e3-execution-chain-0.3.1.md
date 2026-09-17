# Цепочка выполнения E3 для протокола 0.3.1

## Статус

Цепочка реализована и проверена на 20 development-сценариях. Основной E3 на 40 evaluation-сценариях не выполнялся. Документ фиксирует технический порядок будущего запуска, но не переводит протокол в окончательно замороженное состояние.

## Этап A: validator run без oracle

Отдельный процесс запускается командой `run-catalog`. Он получает каталог сценариев и политику V1-ind, но интерфейс команды не принимает путь к oracle.

Процесс создаёт:

- raw results для каждой пары "сценарий - режим";
- run manifest со статусом `validators_completed_unscored`;
- SHA-256 raw results, каталога сценариев, baseline, реализации, схем и определения метрик.

Raw results не содержат `expected_decision` и `matches_expected`. Run manifest фиксирует `oracle_sha256: null`, `expected_labels_exposed_to_validators: false` и `oracle_loaded_by_validator_process: false`.

## Этап B: отдельный scoring

Отдельный процесс запускается командой `score-results`. До загрузки oracle он обязан:

1. Сверить SHA-256 raw results с run manifest.
2. Проверить статус и тип run manifest.
3. Подтвердить точное однократное покрытие всех пар "сценарий - режим".
4. Проверить `run_id` и идентичность proposal для каждой записи.
5. Отклонить raw results, если в них уже присутствуют поля scoring.

После этих проверок процесс загружает oracle, создаёт новый scored-файл и отчёт метрик. Raw results не перезаписываются.

## Цепочка доказательств

Score manifest имеет статус `scored_from_immutable_raw_results` и содержит SHA-256:

- raw results;
- run manifest;
- oracle;
- scored results;
- отчёта метрик.

Подмена raw results после validator run приводит к отказу scoring из-за несовпадения хеша. Development-пилот дополнительно маркируется `purpose: development_regression`, поэтому его метрики нельзя интерпретировать как подтверждающий результат H1.

## Порядок будущего E3

Будущий E3 должен использовать ту же цепочку с `purpose: confirmatory_e3` на заранее зафиксированном commit. До повторной заморозки и явного решения автора запуск запрещён. После запуска исходные raw results и оба манифеста сохраняются без перезаписи.
