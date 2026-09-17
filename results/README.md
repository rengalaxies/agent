# Results

Каталог содержит только результаты локальных запусков. Development-показатели используются как регрессионный контроль и не считаются подтверждающими результатами H1.

Команда `make pilot` создаёт две группы артефактов:

1. `pilot-raw-results.json` и `run-manifest.json` - результаты валидаторов без ожидаемых решений и хеш raw-файла.
2. `pilot-results.json`, `pilot-metrics.json` и `pilot-score-manifest.json` - отдельный scoring по oracle и хеш-связи всех входных и выходных артефактов.

`pilot-score-manifest.json` не делает development-пилот подтверждающим экспериментом. Поле `purpose: development_regression` сохраняется и в run manifest, и в отчёте метрик.
