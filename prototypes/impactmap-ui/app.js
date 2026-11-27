import {cases, connections, binding} from './fixtures.js';

const $ = id => document.getElementById(id);
const main = $('workspace');
const ui = {role:'operator', generation:'pr5', query:''};
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const icon = name => `<img src="assets/icons/${name}.svg" alt="" aria-hidden="true">`;
const badge = (label, tone='', glyph='circle-check') => `<span class="badge ${tone}">${icon(glyph)}${esc(label)}</span>`;
const jobLabels = {DONE:'завершён',FAILED:'ошибка',PARTIAL:'неполные данные',QUEUED:'в очереди',RUNNING:'выполняется'};
const freshLabels = {CURRENT:'актуально',STALE:'устарело',CLOSED:'ресурс закрыт',UNKNOWN:'неизвестно'};
const pubLabels = {DELIVERED:'доставлена',UNKNOWN:'исход неизвестен',SENDING:'отправка не подтверждена'};

function currentRoute(){
  let parts;
  try { parts = decodeURIComponent(location.hash.slice(1)).split('/').filter(Boolean); }
  catch { return {section:'invalid'}; }
  if (!parts.length) return {section:'changes',id:ui.generation};
  if (parts.length > 2) return {section:'invalid'};
  return {section:parts[0],id:parts[1]};
}

function list(){
  const route = currentRoute();
  const records = [cases[ui.generation],cases.pr4,cases.pr3];
  const shown = records.filter(r => `${r.title} ${r.source}`.toLocaleLowerCase('ru').includes(ui.query.toLocaleLowerCase('ru')));
  $('change-list').innerHTML = shown.length ? shown.map(r => `<a class="change-row ${route.id===r.id?'selected':''}" href="#/changes/${r.id}" ${route.id===r.id?'aria-current="page"':''}><strong>${esc(r.title)}</strong><span>${esc(r.source)} · Поколение ${r.generation}</span><span class="row-state">${icon(r.job==='DONE'?'circle-check':r.job==='FAILED'?'alert-triangle':'circle-help')}Анализ: ${esc(jobLabels[r.job]||r.job)}</span></a>`).join('') : '<p class="no-matches" role="status">Изменения не найдены. Попробуйте другой запрос.</p>';
}

function statusStrip(r){
  const failed=r.job==='FAILED';
  const jobTone=failed?'error':r.job==='DONE'?'':r.job==='QUEUED'?'neutral':'warn';
  const freshness=r.freshness ? `Основание: ${freshLabels[r.freshness]||r.freshness}` : 'Основание: нет результата';
  let pub = r.publication ? `Публикация: ${pubLabels[r.publication]||r.publication}` : 'Публикация: не выполнялась';
  if (r.savedGeneration) pub=`Доставлено поколение ${r.savedGeneration}`;
  return `<div class="status-strip" aria-label="Независимые состояния">${badge(`Анализ: ${jobLabels[r.job]||'неизвестный код'}`,jobTone,failed?'alert-triangle':r.job==='DONE'?'circle-check':'clock')}${badge(freshness,r.freshness==='CURRENT'?'':r.freshness==='CLOSED'?'neutral':'warn',r.freshness==='CURRENT'?'circle-check':'circle-help')}${badge(pub,r.publication==='DELIVERED'?'':r.publication?'warn':'neutral',r.publication==='DELIVERED'?'circle-check':'circle-help')}</div>`;
}

