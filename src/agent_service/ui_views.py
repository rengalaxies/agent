"""Escaped, read-only workbench fragments from authorized UI projections only.

No file/network access and no arbitrary links. Evidence coordinates are text;
source quotes are deliberately unavailable until a pinned reader is implemented.
"""
from datetime import datetime, timezone
from html import escape
from urllib.parse import urlencode

JOB={'QUEUED':'в очереди','RUNNING':'выполняется','ANALYZED':'анализ завершён',
     'DONE':'обработка завершена','FAILED':'ошибка','SUPERSEDED':'заменён новым заданием'}
FRESH={'CURRENT':'актуально для поколения','STALE':'устарело','CLOSED':'ресурс закрыт'}
PUBLICATION={'PENDING':'ожидает доставки','BLOCKED':'доставка заблокирована','SENDING':'отправка не подтверждена',
             'UNKNOWN':'исход неизвестен','DELIVERED':'доставлено','FAILED':'ошибка доставки','SUPERSEDED':'заменено'}
STATUS={'USEFUL':'Найдена область влияния','PARTIAL':'Неполные данные','ABSTAINED':'Недостаточно основания для вывода',
        'FAILED':'Анализ завершился ошибкой','SUPERSEDED':'Результат заменён'}
REASONS={'impact_found_within_profile':'Влияние найдено в пределах поддерживаемого профиля',
         'preliminary_impact_found':'Предварительная область влияния по задаче, без доказательства поломки',
         'coverage_gaps':'Обследование выполнено не полностью','commit_unavailable':'Закреплённый commit недоступен',
         'source_unavailable':'Источник недоступен','no_consumer_found_within_profile':'Потребитель в обследованном профиле не найден',
         'no_supported_delta':'Поддерживаемое изменение не выделено','insufficient_evidence':'Недостаточно основания'}


def e(value):return escape(str(value if value is not None else 'не указано'),quote=True)


def observed(value):
    try:return datetime.fromtimestamp(value,timezone.utc).isoformat(timespec='seconds')
    except (ValueError,TypeError,OverflowError,OSError):return 'не наблюдалось'


def badge(label,code,labels,tone='neutral'):
    if code is None:return f'<span class="badge neutral">{e(label)}: не выполнялась / нет данных</span>'
    known=code in labels
    text=labels.get(code,'Неизвестный код; успех не подтверждён')
    return f'<span class="badge {tone if known else "error"}">{e(label)}: {e(text)} <code>{e(code)}</code></span>'


def reason(code):
    return f'{e(REASONS.get(code,"Причина обработки"))} <code>{e(code)}</code>' if code else 'Причина не указана'


def pairs(values):
    return '<dl>'+''.join(f'<dt>{e(k)}</dt><dd>{e(v)}</dd>' for k,v in values)+'</dl>'


def evidence_links(ids,refs,context=''):
    return ' '.join(f'<a href="#evidence-{i}">Основание {i+1}{e(context)}</a>'
                    for i in sorted({refs[ref] for ref in ids if ref in refs}))


def evidence_view(items):
    out=[]
    for i,item in enumerate(items):
        base=[('ID',item['id']),('Источник',item['origin']),('Происхождение',item['provenance']),
              ('Достаточность',item['sufficiency']),('Свежесть основания',item['freshness']['status']),
              ('Проверено',item['freshness']['checked_at'])]
        if item['origin']=='code':
            base.extend([('Репозиторий',item['repository']),('Файл',item['path']),
                         ('Строки',f"{item['start_line']}–{item['end_line']}"),('Снимок',item['snapshot']),
                         ('Commit',item.get('commit')),('Blob',item.get('blob')),('SHA-256',item['content_sha256'])])
            note='<p class="muted">Фрагмент исходника недоступен в этом интерфейсе. Координаты относятся к сохранённому снимку; текущая ветка не читается.</p>'
        elif item['origin']=='runtime':
            base.extend([('Источник runtime',item['source']),('Окно с',item['window_start']),('Окно до',item['window_end'])])
            note='<p class="muted">Наблюдение относится только к указанному временному окну.</p>'
        else:
            note='<p class="muted">Это отдельный тип основания; он не подменяет чтение закреплённого кода.</p>'
        out.append(f'<article class="evidence-card" id="evidence-{i}" tabindex="-1"><h3>Основание {i+1}</h3>{pairs(base)}{note}</article>')
    return ''.join(out) or '<p>Основания в сохранённом результате отсутствуют.</p>'


