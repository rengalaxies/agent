"""Targeted external HTTPS browser acceptance; no inference or verifier calls."""
import json,time,pathlib
import httpx
URL='https://45-151-31-140.sslip.io';SOURCE='107dfd14292a5ab06593d424bf0b94f1cccb0b90'
def run(password,out,restart):
 from playwright.sync_api import sync_playwright
 out=pathlib.Path(out);out.mkdir(exist_ok=True)
 result={'outcome':'FAIL','url':URL,'source_commit':SOURCE,'llm_calls':0,'full_verifier_runs':0,'checks':{}}
 # TLS is validated by the default trust store. Never ignore certificate errors.
 for path in ['/','/ui/app.js','/api/lab/state','/api/lab/jobs','/api/lab/sessions/export','/api/lab/sessions/reset','/api/lab/apply','/saved-demo','/api/lab/saved-demo']:
  r=httpx.get(URL+path,timeout=20);assert r.status_code==401,(path,r.status_code)
 result['checks']['unauthenticated_all_routes']='PASS'
 with sync_playwright() as pw:
  browser=pw.chromium.launch(headless=True);context=browser.new_context(http_credentials={'username':'acceptance','password':password},viewport={'width':1440,'height':1050});page=context.new_page();page.goto(URL);assert 'UNAVAILABLE' in page.locator('body').inner_text()
  def req(method,path,payload=None,headers=None):
   r=context.request.fetch(URL+'/api/lab'+path,method=method,data=payload,headers=headers or {});assert r.ok,(path,r.status,r.text()[:300]);return r.json()
  def state(sid=None):return req('GET','/state',headers={'x-lab-session':sid} if sid else {})
  def current():return req('GET','/sessions/current')['session']
  def wait(fn,timeout=90):
   until=time.monotonic()+timeout
   while time.monotonic()<until:
    v=fn()
    if v:return v
    page.wait_for_timeout(200)
   raise AssertionError('TARGETED_WAIT_TIMEOUT')
  def new(scenario):
   old=current();page.locator('#session-scenario').select_option(scenario);page.get_by_test_id('session-create').click()
   row=wait(lambda: (r if (r:=current()) and (not old or r['session_id']!=old['session_id']) else None));wait(lambda:not state()['changes']);assert state()['source_commit']==SOURCE
   page.get_by_test_id('revision').fill('1');page.get_by_test_id('change-id').fill('amount-transition');page.get_by_test_id('create-change').click();wait(lambda:state()['changes']);page.get_by_test_id('tab-details').click();return row
  def job(button,op,mode):
   before={x['id'] for x in state()['jobs']};page.get_by_test_id('mode').select_option(mode);page.get_by_test_id(button).click()
   row=wait(lambda:next((j for j in state()['jobs'] if j['id'] not in before and j['operation']==op and j['status'] not in ('QUEUED','RUNNING')),None));assert row['status']=='SUCCEEDED',row;page.get_by_test_id('refresh').click();page.wait_for_timeout(300);return row
  first=new('confirmed');job('collect-snapshot','snapshot','LIVE RUN');job('run-analysis','analysis','REPLAY');assert {c['team'] for c in state()['cards'] if c['current']}=={'billing','analytics'}
  page.get_by_test_id('tab-inbox').click();page.get_by_test_id('role').select_option('billing');page.get_by_test_id('save-decision').first.click();wait(lambda:state()['decisions']);assert not state()['decisions'][0]['grants_execution'];page.screenshot(path=str(out/'01-confirmed.png'),full_page=True)
  page.get_by_test_id('tab-patch').click();job('prepare-patch','prepare','REPLAY')
  prior=state();candidate=prior['candidates'][-1]
  # Use exact job fields from current state, but the boundary must refuse before enqueue.
  payload={'change_id':'amount-transition','revision':1,'operation':'verify','mode':'REPLAY','candidate_id':candidate['id']}
  r=context.request.post(URL+'/api/lab/jobs',data=payload);assert r.status==409 and r.json()['job_created'] is False;assert state()['jobs']==prior['jobs'] and not state()['verifications']
  assert context.request.post(URL+'/api/lab/apply',data={}).status==403
  result['checks'].update(confirmed='PASS',replay_patch='PASS',verifier_unavailable_no_job='PASS',apply_403='PASS')
  before=state();second=new('unknown-owner');assert not state()['decisions'];job('collect-snapshot','snapshot','LIVE RUN');job('run-analysis','analysis','FIXTURE / CONTROL');assert any(c['team']=='COORDINATOR' for c in state()['cards']);page.get_by_test_id('tab-inbox').click();page.screenshot(path=str(out/'02-control-owner.png'),full_page=True)
  page.locator('#session-reset').click();wait(lambda:current()['generation']==2);assert not state()['changes'];assert state(first['session_id'])==before
  result['checks'].update(unknown_owner_control='PASS',sequential_session_isolation='PASS',targeted_reset='PASS')
  third=new('stale');job('collect-snapshot','snapshot','LIVE RUN');job('run-analysis','analysis','REPLAY');page.get_by_test_id('new-revision').click();page.get_by_test_id('create-change').click();wait(lambda:any(c['revision']==2 for c in state()['changes']));assert not any(c['current'] for c in state()['cards']);page.screenshot(path=str(out/'03-stale.png'),full_page=True)
  before_restart=state();restart();wait(lambda:context.request.get(URL+'/api/lab/readyz').ok,120);assert state()==before_restart;result['checks'].update(stale='PASS',restart_persistence='PASS')
  receipt=req('GET','/saved-demo');assert receipt['mode']=='REPLAY' and not receipt['current_candidate_verification'];assert receipt['receipt']['source_commit']==receipt['source_commit']
  caps=req('GET','/capabilities');assert caps['new_independent_checks']=='UNAVAILABLE' and caps['new_agent_runs']=='UNAVAILABLE'
  text=json.dumps({'state':state(),'saved':receipt,'capabilities':caps,'export':req('GET','/sessions/export')})
  assert password not in text
  assert not any(v in text for v in ['INTERNAL_PASSWORD','PG_ADMIN_PASSWORD','CLOUDRU_SECRET','BEGIN OPENSSH PRIVATE KEY'])
  result['checks'].update(saved_replay_provenance='PASS',secrets_absent='PASS',trusted_https_browser='PASS')
  result['outcome']='PASS';(out/'cloud-acceptance.json').write_text(json.dumps(result,indent=2));browser.close()
 return result
