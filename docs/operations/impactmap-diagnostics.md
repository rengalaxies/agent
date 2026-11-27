# Операторская диагностика и полный результат ImpactMap

Кандидат пачки10 добавляет read-only JSON API к существующему HTTP сервису. Это интерфейс оператора одной установки, не публичная ссылка из трекера и не готовая многопользовательская админка. UI/роли/управляющие действия обсуждаются в [A6](../product/roadmap-2026-11-14/UI-ADMIN-BATCH.md).

## Доступ

У процесса `agent_service serve` должен быть `AGENT_SERVICE_STATUS_TOKEN`. Без него `/resources` и `/result` закрыты, как `/status` и `/graph`. Используется точный заголовок `Authorization: Bearer …`. Токен не передавать в URL, скриншотах, Git или общем комментарии; endpoint содержит разрешённые исходники/evidence и доступен оператору всей этой установки. Использовать loopback/SSH tunnel или установленный защищённый reverse proxy. Ролевой доступ к отдельным проектам этим токеном не реализуется.

Пример чтения без токена в аргументах процесса (переменная уже подготовлена оператором):

```sh
python - <<'PY'
import json,os,urllib.request,urllib.parse
base='http://127.0.0.1:8090'
headers={'Authorization':'Bearer '+os.environ['AGENT_SERVICE_STATUS_TOKEN']}
def get(path):
    with urllib.request.urlopen(urllib.request.Request(base+path,headers=headers),timeout=15) as r:
        return json.load(r)
resources=get('/resources?limit=50')
for item in resources['items']:
    print(item['resource_id'],item['generation'],item['closed'])
# Выбрать нужный ID из списка; далее request не меняет очередь/ресурс.
if resources['items']:
    rid=resources['items'][0]['resource_id']
    print(json.dumps(get('/result?'+urllib.parse.urlencode({'resource_id':rid})),ensure_ascii=False,indent=2))
PY
```

Порт в примере — стандартный локальный8090, не установленный порт конкретной ВМ. Сначала сверить фактический service unit/маршрутизацию. У установленного старого a02ffa7 этих новых endpoints ещё нет.

## Контракт чтения

`GET /resources?limit=1..100` возвращает `schema=impactmap-diagnostics-1`, ограниченный список метаданных, `limit` и `has_more`. По умолчанию50, сортировка updated_at DESC/resource_id. Это последние100 максимум, без курсорного обхода всех ресурсов. Snapshot descriptions, конфигурация, HTTP receipts и secret env в список не входят.

`GET /result?resource_id=...` читает один ID (1–512 символов) параметризованным SQL в одном read transaction. Файловая система по этому ID не читается. Ответ:

- `resource` — текущее поколение/version, closed, provider/kind, published generation и locator комментария;
- `current_job` — состояние текущего поколения, reason/attempts/updated_at;
- `analysis` — последнее **сохранённое** поколение с raw result, его version/job state/reason и `freshness`;
- `publication` — состояние result intent именно выбранного analysis generation, отдельно от анализа;
- `document` — полный сохранённый документ этого результата, а не только краткий комментарий трекера.

`CURRENT` означает совпадение сохранённого analysis generation с текущим открытым ресурсом, **не** завершённую публикацию или доказанную совместимость API. `STALE` означает более старое поколение, включая rebuild той же version после обновления анализатора. `CLOSED` явно обозначает закрытый ресурс. Новый FAILED result выбирается вместо старого успешного. Если текущий job отказал без raw, возвращается предыдущий raw с `STALE` и отдельной текущей ошибкой; если raw ещё никогда не было, `analysis=null`. Superseded result может быть виден для диагностики, он не становится текущим из-за наличия raw.

Невалидный или отвергнутый сервисом результат имеет `compatible=false`, `raw=null`, `document=null`: произвольный incompatible payload не выдаётся как достоверный анализ. Токены/headers/HTTP receipts не входят в проекции. Это не универсальная фильтрация секретов в разрешённом исходном коде: сам полный валидный анализ доступен только уполномоченному оператору.

Нет токена/неверный токен —401; некорректный параметр —400 после авторизации; неизвестный resource —404; POST отсутствует/405. Новые endpoints во всех этих исходах `Cache-Control: no-store`, nosniff/no-referrer. Чтение не запускает reconcile, анализ, повторы, recovery или публикацию.

## Что проверять при отказе

1. `/healthz` — только жив ли HTTP процесс; не проверка Bitbucket/трекера/анализа.
2. `/status` — счётчики и notices. Найти ресурс через `/resources`, затем прочитать `/result`.
3. Сначала current_job generation/state/reason, затем analysis freshness/compatible/status, затем publication state. Успешный старый результат не снимает ошибку нового поколения.
4. `connection_unauthorized`/401/403 — проверить разрешённую учётную запись/проект/доску; `commit_unavailable` — наличие точного pin в mirror. Не переключать анализ на другой commit ради успешного результата.
5. UNKNOWN/SENDING после потери HTTP ответа — применять существующий marker/list/readback/recovery протокол; не выполнять слепой POST и не сбрасывать durable state. Новые API только показывают состояние.
6. Сверить source commit, loaded runtime и config/policy/lock hashes перед обновлением. Проверить явные старые policy2MB: новый default8MB не заменяет значения оператора.

Для PR полный раздел «Версии» использует base/head совместимого AnalysisRequest, включая настоящий merge-base. Исходный Bitbucket destination tip отдельно именуется `destination tip`, если анализа base ещё нет. Пустое `base ,` устранено; при отсутствии pins явно «неизвестен». Краткий русский комментарий остаётся кратким, полный audit доступен оператору.
