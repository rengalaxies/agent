// Author-created UX examples only. No connector, token, live result or customer data.
const base = {
  source: 'Bitbucket → Kaiten', generation: 2, updated: '16.11.2026, 14:20 МСК',
  job: 'DONE', freshness: 'CURRENT', publication: 'DELIVERED', consumer: 'Reporting',
  repository: 'reporting', path: 'client.py', commit: '2cba012ba204', line: 5,
  code: 'response = requests.get("http://orders:8000/orders", timeout=5)',
  headline: 'Возможна потеря части заказов',
  explanation: 'Лимит страницы уменьшен до 100. В коде потребителя найден одиночный запрос.',
  check: 'Проверьте, нужен ли Reporting полный набор заказов и обрабатывает ли он следующую страницу. Сверьте поведение потребителя с его требованиями.',
  caveat: 'Статический риск. Тесты потребителя не запускались.',
  compatible: true,
};
export const cases = Object.freeze({
  pr5: {...base, id:'pr5', title:'PR #5 · Ограничение страницы Orders'},
  'pr5-fixed': {...base, id:'pr5-fixed', generation:3, title:'PR #5 · Ограничение страницы Orders', commit:'8d1a760b912f', line:8,
    code:'for order in iter_orders(page_size=100):\n    yield order',
    headline:'Прежний статический признак изменился', explanation:'В авторском примере исправления найден обход страниц. Результат относится к новому поколению 3.',
    caveat:'Исправление требует проверки. Корректность потребителя статическим анализом не доказана.',
    check:'Повторите проверку полного набора заказов. Сопоставьте пропуски и дубли с требованием потребителя.'},
  pr4: {...base, id:'pr4', title:'PR #4 · Исправление пагинации Reporting', job:'FAILED', freshness:'STALE', publication:'DELIVERED', generation:3, savedGeneration:2,
    error:'Не удалось прочитать закреплённый commit Reporting.', reason:'commit_unavailable',
    headline:'Показан предыдущий результат', explanation:'Текущее задание поколения 3 завершилось ошибкой. Ниже сохранён результат поколения 2; он не описывает текущее изменение.'},
  pr3: {...base, id:'pr3', title:'PR #3 · Добавление потребителя Export', job:'PARTIAL', publication:'UNKNOWN', consumer:'Export',
    repository:'export', path:'integrations/orders/clients/enterprise/reports/monthly/export_orders_client.py', commit:'5ac19b87d320', line:27,
    code:null, headline:'Влияние оценено по неполным данным',
    explanation:'Исходники Export недоступны. Полнота зависимостей не подтверждена.',
    caveat:'Нет доступа к источнику. Это не означает, что влияния нет.',
    check:'Восстановите разрешённый доступ и выполните новый анализ. Исход публикации сначала проверьте через readback/recovery.'},
  empty: {...base, id:'empty', title:'PR #8 · Новое изменение', job:'QUEUED', freshness:null, publication:null, noResult:true},
  closed: {...base, id:'closed', title:'PR #9 · Закрытое изменение', freshness:'CLOSED', closed:true},
  incompatible: {...base, id:'incompatible', title:'PR #10 · Несовместимый результат', job:'FAILED', compatible:false, freshness:null, publication:null},
  unknown: {...base, id:'unknown', title:'PR #11 · Новый код состояния', job:'FUTURE_STATUS_V7', freshness:'UNKNOWN', publication:'SENDING',
    headline:'Состояние анализа не распознано', explanation:'Эта версия интерфейса не знает код FUTURE_STATUS_V7. Результат нельзя интерпретировать как успешный.'},
});
export const connections = Object.freeze([
  {id:'bitbucket', name:'Bitbucket', type:'Источник кода', scope:'orders, reporting, export', state:'Частичный доступ', tone:'warn', observed:'16.11.2026, 14:18 МСК', detail:'orders и reporting доступны. Доступ к export не подтверждён. Фактических API-проб из прототипа нет.'},
  {id:'kaiten', name:'Kaiten', type:'Трекер задач', scope:'Выделенная доска пилота', state:'Исход публикации неизвестен', tone:'warn', observed:'16.11.2026, 14:20 МСК', detail:'Ответ на публикацию для PR #3 потерян. Сначала проверить marker и список комментариев, затем применить recovery; не выполнять слепой POST.'},
  {id:'jira', name:'Jira', type:'Трекер задач', scope:'Пилотный проект', state:'В этом примере не проверен', tone:'muted', observed:null, detail:'Отсутствие наблюдения не является проверкой работоспособности Jira.'},
  {id:'yandex', name:'Яндекс Трекер', type:'Трекер задач', scope:'Не задана', state:'Не подключён', tone:'muted', observed:null, detail:'Доступ и интеграция пока не настроены. Это не положительный результат приёмки.'},
]);
export const binding = Object.freeze({pr:'Bitbucket PR #5', target:'Kaiten · тестовая карточка', type:'Явная привязка', state:'Настроена в авторском примере'});
