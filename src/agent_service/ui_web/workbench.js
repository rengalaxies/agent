"use strict";
const $=id=>document.getElementById(id);
let csrf=null,revision=0,expiry=null,poll=null,controller=null,signingOut=false;
let exitUnconfirmed=false;
let loadedPath=location.pathname+location.search;
function clear(){
  revision++;clearTimeout(expiry);clearTimeout(poll);expiry=poll=null;
  controller?.abort();controller=null;csrf=null;
  $('private').hidden=true;$('account').hidden=true;$('account').textContent='';$('logout').hidden=true;
  for(const id of ['workspace','change-list','list-note','observation'])$(id).replaceChildren();
  document.querySelectorAll('[data-operator]').forEach(el=>el.hidden=true);
  document.title='Результаты · ImpactMap';
}
function signIn(){
  clear();$('search').value='';location.replace('/ui/login?'+new URLSearchParams({next:location.pathname+location.search}));
}
function filter(){
  const query=$('search').value.toLocaleLowerCase('ru');
  const rows=[...$('change-list').querySelectorAll('[data-resource]')];
  for(const row of rows)row.hidden=!row.textContent.toLocaleLowerCase('ru').includes(query);
  $('no-matches').hidden=!rows.length||rows.some(row=>!row.hidden);
}
function showFailure(text){
  if(!csrf)clear();
  else{
    clearTimeout(poll);poll=null;$('private').hidden=true;
    for(const id of ['workspace','change-list','list-note','observation'])$(id).replaceChildren();
  }
  $('message').textContent=text;
}
function schedule(){
  if($('auto-refresh').checked&&document.visibilityState==='visible'&&!signingOut)
    poll=setTimeout(()=>load(false),30000);
}
async function load(focus=false){
  if(signingOut||document.visibilityState!=='visible')return;
  loadedPath=location.pathname+location.search;
  clear();const current=revision;controller=new AbortController();
  const options={cache:'no-store',credentials:'same-origin',signal:controller.signal};
  $('message').textContent='Проверяем доступ и загружаем сохранённые данные…';
  try{
    const started=performance.now();
    const auth=await fetch('/ui/api/me',options);
    if(current!==revision)return;
    if(auth.status===401||auth.status===403){signIn();return;}
    if(!auth.ok)throw Error('unavailable');
    const user=await auth.json();if(current!==revision)return;
    const remaining=user.valid_for_seconds*1000-(performance.now()-started);
    if(!Number.isFinite(remaining)||remaining<=0){signIn();return;}
    csrf=user.csrf;
    expiry=setTimeout(signIn,remaining);
    $('account').textContent=`${user.username} · ${user.role==='operator'?'Оператор':'Ревьюер'} · ${user.installation_id} / ${user.environment}`;
    $('account').hidden=false;$('logout').hidden=false;
    const section=location.pathname.split('/').pop();
    let endpoint='/ui/api/view';
    if(section==='result')endpoint+='?'+new URLSearchParams({resource_id:new URLSearchParams(location.search).get('resource_id')||''});
    const operator=['operations','connections'].includes(section);
    if(operator)endpoint='/ui/api/'+section;
    const response=await fetch(endpoint,options);if(current!==revision)return;
    if(response.status===401){signIn();return;}
    if(response.status===403){
      showFailure(operator?'Для этого раздела нужна роль оператора. Вернитесь в «Изменения».':'Область доступа изменилась. Войдите заново.');
      return;
    }
    if(response.status===404){showFailure('Результат не найден или недоступен в вашей области. Откройте список через ImpactMap.');return;}
    if(response.status===400){showFailure('Некорректная ссылка результата. Откройте список через ImpactMap.');return;}
    if(!response.ok)throw Error('unavailable');
    const data=await response.json();if(current!==revision)return;
    document.querySelectorAll('[data-operator]').forEach(el=>el.hidden=user.role!=='operator');
    document.querySelectorAll('[data-section]').forEach(el=>{
      const active=el.dataset.section===(operator?section:'changes');
      el.classList.toggle('active',active);if(active)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');
    });
    // Only escaped, server-rendered fragments from this authenticated fixed endpoint.
    // No raw result fields, publisher document or external HTML are assigned to innerHTML.
    if(operator){
      $('workspace').innerHTML=data.result_html;
    }else{
      $('change-list').innerHTML=data.list_html;$('list-note').innerHTML=data.list_note_html;
      $('workspace').innerHTML=data.result_html;
      const time=new Date(data.observed_at*1000);
      $('observation').textContent=Number.isFinite(time.getTime())?'Прочитано: '+time.toISOString():'Время чтения неизвестно';
      filter();
    }
    $('changes-panel').hidden=operator;$('private').classList.toggle('operator',operator);
    const observed=new Date(data.observed_at*1000);
    $('observation').textContent=Number.isFinite(observed.getTime())?'Прочитано: '+observed.toISOString():'Время чтения неизвестно';
    $('private').hidden=false;$('message').textContent='';
    if(focus)$('workspace').querySelector('h1')?.focus();
    schedule();
  }catch(error){
    if(current!==revision||error.name==='AbortError')return;
    showFailure('Не удалось загрузить данные. Сохранённый экран скрыт; повторите обновление.');
  }
}
document.addEventListener('click',event=>{
  const link=event.target.closest('a');
  if(!link||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const url=new URL(link.href);
  if(url.origin!==location.origin||!['/ui/changes','/ui/result','/ui/operations','/ui/connections'].includes(url.pathname)||url.hash)return;
  event.preventDefault();history.pushState(null,'',url.pathname+url.search);load(true);
});
$('search').addEventListener('input',filter);
$('refresh').addEventListener('click',()=>load(false));
$('auto-refresh').addEventListener('change',()=>{clearTimeout(poll);schedule();});
$('logout').addEventListener('click',async()=>{
  const token=csrf;signingOut=true;exitUnconfirmed=false;clear();$('message').textContent='Завершаем сессию…';
  try{
    const send=value=>fetch('/ui/api/logout',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'X-CSRF-Token':value||''}});
    let response=await send(token);
    if(response.status===403){
      const renewed=await fetch('/ui/api/me',{cache:'no-store',credentials:'same-origin'});
      if(renewed.status===401){signIn();return;}
      if(renewed.ok)response=await send((await renewed.json()).csrf);
    }
    if(response.ok||response.status===401){notifySignedOut();signIn();return;}
    throw Error('unavailable');
  }catch{exitUnconfirmed=true;csrf=token;$('logout').hidden=false;$('message').textContent='Сервер не подтвердил выход. Повторите выход; закрытие страницы не отзывает сессию.';}
});
function resume(){
  if(exitUnconfirmed){clear();$('logout').hidden=false;$('message').textContent='Сервер не подтвердил выход. Повторите выход; закрытие страницы не отзывает сессию.';}
  else load();
}
addEventListener('popstate',()=>{if(location.pathname+location.search!==loadedPath)load(true);});
onSignedOut(signIn);
addEventListener('pagehide',()=>{clear();$('search').value='';});
addEventListener('pageshow',event=>{if(event.persisted)resume();});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')resume();else{clear();$('search').value='';}});
load();
