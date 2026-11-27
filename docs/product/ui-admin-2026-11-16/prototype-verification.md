# A6.1 — проверка выбранного прототипа

16.11.2026. Владелец выбрал **вариант2**, не комбинацию2+3. Реализован отдельный [локальный прототип](../../../prototypes/impactmap-ui/README.md). Визуальная QA: [design-qa.md](../../../prototypes/impactmap-ui/design-qa.md), final result passed. Это завершение технической части A6.1; вся A6 остаётся IN_PROGRESS.

## Пять авторских сценариев

| Сценарий | Browser verification1440/390 |
|---|---|
| Из списка открыть изменение | PASS: PR5, выбранная строка и три независимых состояния; поиск1/0/3 строк после match/no-match/clear |
| Потребитель → основание | PASS: Reporting, repository/path/commit/line; Enter переводит focus на evidence-heading; окно кода/Escape; локальная прокрутка длинного кода на390 |
| Новый отказ против старого результата | PASS: PR4 current generation3 FAILED, старый generation2 STALE; delivered относится к поколению2 |
| Ошибка → операции → подключение/binding | PASS: readback/recovery без кнопки слепого POST, Kaiten metadata и явная PR5→карточка; Яндекс «не подключён», worker «не наблюдалось» |
| Пример после исправления | PASS: переход на подготовленное поколение3, новый pin и признак обхода страниц; нет обещания пройденного теста или полного архива |

Дополнительно проверены queued без результата, closed, incompatible (кода нет), unknown-code (код FUTURE_STATUS_V7 виден без success), UNKNOWN/SENDING публикации, prototype role restriction, deep-route/reload и unknown route fallback. Реальные login/access isolation/history/source integrity не проверялись этим frontend-прототипом.

## Найденное и исправленное

1. Уточнены desktop-пропорции/типографика по выбранному reference.
2. Длинный source path на390px расширял страницу до596px. После fix scrollWidth390 при innerWidth390.
3. Перенесённые inline-ссылки на narrow могли активировать соседнюю область. Сделаны отдельные targets; фактические клики повторены.
4. Независимый reviewer нашёл inherited-key route (`toString`/`constructor`/`__proto__`). Воспроизведено в браузере; проверка own property устранила fake incompatible/undefined screen. `toString`, `constructor` и `__proto__` direct routes повторно проверены.

Скриншоты и сравнения — `prototypes/impactmap-ui/qa/`. Основной desktop: [1440](../../../prototypes/impactmap-ui/qa/09-desktop-1440.jpg). Неполный доступ: [390](../../../prototypes/impactmap-ui/qa/07-mobile-partial.jpg). [Общее сравнение](../../../prototypes/impactmap-ui/qa/04-comparison-final.jpg), [evidence comparison](../../../prototypes/impactmap-ui/qa/11-comparison-evidence.jpg). Первоначальные/до-fix снимки оставлены как история QA, не доказательство финального состояния.

## Реализационные решения

Утверждённый план — HTML/CSS/JS без новых runtime dependencies. Node/npm отсутствуют на shell PATH и обычных путях, поэтому не вводился Vite/React starter; сохранена согласованная Python loopback поставка прототипа. Это не заявляется как выполненный Product Design bootstrap/npm build. Все UI/browser/reference QA выполнены непосредственно. Установка на ВМ и публикация сайта не проводились.

Реальные Bitbucket/Jira/Kaiten, ключи и worker не использовались. Сервер статики ограничен loopback, `connect-src 'none'`. Роли имитируются; любой fixture-файл публичен внутри этого локального прототипа. Не добавлять туда реальные данные. Полная независимая оценка06, Яндекс09 и LIVE gate10 не меняют статус из-за нового UI.

Следующий шаг: пользовательский просмотр прототипа и A6.2 — настоящие серверные сессии/роли и безопасные UI projections над service API. Общие привилегии старого status token не передавать в браузер.

Обновление16.11 после просмотра владельцем: шрифт уменьшен (body14/h128), общий вариант2 сохранён. Серверная A6.2 [реализована и проверена отдельно](../../operations/a6-2-2026-11-16/README.md); сам прототип остаётся на author fixtures. Следом A6.3 подключает рабочий result UI к защищённым API.
