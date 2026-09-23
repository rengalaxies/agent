# E4-N: как провести проверку в трех средах

Статус: пакет готов к развертыванию; проверка на трех машинах еще не выполнена.
Локальный сетевой smoke test: `PYTHONPATH=src python tools/smoke_e4_network.py`.
Его результат в `results/e4-network-loopback.json` относится только к одному
компьютеру. Не переносите этот вывод на H3 или промышленную надежность.

## Что требуется

| От кого | Требуется | Для чего |
|---|---|---|
| Владелец сред | Доступ по SSH к трем Linux-машинам A, B, C с Python >= 3.12; доступ A к B и C по SSH | A: fintech и координатор, B: retail, C: mobility |
| Владелец сред | Разрешенные SSH-туннели A -> B и A -> C; ~1 GB свободного диска на каждой машине | Передать запросы без публикации HTTP в интернет |
| Владелец запуска | Три случайных ключа длиной от 32 символов; fintech, retail, mobility | Проверить HMAC запросов и вердиктов |
| Я после запуска | Четыре JSON-файла результатов и описание конфигурации без ключей и публичных адресов | Рассчитать метрики и оформить отчет |

Синтетический сценарий встроен: `scenarios/development/T-03.yaml` плюс третье
обязательство. Пользовательские данные, Kafka и оплаченные LLM не нужны.

## 1. Установить пакет

На A, B и C разверните одну и ту же ветку
`research/e4-distributed-development-20260923` репозитория
`rengalaxies/agent`; используйте одинаковый коммит. В корне репозитория:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e .
```

Отдельно сохраните SHA коммита в протоколе запуска: `git rev-parse HEAD`.
Для подготовки без трех машин можно выполнить smoke test на A:

```bash
PYTHONPATH=src .venv/bin/python tools/smoke_e4_network.py
```

## 2. Настроить ключи и сервисы

Сгенерируйте три независимых ключа командой
`.venv/bin/python -c 'import secrets; print(secrets.token_urlsafe(48))'`.
Сохраните их в защищенном менеджере секретов. На A должны быть доступны все
три ключа; на B только `E4_RETAIL_KEY`, на C только `E4_MOBILITY_KEY`.
Передавайте секреты в переменных окружения, не записывайте в GitHub,
конфигурацию или файлы результатов. На A запустите:

```bash
PYTHONPATH=src .venv/bin/python tools/e4_network.py serve --domain fintech --host 127.0.0.1 --port 8411 --key-env E4_FINTECH_KEY
```

На B:

```bash
PYTHONPATH=src .venv/bin/python tools/e4_network.py serve --domain retail --host 127.0.0.1 --port 8412 --key-env E4_RETAIL_KEY
```

На C:

```bash
PYTHONPATH=src .venv/bin/python tools/e4_network.py serve --domain mobility --host 127.0.0.1 --port 8413 --key-env E4_MOBILITY_KEY
```

Оставьте три сервиса запущенными. На A откройте два отдельных SSH-туннеля
в разных терминалах (подставьте свои SSH-имена машин):

```bash
ssh -N -L 127.0.0.1:8412:127.0.0.1:8412 user@B
ssh -N -L 127.0.0.1:8413:127.0.0.1:8413 user@C
```

На A скопируйте `infrastructure/e4-network.example.json` в локальный
`e4-network.local.json`; пример уже содержит адреса трех локальных портов.
При изменении портов исправьте только этот локальный файл. Не публикуйте
его с реальными адресами машин.

## 3. Провести четыре запуска на A

Для каждого запуска нужны **новые** `run-id`, файл SQLite и JSON результата.
Из корня репозитория при работающих трех сервисах:

```bash
PYTHONPATH=src .venv/bin/python tools/e4_network.py run --config e4-network.local.json --run-id E4N-01 --journal e4n-01.sqlite --output e4n-01.json --timeout 2
PYTHONPATH=src .venv/bin/python tools/e4_network.py run --config e4-network.local.json --run-id E4N-02 --journal e4n-02.sqlite --output e4n-02.json --timeout 2 --duplicate
PYTHONPATH=src .venv/bin/python tools/e4_network.py run --config e4-network.local.json --run-id E4N-03 --journal e4n-03.sqlite --output e4n-03.json --timeout 0.5 --delay-domain mobility --delay-seconds 2
```

Для четвертого запуска остановите **только** сервис mobility на C и выполните:

```bash
PYTHONPATH=src .venv/bin/python tools/e4_network.py run --config e4-network.local.json --run-id E4N-04 --journal e4n-04.sqlite --output e4n-04.json --timeout 1
```

Ожидается: 01 и 02 - `ACCEPT`; 03 и 04 - `NEEDS_REVIEW` с `mobility`
в `missing_domains`. В JSON записаны `elapsed_ms`, ошибки транспорта,
полученные домены, повторы, `snapshot_id` и итог. Порог 0.5 с тестовый,
не обещание SLA. Если базовый запуск не дал `ACCEPT`, сначала проверьте
туннели, совпадение ключей, версию кода и доступность сервисов.

Пришлите четыре JSON результата и SHA коммита, укажите три разные среды
без логинов, адресов и ключей. Я сверю сценарии, ограничения и подготовлю
итоговый отчет E4-N для GitHub и раздел ВКР. Без этого нельзя заявлять,
что опыт на трех средах состоялся.

## Границы архитектуры

Координатор и локальный SQLite-журнал размещены на A; у доменов на B и C
нет собственного хранилища входящих событий. HTTP используется через SSH,
не открывайте порты 8411-8413 в интернет без TLS и контроля доступа.
Каждый доменный сервис получает общий контракт и **только свои** обязательства;
координатор знает перечень всех трех доменов. Хеш снимка проверяется
координатором; HMAC защищает запросы и ответы при знании общего ключа,
но не дает доказательства независимого происхождения контрактных данных.
Внешний отказ A или ее диска остается точкой отказа.