function result(r){
  document.title=`${r.title} · ImpactMap`;
  const header=`<h1 tabindex="-1">${esc(r.title)}</h1><p class="source-line">${esc(r.source)} · Поколение ${r.generation}</p>${statusStrip(r)}`;
  if (r.noResult) return header+`<section class="empty-state"><h2>Анализ ещё не выполнен</h2><p>Задание находится в очереди. Отсутствие результата не означает отсутствия влияния.</p><p class="muted">Время наблюдения: ${esc(r.updated)}. Автоматическое обновление в прототипе не выполняется.</p></section>`;
  if (!r.compatible) return header+`<section class="notice error"><div><h2>Результат несовместим</h2><p>Сервис отклонил формат сохранённого анализа. Исходный payload и документ не отображаются как достоверный результат.</p><p>Для проверки нужна совместимая версия анализатора и схемы.</p>${operatorLink('Проверить состояние обработки','#/operations')}</div></section>`;
  const error=r.error?`<section class="notice error error-banner" role="alert">${icon('alert-triangle')}<div><h2>Текущее поколение 3: ошибка анализа</h2><p>${esc(r.error)} Старый результат ниже помечен как устаревший.</p>${operatorLink('Разобраться с ошибкой','#/operations/pr4')}</div></section>`:'';
  const closed=r.closed?`<div class="notice neutral">${icon('clock')}<p>Ресурс закрыт. Показан сохранённый результат; его актуальность для новых изменений не подтверждается.</p></div>`:'';
  const unknown=!jobLabels[r.job]?`<div class="notice error" role="alert">${icon('circle-help')}<p>Неизвестный код: <strong>${esc(r.job)}</strong>. Успешное завершение не подтверждено.</p></div>`:'';
  const publishing=['UNKNOWN','SENDING'].includes(r.publication)?`<div class="notice">${icon('circle-help')}<div><strong>Исход публикации неизвестен</strong><p>Не выполняйте слепой повтор POST. Сначала проверьте marker и результат доставки.</p>${operatorLink('Порядок восстановления','#/operations/pr3')}</div></div>`:'';
  const evidence=r.code ? `<div class="code-box"><div class="code-heading">${icon('file-code')}<strong>${esc(r.repository)} / ${esc(r.path)}</strong><span class="pin">commit ${esc(r.commit)} · строка ${r.line}</span></div><pre id="evidence-code" tabindex="0" aria-label="Закреплённый фрагмент кода">${r.code.split('\n').map((line,i)=>`<span class="line-number">${r.line+i}</span>${esc(line)}`).join('\n')}</pre></div>` : `<div class="notice">${icon('alert-triangle')}<div><strong>Фрагмент исходника недоступен</strong><p class="muted">${esc(r.repository)} / ${esc(r.path)}</p><p>Полный исходник не подменяется текущей веткой или предположением. Требуется восстановить разрешённый доступ.</p></div></div>`;
  const fixed=r.id==='pr5-fixed';
  return header+error+closed+unknown+
    `<section class="impact-block"><h2>${esc(r.headline)}</h2><p class="consumer">Потребитель: <strong>${esc(r.consumer)}</strong></p><p>${esc(r.explanation)}</p></section>`+
    `<div class="notice">${icon('alert-triangle')}<p><strong>${fixed?'Нужна проверка.':'Статический риск.'}</strong> ${esc(r.caveat.replace(/^(Статический риск\.|Исправление требует проверки\.)\s*/,''))}</p></div>`+
    publishing+
    `<div class="action-row"><button class="primary" data-action="evidence">Открыть основание</button>${r.code?'<button data-action="source">Перейти к коду</button>':''}</div>`+
    `<section class="evidence-section" id="evidence" aria-labelledby="evidence-heading"><h2 id="evidence-heading" tabindex="-1">Основание: код потребителя</h2><p>${r.code?'В обследованном фрагменте найден вызов Orders.':'Разрешённые данные об этом потребителе неполны.'}</p>${evidence}<section class="check-block"><h3>Что проверить</h3><p>${esc(r.check)}</p>${r.id==='pr5'?'<a class="text-link" href="#/changes/pr5-fixed">Посмотреть авторский пример после исправления</a>':r.id==='pr5-fixed'?'<a class="text-link" href="#/changes/pr5">Сравнить с авторским примером риска</a>':''}</section></section>`+
    `<details class="details-block"><summary>Версии и ограничения результата</summary><dl><dt>Результат поколения</dt><dd>${r.savedGeneration||r.generation}</dd><dt>Текущее поколение</dt><dd>${r.generation}</dd><dt>Профиль примера</dt><dd>Статический Python HTTP/API</dd><dt>Наблюдение</dt><dd>${esc(r.updated)}</dd><dt>Источник</dt><dd>Авторские данные прототипа, не ответ работающего сервиса</dd><dt>Проверка поведения</dt><dd>Не выполнялась</dd></dl></details>`+
    `<dialog id="source-dialog" aria-labelledby="dialog-heading"><h2 id="dialog-heading">Закреплённый фрагмент</h2><p>${esc(r.repository)} / ${esc(r.path)} · commit ${esc(r.commit)}</p><pre tabindex="0">${esc(r.code||'Фрагмент недоступен')}</pre><p>Это авторский пример. Полный файл и внешнее хранилище кода не подключены.</p><button data-action="close-source">Закрыть</button></dialog>`;
}

