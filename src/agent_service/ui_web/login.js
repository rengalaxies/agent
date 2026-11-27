"use strict";
const form=document.getElementById('login');
const message=document.getElementById('message');
const submit=document.getElementById('submit');
form.addEventListener('submit',async event=>{
  event.preventDefault();submit.disabled=true;message.textContent='Проверяем вход…';
  try{
    const pre=await fetch('/ui/api/csrf',{cache:'no-store',credentials:'same-origin'});
    if(!pre.ok)throw Error('unavailable');
    const {csrf}=await pre.json();
    const body=JSON.stringify({username:form.elements.username.value,password:form.elements.password.value});
    form.elements.password.value='';
    const result=await fetch('/ui/api/login',{method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body});
    if(result.ok){
      const next=new URLSearchParams(location.search).get('next');
      let target='/ui/changes';
      if(next){
        const url=new URL(next,location.origin);
        if(url.origin===location.origin&&['/ui/changes','/ui/result','/ui/operations','/ui/connections'].includes(url.pathname)&&next.length<=2048)
          target=url.pathname+url.search;
      }
      location.replace(target);return;
    }
    message.textContent=result.status===429?'Слишком много попыток. Повтори вход позже.':result.status===401?'Не удалось войти. Проверь имя пользователя и пароль.':'Вход не выполнен. Обнови страницу и повтори попытку.';
  }catch{form.elements.password.value='';message.textContent='Сервис недоступен. Повтори попытку позже.';}
  finally{submit.disabled=false;}
});
