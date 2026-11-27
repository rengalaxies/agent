"""Escaped operator screens consume only ui_operator projections."""
from urllib.parse import urlencode
from .ui_views import e,pairs,observed,badge,JOB,PUBLICATION,FRESH,reason

TRACKERS={'jira':'Jira','kaiten':'Kaiten','yandex':'Яндекс Трекер'}
STATES={'NOT_CHECKED':'Доступ не проверен','NOT_CONNECTED':'Не подключён','ATTENTION':'Есть сохранённая ошибка маршрута',
        'RECORDED_GAPS':'В сохранённом анализе есть пробелы','CONFIGURED_UNVERIFIED':'Настроена, актуальность не проверена',
        'MATCHED_SNAPSHOT':'Совпадает с сохранённым снимком','RECORDED_UNVERIFIED':'Сохранённая связь, доступ не проверен',
        'CONFLICT':'Конфликт привязки','NOT_OBSERVED':'Не наблюдалось'}
NOTICES={'connection_unauthorized':'Ошибка доступа к маршруту','provider_rejected':'Провайдер отклонил запрос',
         'reconcile_failed':'Ошибка инвентаризации','rate_limited':'Ограничение частоты запросов',
         'duplicate_service_comments':'Найдены дубли собственных комментариев','postsend_check_failed':'Проверка после отправки не пройдена',
         'analysis_not_connected':'Ядро анализа не подключено к этому маршруту'}


def link(rid,label='Открыть результат', *, path_prefix='/ui'):
    return f'<a class="text-link" href="{e(path_prefix+"/result?"+urlencode({"resource_id":rid}))}">{e(label)}</a>'


def state(value):return badge('Состояние',value,STATES,'error' if value in ('ATTENTION','CONFLICT') else 'neutral')


def notices_view(notices):
    out=['<section><h2>Сохранённые уведомления</h2>']
    if not notices:out.append('<p>В показанной области уведомлений нет. Это не подтверждает исправность источников.</p>')
    for n in notices:
        out.append(f'<article class="notice warn"><h3>{e(NOTICES[n["kind"]])} <code>{e(n["kind"])}</code></h3>'+pairs([
            ('Область',n['subject']),('Повторений',n['count']),('Последняя запись UTC',observed(n['last_at']))])+ '<p>Это сохранённое наблюдение; текущее состояние доступа автоматически не проверялось. Текст ответа провайдера скрыт.</p></article>')
    out.append('</section>');return ''.join(out)


