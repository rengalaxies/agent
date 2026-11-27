# Карта API Kaiten и Яндекс Трекера

Проверено по официальной документации 14.11.2026. Это **DOCS_VERIFIED**, не успешная авторизация в tenant. Краткие примеры — authored fixtures; реальные тела ответов не получены.

| Операция | Kaiten | Яндекс Трекер |
|---|---|---|
| Версия/base | https://<company>.kaiten.ru/api/v1; latest — alias | https://api.tracker.yandex.net/v3 |
| Авторизация | Authorization: Bearer TOKEN | Authorization: OAuth TOKEN либо Bearer IAM_TOKEN; X-Org-ID для Яндекс360 / X-Cloud-Org-ID для Identity Hub |
| Читать цель | GET /cards/{card_id} | GET /issues/{issue_id_or_key}; fields projection |
| Scope/контекст | id, board_id, title, description, archived; state/condition отдельно проверить | id, key, queue.id/key, summary, description, status/resolution; локальные правила закрытия отдельно |
| Список комментариев | GET /cards/{id}/comments?limit=100&offset=0 | GET /issues/{id}/comments?perPage=50, далее Link rel=next |
| Читать один | В выбранном minimum API — полный list и поиск ID, отдельный GET не предполагается | Официальный справочник содержит «Получить комментарий»; probe использует полный list, отдельный маршрут не заявлен проверенным |
| Создать | POST /cards/{id}/comments, JSON text | POST /issues/{id}/comments, JSON text |
| Обновить | PATCH /cards/{id}/comments/{comment_id}, JSON text | PATCH /issues/{id}/comments/{comment_id_or_longId}, JSON text |
| Комментарий/автор | id, card_id, author_id, text, deleted | id/longId, createdBy.id, text, version |
| Remote revision | card.version/updated отдельно от semantic hash | issue.version и comment.version отдельно от semantic hash |
| Лимит тела | text≤4096, включая marker | Для probe короткий текст; максимальный размер не подтверждён, не выдумывается |

Kaiten v1/base, Bearer и общий предел50 запросов/сек описаны в [API overview](https://developers.kaiten.ru/). При429 учитывать reset/remaining; это потолок поставщика, не обещание пропускной способности нашей очереди. Scope/поля карточки сверены с [Retrieve card](https://developers.kaiten.ru/cards/retrieve-card).

**Полнота списка:** с01.10.2026 Kaiten выдаёт максимум100 комментариев, сортировка по id, offset увеличивается на применённый limit из X-Pagination-Limit; заканчивать на короткой странице. Это актуальное ограничение, старый «вернулся весь массив» непригоден. [Retrieve card comments](https://developers.kaiten.ru/card-comments/retrieve-card-comments).

Kaiten поддерживает текстовое [создание](https://developers.kaiten.ru/card-comments/add-comment) и [PATCH обновление](https://developers.kaiten.ru/card-comments/update-comment) с лимитом4096. Deprecated files[] к нашему text-only пути не относится; вложения пробой не создаются.

В Яндекс Трекере чтение принимает key/ID, но результат хранится по immutable id, alias отдельно. Header организации выбирается по типу организации. [Get issue](https://yandex.ru/support/tracker/ru/api/issues/get-issue). Чтение комментариев по умолчанию ограничено50, курсор — id последнего комментария, переходы — Link. Нельзя переносить числовые ID через float; для адресации сохраняем longId, где он есть. [Get comments](https://yandex.ru/support/tracker/ru/api/issues/get-comments).

Текстовые POST/PATCH и типы comment ID описаны в [Add comment](https://yandex.ru/support/tracker/ru/api/issues/add-comment) и [Edit comment](https://yandex.ru/support/tracker/ru/api/issues/edit-comment). Наличие version в ответе не подтверждает CAS на PATCH; такие параметры probe не использует.

Документированы конфликты409/412, валидация422, блокировка423 и precondition428, а также429. Для обычных методов гарантированный предел — до10 запросов/сек, для поиска/массовых операций — до5. Общий лимитер подключения нужен в09. [Response codes](https://yandex.ru/support/tracker/ru/api/error-codes).

## Примеры запросов и ответов (синтетические)

Без реальных доменов, идентификаторов людей и токенов. Authorization берётся из env, в артефакты не попадает.

```http
GET /api/v1/cards/12
GET /api/v1/cards/12/comments?limit=100&offset=0
POST /api/v1/cards/12/comments
Content-Type: application/json

{"text":"ImpactMap API probe: created. Dedicated test target.\n\nagent-service marker=0123456789abcdef digest=<64 hex> generation=1"}

PATCH /api/v1/cards/12/comments/5
{"text":"<updated text + same marker + new digest + generation=2>"}
```

Синтетический Kaiten response subset: `{"id":5,"card_id":12,"author_id":7,"text":"...","deleted":false}`.

```http
GET /v3/issues/<immutable-id>
X-Cloud-Org-ID: <org-id>
GET /v3/issues/<immutable-id>/comments?perPage=50
POST /v3/issues/<immutable-id>/comments
Content-Type: application/json

{"text":"<created text + marker/digest/generation=1>"}

PATCH /v3/issues/<immutable-id>/comments/<opaque-longId>
{"text":"<updated text + same marker + new digest + generation=2>"}
```

Синтетический Яндекс response subset: `{"id":5,"longId":"opaque-5","createdBy":{"id":"7"},"text":"...","version":1}`. Это примеры mapping, не скопированные реальные ответы. В local HTTP stand применяется именно эта форма запросов и ответов.

Для пробы Kaiten выбран закреплённый /api/v1 (документированные latest routes относятся к текущей v1). Соответствие на реальном tenant ещё проверяется. Probe требует applied-limit header и исчерпывает Yandex numeric cursor; link к текущему key допускается только после GET immutable task, отправка остаётся на immutable path. Это намеренные проверки нашей реализации.