def result_view(data):
    if data is None:
        return '<section class="empty-state"><h1 tabindex="-1">Выберите изменение</h1><p>Откройте результат в списке слева. Отсутствие строки не означает отсутствия влияния.</p></section>'
    resource=data['resource'];job=data['current_job'] or {};analysis=data['analysis'];pub=data['publication'] or {}
    state=job.get('state');freshness=analysis['freshness'] if analysis else None
    out=[f'<h1 tabindex="-1">Результат изменения</h1><p class="source-line">{e(resource["resource_id"])}</p>',
         f'<p class="muted">{e(resource["provider"])} · {e(resource["kind"])} · Текущее поколение {e(resource["generation"])}</p>',
         '<div class="status-strip" aria-label="Независимые состояния">',
         badge('Анализ',state,JOB,'error' if state=='FAILED' else 'neutral'),
         badge('Основание',freshness,FRESH,'warn' if freshness in ('STALE','CLOSED') else 'neutral'),
         badge('Публикация',pub.get('state'),PUBLICATION,'success' if pub.get('state')=='DELIVERED' else 'warn'),'</div>']
    if state=='FAILED':
        out.append(f'<section class="notice error" role="alert"><h2>Ошибка текущего поколения {e(resource["generation"])}</h2><p>{reason(job.get("reason"))}. Предыдущий результат, если он есть, показан отдельно.</p></section>')
    if resource['closed']:
        out.append('<section class="notice neutral"><h2>Ресурс закрыт</h2><p>Показано сохранённое состояние. Применимость к новым изменениям не подтверждается.</p></section>')
    if pub.get('state') in ('SENDING','UNKNOWN'):
        out.append('<section class="notice warn"><h2>Исход публикации неизвестен</h2><p>Не повторяйте отправку вслепую. Оператору нужно проверить доставку существующим протоколом восстановления.</p></section>')
    if analysis is None:
        out.append('<section class="empty-state"><h2>Анализ ещё не выполнен</h2><p>Отсутствие результата не означает отсутствия влияния. Текущее состояние задания показано выше.</p></section>')
    elif not analysis['compatible'] or analysis['result'] is None:
        out.append('<section class="notice error"><h2>Результат несовместим</h2><p>Формат или коды сохранённого анализа не поддерживаются. Исходный payload и документ публикации не показываются как достоверный результат.</p></section>')
    else:
        raw=analysis['result'];status=raw.get('status');refs={v['id']:i for i,v in enumerate(raw.get('evidence',[]))}
        out.append(f'<section class="impact-block {"error" if status=="FAILED" else "warn"}"><h2>{e(STATUS.get(status,"Неизвестный код результата"))} <code>{e(status)}</code></h2><p>{e(raw.get("summary"))}</p><p>{reason(raw.get("reason_code"))}</p></section>')
        out.append('<p class="notice neutral">Статический вывод ограничен обследованным профилем. CURRENT означает совпадение поколения, а не гарантию совместимости или успешную доставку.</p>')
        if raw.get('deltas'):
            out.append('<section><h2>Что изменилось</h2><ul>'+''.join(
                f'<li><strong>{e(d["operation"]["service"])} · {e(d["operation"]["method"])} {e(d["operation"]["route"])}</strong><br><code>{e(d["code"])}</code> · {e(d["before"])} → {e(d["after"])}</li>' for d in raw['deltas'])+'</ul></section>')
        if raw.get('findings'):
            out.append('<section><h2>Наблюдения о потребителях</h2><ul>'+''.join(
                f'<li id="finding-{i}"><strong>{e(f["consumer"]["service"])}</strong> · <code>{e(f["code"])}</code><br>Использование: <code>{e(f["usage"])}</code> · Свежесть связи: {e(f["dependency_freshness"])}<br>{evidence_links(f["evidence_refs"],refs," · наблюдение")}</li>' for i,f in enumerate(raw['findings']))+'</ul></section>')
        affected=raw.get('affected',[])
        if affected:
            edges={r['id']:r['evidence_refs'] for r in raw.get('relationships',[])}
            out.append('<section><h2>Затронутые потребители</h2><ul>'+''.join(
                f'<li id="consumer-{i}"><strong>{e(a["service"]["service"])}</strong> · Владелец: {e(a["owner"]["status"])} {e(", ".join(t["team"] for t in a["owner"]["teams"]))}<br>{evidence_links([ref for edge in a["relationship_refs"] for ref in edges.get(edge,[])],refs," · "+a["service"]["service"])}</li>' for i,a in enumerate(affected))+'</ul></section>')
        claims=[]
        for claim in raw.get('claims',[]):
            links=' '.join(f'<a href="#evidence-{refs[ref]}">Основание {refs[ref]+1}</a>' for ref in claim['evidence_refs'] if ref in refs)
            kind='Факт в пределах профиля' if claim['kind']=='fact' else 'Гипотеза'
            claims.append(f'<article class="claim"><h3>{kind}</h3><p>{e(claim["statement"])}</p><p class="muted">Применимость: {e(claim["applicability"])} · Неопределённость: {e(claim["uncertainty"])}</p>{links}</article>')
        if claims:out.append('<section><h2>Выводы и основания</h2>'+''.join(claims)+'</section>')
        if raw.get('checks'):
            out.append('<section class="checks"><h2>Что проверить</h2><ul>'+''.join(
                f'<li><strong>{e(c["consumer"]["service"])}:</strong> {e(c["text"])}</li>' for c in raw['checks'])+'</ul></section>')
        for key,title in [('gaps','Пробелы обследования'),('unknowns','Неизвестное')]:
            if raw.get(key):
                out.append(f'<section class="notice warn"><h2>{title}</h2><ul>'+''.join(
                    '<li>'+e(' · '.join(str(v) for k,v in g.items() if v is not None and k in ('code','subject','repository','path','detail','reason')) )+'</li>' for g in raw[key])+'</ul></section>')
        out.append('<section id="evidence"><h2 tabindex="-1">Основания сохранённого анализа</h2>'+evidence_view(raw.get('evidence',[]))+'</section>')
    versions=[('Текущее поколение',resource['generation']),('Текущая версия ресурса',resource['version']),
              ('Поколение результата',analysis['generation'] if analysis else None),
              ('Версия ресурса в результате',analysis['resource_version'] if analysis else None),
              ('Поколение публикации',pub.get('generation')),('Доставленное поколение',resource['published_generation']),
              ('Профиль',((analysis or {}).get('result') or {}).get('profile')),
              ('Наблюдение ресурса (UTC)',observed(resource['updated_at'])),
              ('Наблюдение задания (UTC)',observed(job.get('updated_at')))]
    out.append('<details class="versions"><summary>Версии и ограничения</summary>'+pairs(versions)+'<p>Это последний сохранённый анализ, а не история всех поколений. Сравнение версий не загружено.</p></details>')
    return ''.join(out)