function operatorLink(label,href){
  return ui.role==='operator'?`<a class="text-link" href="${href}">${esc(label)}</a>`:'<p class="muted">Для диагностики обратитесь к оператору установки.</p>';
}

function operations(id){
  return `<h1 tabindex="-1">Операции</h1><p class="section-intro">Состояние обработки и безопасный следующий шаг. Это авторские ситуации, а не наблюдение за работающей установкой.</p><div class="notice neutral">${icon('clock')}<p><strong>Состояние worker: не наблюдалось.</strong> Доступ к источникам и доставка результата проверяются отдельно.</p></div><div class="section-grid"><section class="operation-item" ${id==='pr4'?'id="selected-operation"':''}>${badge('Ошибка текущего поколения','error','alert-triangle')}<h2>PR #4: недоступен закреплённый commit</h2><p><code>commit_unavailable</code> · поколение 3. Предыдущий анализ поколения 2 сохранён с STALE.</p><p>Проверьте наличие точного commit в mirror и разрешённый доступ к Reporting. Не заменяйте pin другой веткой ради успешного результата.</p><a href="#/changes/pr4" class="text-link">Открыть результат с ошибкой</a></section><section class="operation-item" ${id==='pr3'?'id="selected-operation"':''}>${badge('Публикация: UNKNOWN','warn','circle-help')}<h2>PR #3: ответ на публикацию потерян</h2><p>Сначала выполните readback: найдите собственный marker и result-комментарий. Затем примените существующий recovery-протокол с сохранением idempotency.</p><p>Неполный доступ к Export — отдельная проблема анализа. Доставка комментария не устраняет её.</p><a href="#/changes/pr3" class="text-link">Открыть неполный результат</a> <a class="text-link" href="#/connections/kaiten">Состояние Kaiten</a></section></div><p class="muted check-block">Повтор анализа, перезапуск и публикация из этой панели не запускаются. Демонстрационное переключение роли не является серверной авторизацией.</p>`;
}

function connectionPage(id){
  const selected=connections.find(c=>c.id===id);
  return `<h1 tabindex="-1">Подключения</h1><p class="section-intro">Области доступа, последние наблюдения и явные привязки. Секреты не отображаются; внешние API из прототипа не вызываются.</p>${selected?`<section class="connection-detail" role="region" aria-label="Выбранное подключение"><h2>${esc(selected.name)}</h2><p>${esc(selected.detail)}</p><p class="muted">Последнее наблюдение: ${esc(selected.observed||'не выполнялось')}</p><a class="text-link" href="#/connections">Все подключения</a></section>`:''}<div>${connections.map(c=>`<section class="connection-row"><div><h2>${esc(c.name)}</h2><p>${esc(c.type)} · ${esc(c.scope)}</p></div>${badge(c.state,c.tone==='muted'?'neutral':c.tone,c.tone==='warn'?'alert-triangle':'clock')}<a href="#/connections/${c.id}" class="text-link">Подробности подключения ${esc(c.name)}</a></section>`).join('')}</div><section class="binding" id="binding"><h2>Привязка PR → задача</h2><dl><dt>Изменение</dt><dd>${esc(binding.pr)}</dd><dt>Назначение</dt><dd>${esc(binding.target)}</dd><dt>Основание</dt><dd>${esc(binding.type)}</dd><dt>Состояние</dt><dd>${esc(binding.state)}</dd></dl><p>Для PR #3 привязка не подтверждена. Это не означает отсутствия влияния; оператору нужно проверить явное соответствие задачи.</p><a href="#/changes/pr5" class="text-link">Открыть связанный результат PR #5</a><p class="muted check-block">Создание подключений, редактирование привязок и ключей появятся отдельным шагом после серверных команд. Сейчас доступен просмотр.</p></section>`;
}

