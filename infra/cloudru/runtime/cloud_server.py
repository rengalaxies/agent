"""Cloud boundary for staged, verified product commit; no executor authority."""
import base64,json,os,socket,sqlite3
from pathlib import Path
from fastapi import HTTPException
from fastapi.responses import HTMLResponse,JSONResponse
from lab.product.api import create_app
app=create_app()
CAPS={'runtime_controller_commit':os.getenv('LAB_RUNTIME_CONTROLLER_COMMIT','UNKNOWN'),'product_commit':'107dfd14292a5ab06593d424bf0b94f1cccb0b90','new_agent_runs':'UNAVAILABLE','new_independent_checks':'UNAVAILABLE','saved_demonstrations':'AVAILABLE','execution_permission':False,'reason':'No qualified isolated CI executor is connected. No LLM credential is deployed. Historical PASS applies only to its recorded inputs.'}
@app.middleware('http')
async def boundary(request,call_next):
 # Authentication remains enforced by the product middleware and whole-origin proxy.
 if request.url.path=='/api/lab/jobs' and request.method=='POST':
  expected='Basic '+base64.b64encode((os.environ['LAB_AUTH_USERNAME']+':'+os.environ['LAB_AUTH_PASSWORD']).encode()).decode()
  if request.headers.get('authorization')!=expected:return JSONResponse({'detail':'Authentication required'},status_code=401)
  try:p=await request.json()
  except Exception:return JSONResponse({'detail':'Invalid JSON'},status_code=400)
  if p.get('operation')=='verify' or (p.get('operation') in ('analysis','prepare') and p.get('mode')=='LIVE RUN'):
   return JSONResponse({'detail':CAPS['reason'],'status':'UNAVAILABLE','job_created':False},status_code=409)
 response=await call_next(request)
 if request.url.path=='/' and response.status_code==200:
  body=b''.join([part async for part in response.body_iterator]).decode()
  banner='<aside style="padding:16px;background:#fff3cd;color:#332b00">Cloud runtime: применение BLOCKED; новые агенты UNAVAILABLE; новая независимая проверка UNAVAILABLE. Анализ/патч: явно выбранный REPLAY. <a href="/saved-demo">Сохранённая проверка — исторический REPLAY</a></aside>'
  body=body.replace('<body>','<body>'+banner).replace('data-testid="verify-patch"','data-testid="verify-patch" disabled title="UNAVAILABLE: qualified CI executor is not connected"')
  return HTMLResponse(body,headers={k:v for k,v in response.headers.items() if k.lower() not in ('content-length','content-type')})
 return response
# Insert before any static routes; product auth middleware covers these routes as well.
@app.get('/api/lab/capabilities')
def capabilities():return CAPS
@app.get('/api/lab/readyz')
def ready():
 import psycopg,urllib.request
 try:
  with psycopg.connect(os.environ['SOURCE_READ_DSN'],connect_timeout=3) as c:c.execute('SELECT 1')
  with socket.create_connection(('rabbitmq',5672),timeout=3):pass
  with sqlite3.connect(os.environ['LAB_PRODUCT_DB']) as c:c.execute('SELECT 1')
 except Exception:raise HTTPException(503,'Component readiness unavailable') from None
 return {'ready':True,'components':['sqlite','postgres','rabbitmq'],'execution_permission':False}
@app.get('/saved-demo',response_class=HTMLResponse)
def saved():
 return '''<html lang="ru"><meta charset="utf-8"><title>Исторический REPLAY</title><body><h1>REPLAY — сохранённая демонстрация</h1><p>Это не проверка текущего патча и не разрешение на применение.</p><p>Проверенный продукт: commit 107dfd14292a5ab06593d424bf0b94f1cccb0b90, <a href="https://github.com/rengalaxies/agent/actions/runs/39105701043">Actions 39105701043</a>.</p><p>Реальный агентный проход: <a href="https://github.com/rengalaxies/agent/actions/runs/39068862920">Actions 39068862920</a>, модель openai/gpt-oss-120b; происхождение и точные входы сохранены в репозитории.</p><p><a href="/api/lab/saved-demo">Историческая квитанция 46bb9c61 (Actions 39070509491)</a> · <a href="/">Вернуться в сценарий</a></p></body></html>'''
@app.get('/api/lab/saved-demo')
def saved_receipt():
 path=Path('/work/lab/reports/interview/first-ci/session-one-state.json')
 return {'mode':'REPLAY','current_candidate_verification':False,'source_commit':'46bb9c61fc7a279d863e5e87656985b7833713a5','actions_run':'https://github.com/rengalaxies/agent/actions/runs/39070509491','artifact_path':str(path.relative_to('/work')),'receipt':json.loads(path.read_text())}
