# Пять проверяемых случаев ImpactMap

## AUD-0001 Удалён endpoint

Provider fce3d0a08d53aad56e7241edf64e8dea1bb24b52 → adc2ec13a18e8d4932c8fce035bbb2c08ad5910a; consumer ad2ae6070be7864077cef77da0b690bd702128ba.

```python
Provider head, api.py:
from fastapi import FastAPI
app = FastAPI()

Consumer head, client.py:
import requests
def consume():
    return requests.get("https://dev-provider.test/audit/1/records").json()
```

Ожидается влияние: consumer вызывает удалённую операцию. В эталоне требуется существующий endpoint и 60 строк.

ImpactMap указывает OPERATION_REMOVED и вызов consumer. LS1 находит путь в consumer; оба метода дают TP=1, FP=0, FN=0.

Адресное основание доступно; бизнес-владелец не определён. До выпуска нужно согласовать замену операции и проверить вызов. Это статический результат, интеграционные тесты не выполнялись.

[План и входы](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/corpus/plan-before-run.json) · [Вывод ImpactMap](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0001/impactmap_static/payload.json) · [Вывод LS1](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0001/lexical_search_ls1/normalized.json)

## AUD-0002 Уменьшён default без явного параметра

Provider cdcf11ab064f8f14dcaa1e1230e03550bb5a17d3 → f15285ecdf65ee71295f2ef152ec3595b9b34080; consumer 5db8919304567e252a1a66ecd3a7a94ca5dd86ce.

```python
Provider head, api.py:
from fastapi import FastAPI
app = FastAPI()
@app.get("/audit/2/records")
def entries(page_size: int = 15, page: int = 1):
    return list(range(60))[(page-1)*page_size:page*page_size]

Consumer head, client.py:
import requests
def consume():
    return requests.get("https://dev-provider.test/audit/2/records").json()
```

Ожидается влияние: consumer выполняет один запрос без page_size и по условию должен получить 60 строк. Default меняется 60→15.

ImpactMap указывает POSSIBLE_TRUNCATION. LS1 находит потребителя; оба метода дают TP=1, FP=0, FN=0.

Совпадение методов сохраняется. Полезность ImpactMap здесь — классифицированное основание; экономия труда не измерена. Явный размер требует проверки допустимости; пагинация изменяет условие одного вызова и требует согласования.

[План и входы](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/corpus/plan-before-run.json) · [Вывод ImpactMap](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0002/impactmap_static/payload.json) · [Вывод LS1](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0002/lexical_search_ls1/normalized.json)

## AUD-0004 Явный параметр перекрывает default

Provider 94b6452801dc4ca32b11a215d6961d95d45c6383 → 3a39d2230c6e73c79a964dcf8b31a582f312038d; consumer a704bcab0f850e76932d0b44469ae018bf5f1238.

```python
Provider head, api.py:
from fastapi import FastAPI
app = FastAPI()
@app.get("/audit/4/records")
def entries(page_size: int = 15, page: int = 1):
    return list(range(60))[(page-1)*page_size:page*page_size]

Consumer head, client.py:
import requests
def consume():
    return requests.get("https://dev-provider.test/audit/4/records", params={"page_size": 60}).json()
```

По эталону дополнительное влияние default не ожидается: consumer явно передаёт page_size=60. Сам provider меняет только default 60→15.

ImpactMap: ABSTAINED/insufficient_evidence; TP/FP/FN=0/0/0. В summary явно объяснено перекрытие default. LS1: USEFUL с одним буквальным кандидатом, по эталону FP=1.

Отсутствие дополнительной тревоги относится к данному изменению и вызову. Другие свойства совместимости и другие consumer не установлены. E7 показала, что отсутствие consumer в карточке непонятно; отсюда IM-FB-01 и IM-FB-02.

[План и входы](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/corpus/plan-before-run.json) · [Вывод ImpactMap](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0004/impactmap_static/payload.json) · [Вывод LS1](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0004/lexical_search_ls1/normalized.json)

## AUD-0007 Совпадает путь, различается host

Provider 682b0d06395e5ffdbd26d0161b26012226ef2295 → 2f305556cc2c5d31ba72d87fe80a6731ab140968; consumer 5d252dbb7a140ac1c37909c180734918e051f76a.

```python
Provider head, api.py:
from fastapi import FastAPI
app = FastAPI()
@app.get("/audit/7/records")
def entries(page_size: int = 15, page: int = 1):
    return list(range(60))[(page-1)*page_size:page*page_size]

Consumer head, client.py:
import requests
def consume():
    return requests.get("https://another-provider.test/audit/7/records").json()
```

В контролируемом эталоне затронутый consumer отсутствует: URL относится к another-provider.test, а provider зарегистрирован как dev-provider.test.

ImpactMap: ABSTAINED/no_consumer_found_within_profile; unmapped_call и runtime_not_observed; TP/FP/FN=0/0/0. LS1: USEFUL с буквальным кандидатом, FP=1.

Равенство путей не устанавливает равенство сервисов. В реальной среде нужна актуальная маршрутизация: другой host может быть алиасом. Отсутствие подтверждённой связи не разрешает выпуск. Из ответа продакта E7 я вывел IM-FB-03.

[План и входы](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/corpus/plan-before-run.json) · [Вывод ImpactMap](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0007/impactmap_static/payload.json) · [Вывод LS1](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0007/lexical_search_ls1/normalized.json)

## AUD-0010 Недоступен provider

Provider 6a3b5648cb11c1006d43184ac734ae252b1627fb → 6feb9e2870d8c22c7dcb088af79d0ad9092ee63e; consumer 8a8823adedb57f1473759921f8e49826c122b961.

```python
Provider head, api.py:
from fastapi import FastAPI
app = FastAPI()
@app.get("/audit/10/records")
def entries(page_size: int = 15, page: int = 1):
    return list(range(60))[(page-1)*page_size:page*page_size]

Consumer head, client.py:
import requests
def consume():
    return requests.get("https://dev-provider.test/audit/10/records").json()
```

Ожидается выход за профиль доступа: policy указывает на недоступный root provider. Показанный исходник — сохранённый вход корпуса; анализатор не получил к нему доступ в попытке.

ImpactMap: FAILED/commit_unavailable; строгие TP/FP/FN не определены. LS1: PARTIAL с кандидатом по доступному consumer; строгие метрики также не определены.

Я сохраняю ошибку, а не записываю её как отсутствие влияния. Следующий шаг — восстановить разрешённый доступ к base/head и повторить анализ. Для этой попытки вывод о совместимости невозможен.

[План и входы](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/corpus/plan-before-run.json) · [Вывод ImpactMap](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0010/impactmap_static/payload.json) · [Вывод LS1](https://github.com/rengalaxies/agent/blob/main/docs/product/pilot/e6-2026-11-27/attempts/attempts/AUD-0010/lexical_search_ls1/normalized.json)