function render(focus=false){
  const route=currentRoute();
  document.title='Страница не найдена · ImpactMap';
  document.querySelectorAll('[data-operator]').forEach(el=>el.hidden=ui.role!=='operator');
  document.querySelectorAll('[data-nav]').forEach(el=>{
    const active=el.dataset.nav===route.section;el.classList.toggle('active',active);
    if(active)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');
  });
  if (route.id==='pr5'||route.id==='pr5-fixed'){
    ui.generation=route.id;$('generation').value=ui.generation;
  }
  list();
  const restricted=['operations','connections'].includes(route.section)&&ui.role!=='operator';
  if(restricted)main.innerHTML='<section class="empty-state"><h1 tabindex="-1">Раздел оператора</h1><p>Для просмотра нужна роль оператора. В прототипе это имитация доступа; серверной авторизации здесь нет.</p><a href="#/changes/pr5" class="text-link">Вернуться к результатам</a></section>';
  else if(route.section==='changes'&&route.id&&Object.hasOwn(cases,route.id))main.innerHTML=result(cases[route.id]);
  else if(route.section==='changes'&&!route.id){document.title='Изменения · ImpactMap';main.innerHTML='<section class="empty-state"><h1 tabindex="-1">Выберите изменение</h1><p>Откройте результат в списке слева. Видны последние 100 изменений максимум, а не вся история.</p></section>';}
  else if(route.section==='operations'&&(!route.id||['pr3','pr4'].includes(route.id)))main.innerHTML=operations(route.id);
  else if(route.section==='connections'&&(!route.id||connections.some(c=>c.id===route.id)))main.innerHTML=connectionPage(route.id);
  else main.innerHTML='<section class="empty-state not-found"><h1 tabindex="-1">Страница не найдена</h1><p>Изменение или подключение отсутствует в этом авторском наборе.</p><a class="text-link" href="#/changes/pr5">К списку изменений</a></section>';
  if(route.section!=='changes')document.title=`${restricted?'Доступ ограничен':route.section==='operations'?'Операции':route.section==='connections'?'Подключения':'Страница не найдена'} · ImpactMap`;
  if(focus){main.querySelector('h1')?.focus({preventScroll:true});if(window.matchMedia('(max-width:700px)').matches)main.scrollIntoView({block:'start'});else window.scrollTo(0,0);}
  $('announcement').textContent=main.querySelector('h1')?.textContent||'Страница обновлена';
}

$('search').addEventListener('input',e=>{ui.query=e.target.value;list();});
$('role').addEventListener('change',e=>{ui.role=e.target.value;render();$('announcement').textContent=`Роль в прототипе: ${ui.role==='operator'?'оператор':'ревьюер'}. Доступ имитируется.`;});
$('generation').addEventListener('change',e=>{ui.generation=e.target.value;location.hash=`/changes/${ui.generation}`;});
$('fixture').addEventListener('change',e=>{if(e.target.value)location.hash=`/changes/${e.target.value}`;});
document.querySelector('.skip').addEventListener('click',e=>{e.preventDefault();main.focus();main.scrollIntoView();});
main.addEventListener('click',e=>{
  const action=e.target.closest('[data-action]')?.dataset.action;
  if(action==='evidence'){$('evidence-heading')?.focus();$('evidence')?.scrollIntoView({block:'start',behavior:'auto'});}
  if(action==='source')$('source-dialog')?.showModal();
  if(action==='close-source')$('source-dialog')?.close();
});
window.addEventListener('hashchange',()=>render(true));
render();