def workspace_view(data):
    listing=data['listing'];selected=data['selected'];rid=selected['resource']['resource_id'] if selected else None
    rows=[]
    for item in listing['items']:
        r=item['resource'];state=(item['current_job'] or {}).get('state');analysis=item['analysis']
        href='/ui/result?'+urlencode({'resource_id':r['resource_id']})
        active=' class="change-row selected" aria-current="page"' if r['resource_id']==rid else ' class="change-row"'
        label=JOB.get(state,'Неизвестный код') if state else 'нет задания'
        pub=(item['publication'] or {}).get('state')
        rows.append(f'<a{active} href="{e(href)}" data-resource="{e(r["resource_id"])}"><strong>{e(r["resource_id"])}</strong><span>{e(r["provider"])} · {e(r["kind"])} · Поколение {e(r["generation"])}</span><span>Анализ: {e(label)} <code>{e(state)}</code></span><span>Основание: {e(analysis["freshness"] if analysis else "нет результата")}</span><span>Публикация: {e(PUBLICATION.get(pub,"не выполнялась" if pub is None else "Неизвестный код"))} <code>{e(pub) if pub else ""}</code></span><span>UTC: {e(observed(r["updated_at"]))}</span></a>')
    empty='<p class="no-matches">Нет доступных изменений. Анализы могли ещё не получить подтверждение области доступа.</p>'
    more='<p class="notice warn">Есть дополнительные изменения за границей списка.</p>' if listing['has_more'] else ''
    scan='<p class="list-limit">За одно чтение проверяется не более 1000 кандидатов. Список может быть неполным; количество скрытых результатов не раскрывается.</p>'
    note='<p class="list-limit">Последние 100 доступных изменений максимум — не вся история. Старые результаты без подтверждения области доступа не включены.</p>'
    return {'list_html':''.join(rows) or empty,'list_note_html':note+more+scan,'result_html':result_view(selected)}