def operator_view(data,section, *, path_prefix='/ui'):
    title='Операции' if section=='operations' else 'Подключения'
    out=[f'<h1 tabindex="-1">{title}</h1>']
    if not data['available']:
        return ''.join(out)+'<section class="notice warn"><h2>Метаданные установки недоступны</h2><p>Для этой сборки не передана безопасная конфигурационная проекция. Подключения и worker не считаются исправными.</p></section>'
    out.append('<p class="section-intro">Просмотр сохранённых данных. Внешние API, инвентаризация, анализ и публикация при обновлении страницы не запускаются.</p>')
    if section=='operations':
        out.append('<section class="notice neutral"><h2>Worker: не наблюдалось</h2><p>Открытая панель не подтверждает работу worker, доступ к репозиториям или доставку комментариев. Heartbeat в этой версии не записывается.</p></section>')
        out.append(pairs([('Режим публикации',data['publication_mode']),('Задания показанной выборки',', '.join(f'{k}: {v}' for k,v in sorted(data['counts']['jobs'].items())) or 'нет'),
                          ('Outbox показанной выборки',', '.join(f'{k}: {v}' for k,v in sorted(data['counts']['outbox'].items())) or 'нет')]))
        out.append('<p class="list-limit">Последние100 допущенных ресурсов, не вся очередь. Проверяется максимум1000 кандидатов; старые/неподтверждённые области не включены. До10 последних намерений на ресурс с отдельными receipts поколений.</p>')
        if data['has_more']:out.append('<p class="notice warn">Есть дополнительные допущенные ресурсы за границей выборки.</p>')
        if not data['items']:out.append('<p class="empty-state">Нет доступных заданий в показанной выборке. Это не означает отсутствия влияния.</p>')
        for row in data['items']:
            r=row['resource'];job=row['current_job'] or {};analysis=row['analysis']
            out.append(f'<article class="operation-item"><h2>{e(r["resource_id"])}</h2><p>Текущее поколение {e(r["generation"])} · {e(r["provider"])} · UTC {e(observed(r["updated_at"]))}</p><div class="status-strip">'+
                       badge('Задание',job.get('state'),JOB,'error' if job.get('state')=='FAILED' else 'neutral')+
                       badge('Основание',(analysis or {}).get('freshness'),FRESH,'warn')+'</div>')
            if job.get('reason'):out.append(f'<p>Причина: {reason(job["reason"])}</p>')
            if analysis:out.append(f'<p>Поколение анализа {e(analysis["generation"])}; формат: {"совместим" if analysis["compatible"] else "несовместим"}. Доставка проверяется отдельно.</p>')
            if r['closed']:out.append('<p class="notice neutral">Ресурс закрыт; показано сохранённое состояние.</p>')
            if not row['outbox']:out.append('<p>Намерение публикации в доступной выборке не найдено.</p>')
            for intent in row['outbox']:
                out.append('<div class="outbox-item">'+badge('Публикация',intent['state'],PUBLICATION,'success' if intent['state']=='DELIVERED' else 'warn')+
                           f'<p>Поколение {e(intent["generation"])} · Тип {e(intent["kind"])} · Попыток {e(intent["attempts"])} · UTC {e(observed(intent["updated_at"]))}</p>')
                if intent['reason']:out.append(f'<p>Причина: {reason(intent["reason"])}</p>')
                if intent['state'] in ('UNKNOWN','SENDING'):
                    out.append('<p class="notice warn"><strong>Исход публикации неизвестен.</strong> Сначала readback: проверьте собственный marker и существующий комментарий через операторские средства. Не повторяйте POST вслепую; сохраните idempotency и протокол восстановления.</p>')
                out.append('</div>')
            out.append(link(r['resource_id'],path_prefix=path_prefix)+'</article>')
    else:
        out.append('<section><h2>Маршруты получения изменений</h2>')
        for p in data['intake']:
            out.append(f'<article class="connection-row"><h3>{e(p["id"])}</h3>{state(p["state"])}<p>Последняя завершённая инвентаризация (UTC): {e(observed(p["last_inventory_at"]))}</p><p class="muted">Время инвентаризации не подтверждает текущие права или возможность записи в трекер.</p></article>')
        if not data['intake']:out.append('<p>Маршруты не заданы.</p>')
        out.append('</section><section><h2>Репозитории и runtime-источники</h2>')
        for source in data['sources']:
            out.append(f'<article class="connection-row"><h3>{e(source["id"])}</h3>{state(source["state"])}<p>Источник: {e(", ".join(source["providers"]) or "метаданные провайдера отсутствуют")}</p>')
            for issue in source['issues']:
                out.append(f'<p>Сохранённый пробел: <code>{e(issue["code"])}</code> · поколение {e(issue["generation"])} · {e(issue["freshness"])}. '+link(issue['resource_id'],path_prefix=path_prefix)+'</p>')
            out.append('</article>')
        out.append('</section><section><h2>Трекеры</h2>')
        for tracker in data['trackers']:
            out.append(f'<article class="connection-row"><h3>{TRACKERS[tracker["id"]]}</h3>{state(tracker["state"])}'+pairs([
                ('Настроенная область',', '.join(tracker['scope']) or 'не задана'),('Маршрут',tracker['route'])])+ '<p class="muted">Настройка не является успешной API-пробой. Ошибка маршрута может относиться к источнику или назначению; точная причина видна только в соответствующем сохранённом наблюдении.</p></article>')
        out.append('</section><section><h2>Привязки PR → задача</h2><p>Максимум100 привязок разрешённой области. Сохранённое совпадение не подтверждает текущий доступ к карточке.</p>')
        if not data['bindings']:out.append('<p>Явные привязки в доступных сведениях не найдены. Это не означает отсутствия влияния или связи в другом источнике.</p>')
        for b in data['bindings']:
            target=b.get('target') or ', '.join(b.get('targets',[]))
            out.append(f'<article class="binding"><h3>{e(b["resource_id"])}</h3>{state(b["state"])}'+pairs([('Трекер',TRACKERS[b['tracker']]),('Назначение',target)])+link(b['resource_id'],path_prefix=path_prefix)+'</article>')
        out.append('</section>')
    out.append(notices_view(data['notices']))
    return ''.join(out)
