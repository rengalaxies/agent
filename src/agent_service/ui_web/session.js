"use strict";
const account=document.getElementById('account');
const message=document.getElementById('message');
const logout=document.getElementById('logout');
let csrf=null;
let expiryTimer=null;
let revision=0;
let signingOut=false;
let exitUnconfirmed=false;
function clear(){revision++;clearTimeout(expiryTimer);expiryTimer=null;csrf=null;account.hidden=true;logout.hidden=true;for(const id of ['username','role','installation','environment','role-description'])document.getElementById(id).textContent='';}
async function load(){
  clear();
  if(signingOut){
    if(exitUnconfirmed){logout.hidden=false;message.textContent='Сервер не подтвердил выход. Повтори выход; закрытие страницы не отзывает сессию.';}
    return;
  }
  const current=revision;
  const started=performance.now();
  try{
    const response=await fetch('/ui/api/me',{cache:'no-store',credentials:'same-origin'});
    if(current!==revision)return;
    if(response.status===401||response.status===403){location.replace('/ui/login');return;}
    if(!response.ok)throw Error('unavailable');
    const user=await response.json();
    if(current!==revision)return;
    // Relative server lifetime avoids trusting the client wall clock; subtract RTT conservatively.
    const remaining=user.valid_for_seconds*1000-(performance.now()-started);
    if(!Number.isFinite(remaining)||remaining<=0){clear();location.replace('/ui/login');return;}
    csrf=user.csrf;
    expiryTimer=setTimeout(()=>{clear();location.replace('/ui/login');},remaining);
    document.getElementById('username').textContent=user.username;
    document.getElementById('role').textContent=user.role==='operator'?'Оператор':'Ревьюер';
    document.getElementById('installation').textContent=user.installation_id;
    document.getElementById('environment').textContent=user.environment;
    document.getElementById('role-description').textContent=user.role==='operator'?'Доступ к результатам и операторским сведениям этой установки.':'Доступ к результатам разрешённой области. Операторские сведения закрыты.';
    account.hidden=false;logout.hidden=false;message.className='success';message.textContent='Вход выполнен. Права проверены сервером.';
  }catch{if(current!==revision)return;clear();message.textContent='Не удалось проверить сессию. Обнови страницу, чтобы повторить.';}
}
logout.addEventListener('click',async()=>{
  const token=csrf;signingOut=true;exitUnconfirmed=false;clear();message.textContent='Завершаем сессию…';
  try{
    const send=token=>fetch('/ui/api/logout',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'X-CSRF-Token':token||''}});
    let response=await send(token);
    // Another tab may have rotated the session cookie while this tab retained old CSRF.
    if(response.status===403){
      const renewed=await fetch('/ui/api/me',{cache:'no-store',credentials:'same-origin'});
      if(renewed.status===401){location.replace('/ui/login');return;}
      if(renewed.ok){const user=await renewed.json();response=await send(user.csrf);}
    }
    if(response.ok||response.status===401){notifySignedOut();location.replace('/ui/login');return;}
    throw Error('unavailable');
  }catch{exitUnconfirmed=true;csrf=token;logout.hidden=false;message.textContent='Сервер не подтвердил выход. Повтори выход; закрытие страницы не отзывает сессию.';}
});
addEventListener('pagehide',clear);
onSignedOut(()=>{clear();location.replace('/ui/login');});
addEventListener('pageshow',event=>{if(event.persisted)load();});
document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='visible')load();else clear();});
load();
