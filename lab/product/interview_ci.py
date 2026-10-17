"""CI_ONLY protected browser rehearsal on disposable real services; no inference key."""
import argparse,copy,hashlib,json,os,secrets,subprocess,sys,time,urllib.request
from datetime import datetime,timezone
from pathlib import Path
import httpx
from lab.runtime.core import digest

ROOT=Path.cwd();OUT=ROOT/'interview-evidence';OUT.mkdir(exist_ok=True);OUT.chmod(0o777)
URL='http://127.0.0.1:8088';client=httpx.Client(base_url=URL,timeout=15)

def main():
    env=dict(os.environ);project='dm-interview-'+secrets.token_hex(5);env['LAB_APP_IMAGE']=project+':app'
    for name in ['PG_ADMIN_PASSWORD','ORDERS_PASSWORD','BILLING_PASSWORD','VERIFIER_PASSWORD','RABBIT_PASSWORD']:
        env[name]=secrets.token_hex(24);print('::add-mask::'+env[name])
    override=OUT/'compose-ci.json';override.write_text(json.dumps({'services':{'postgres':{'ports':['127.0.0.1::5432']},'rabbitmq':{'ports':['127.0.0.1::15672']}},'networks':{'lab':{'internal':False}}}))
    base=['docker','compose','-p',project,'-f','lab/compose.yaml','-f',str(override)]
    report={'outcome':'FAIL','source_commit':env['GITHUB_SHA'],'mode':'CI_ONLY / REPLAY_ONLY',
        'actions_run':'https://github.com/'+env['GITHUB_REPOSITORY']+'/actions/runs/'+env['GITHUB_RUN_ID'],
        'execution_permission':False,'vm_actions':[],'external_notifications':0,'scenarios':{},'errors':[]}
    server=None
    env.pop('CLOUDRU_FOUNDATION_API_KEY',None)
    env.update(LAB_REQUIRE_AUTH='1',LAB_AUTH_USERNAME='ci_interview',LAB_AUTH_PASSWORD=secrets.token_hex(24))
    print('::add-mask::'+env['LAB_AUTH_PASSWORD'])
    client.auth=(env['LAB_AUTH_USERNAME'],env['LAB_AUTH_PASSWORD'])
    def cmd(args,timeout=180):
        p=subprocess.run(base+args,env=env,capture_output=True,text=True,timeout=timeout)
        if p.returncode:raise RuntimeError('COMPOSE_'+args[0]+'_FAILED')
        return p.stdout
    def start(delay_analysis='0',delay_collect='0'):
        nonlocal server
        e=dict(env,LAB_CONTROL_ANALYSIS_DELAY=delay_analysis,LAB_CONTROL_COLLECT_DELAY=delay_collect)
        server=subprocess.Popen([sys.executable,'-m','lab.product.ci_server'],env=e,stdout=open(OUT/'server.log','a'),stderr=subprocess.STDOUT)
        for _ in range(100):
            try:
                if client.get('/api/lab/healthz').status_code==200:return
            except httpx.HTTPError:pass
            time.sleep(.1)
        raise AssertionError('SERVER_START_FAILED')
    def stop(kill=False):
        nonlocal server
        if server:
            server.kill() if kill else server.terminate()
            server.wait(timeout=15);server=None
    try:
        assert hashlib.sha256((ROOT/'lab/product/SCENARIOS.json').read_bytes()).hexdigest()==(ROOT/'lab/product/SCENARIOS.sha256').read_text().split()[0]
        cmd(['build','app'],600);cmd(['up','-d','--wait','--wait-timeout','120','postgres','rabbitmq']);cmd(['run','--rm','bootstrap'])
        monitor=secrets.token_hex(20);print('::add-mask::'+monitor)
        cmd(['exec','-T','rabbitmq','rabbitmqctl','add_user','ci_monitor',monitor]);cmd(['exec','-T','rabbitmq','rabbitmqctl','set_user_tags','ci_monitor','monitoring'])
        cmd(['exec','-T','rabbitmq','rabbitmqctl','set_permissions','-p','/','ci_monitor','^$','^$','^$'])
        permissions=json.loads(cmd(['exec','-T','rabbitmq','rabbitmqctl','list_user_permissions','ci_monitor','--formatter=json']))
        permission=next(p for p in permissions if p['vhost']=='/')
        attest={'username':'ci_monitor',**permission,'broker_identity':'rabbit@rabbitmq','collected_at':datetime.now(timezone.utc).isoformat(),'source':'trusted CI rabbitmqctl list_user_permissions'}
        att=OUT/'monitor-permission-attestation.json';att.write_text(json.dumps(attest,indent=2))
        pgport=cmd(['port','postgres','5432']).strip().rsplit(':',1)[1];rbport=cmd(['port','rabbitmq','15672']).strip().rsplit(':',1)[1]
        env.update(SOURCE_READ_DSN=f"host=127.0.0.1 port={pgport} dbname=lab_source user=lab_verifier password={env['VERIFIER_PASSWORD']}",
            RABBIT_READ_URL='http://127.0.0.1:'+rbport,RABBIT_READ_USER='ci_monitor',RABBIT_READ_PASSWORD=monitor,
            RABBIT_PERMISSION_ATTESTATION_FILE=str(att),LAB_REPO_ROOT=str(ROOT),LAB_PRODUCT_DB=str(OUT/'state.sqlite'),LAB_ENABLE_ISOLATED_VERIFIER='1')
        start()
        assert httpx.get(URL+'/api/lab/state').status_code==401
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True)
            context=browser.new_context(http_credentials={'username':env['LAB_AUTH_USERNAME'],'password':env['LAB_AUTH_PASSWORD']},viewport={'width':1440,'height':1050})
            page=context.new_page();page.goto(URL)
            def request(method,path,payload=None):
                response=context.request.fetch(URL+'/api/lab'+path,method=method,data=payload)
                assert response.ok,(path,response.status,response.text()[:500])
                return response.json()
            def current():return request('GET','/sessions/current')['session']
            def sessionstate(sid=None):
                response=context.request.get(URL+'/api/lab/state',headers={'x-lab-session':sid} if sid else {})
                assert response.ok,response.text();return response.json()
            def settled(predicate,timeout=30):
                until=time.monotonic()+timeout
                while time.monotonic()<until:
                    value=predicate()
                    if value:return value
                    page.wait_for_timeout(100)
                raise AssertionError('INTERVIEW_WAIT_TIMEOUT')
            def new_session(scenario):
                previous=current()
                page.locator('#session-scenario').select_option(scenario);page.get_by_test_id('session-create').click()
                row=settled(lambda: (r if (r:=current()) and (not previous or r['session_id']!=previous['session_id']) else None))
                settled(lambda: not sessionstate()['changes']);page.get_by_test_id('tab-changes').click()
                page.get_by_test_id('revision').fill('1');page.get_by_test_id('change-id').fill('amount-transition')
                return row
            def create_change():
                page.get_by_test_id('create-change').click();settled(lambda: sessionstate()['changes'])
                page.get_by_test_id('tab-details').click()
            def job(button,op,mode,success=True):
                before={j['id'] for j in sessionstate()['jobs']}
                page.get_by_test_id('mode').select_option(mode);page.get_by_test_id(button).click()
                result=settled(lambda: next((j for j in sessionstate()['jobs'] if j['id'] not in before and j['operation']==op and j['status'] not in ['QUEUED','RUNNING']),None),600)
                assert (result['status']=='SUCCEEDED')==success,result
                page.get_by_test_id('refresh').click();page.wait_for_timeout(400);return result
            first=new_session('confirmed');assert not request('GET','/sessions/export')['observations']
            page.locator('#research-consent').check();page.locator('#save-consent').click();settled(lambda:current()['research_consent'])
            create_change();job('collect-snapshot','snapshot','LIVE RUN')
            # Actual LIVE request fails without an API key. No provider request is made and no implicit fallback occurs.
            failed=job('run-analysis','analysis','LIVE RUN',False);assert not sessionstate()['assessments']
            job('run-analysis','analysis','REPLAY')
            assert {c['team'] for c in sessionstate()['cards'] if c['current']}=={'billing','analytics'}
            page.get_by_test_id('tab-inbox').click();page.get_by_test_id('role').select_option('billing');page.get_by_test_id('save-decision').first.click()
            settled(lambda: sessionstate()['decisions']);assert not sessionstate()['decisions'][0]['grants_execution']
            page.screenshot(path=str(OUT/'01-confirmed-inbox.png'),full_page=True)
            page.get_by_test_id('tab-patch').click();job('prepare-patch','prepare','REPLAY');job('verify-patch','verify','REPLAY')
            assert sessionstate()['verifications'][-1]['outcome']=='PASS'
            page.screenshot(path=str(OUT/'02-replay-fresh-verifier.png'),full_page=True)
            assert context.request.post(URL+'/api/lab/apply',data={}).status==403
            page.locator('#moderator-help').select_option('navigation');page.locator('#save-help').click()
            with page.expect_download() as downloaded:page.locator('#export-research').click()
            downloaded.value.save_as(str(OUT/'synthetic-session-export.json'))
            exported=json.loads((OUT/'synthetic-session-export.json').read_text());assert exported['observations']
            assert any(x['action']=='MODERATOR_HELP' for x in exported['observations'])
            assert not any(k in json.dumps(exported) for k in ['decision-comment','billing-reviewer','password','proposed_diff'])
            first_state=sessionstate();(OUT/'session-one-state.json').write_text(json.dumps(first_state,indent=2))
            second=new_session('unknown-owner');assert not sessionstate()['decisions'] and not sessionstate()['cards']
            assert not request('GET','/sessions/export')['observations']
            create_change();job('collect-snapshot','snapshot','LIVE RUN');job('run-analysis','analysis','FIXTURE / CONTROL')
            assert any(c['team']=='COORDINATOR' for c in sessionstate()['cards'])
            page.get_by_test_id('tab-inbox').click();page.get_by_test_id('role').select_option('COORDINATOR')
            page.screenshot(path=str(OUT/'03-unknown-owner.png'),full_page=True)
            before= sessionstate(first['session_id']);page.locator('#session-reset').click();settled(lambda:current()['generation']==2)
            assert not sessionstate()['changes'];assert sessionstate(first['session_id'])==before
            report['scenarios']['isolation']={'status':'PASS','first':first['session_id'],'second':second['session_id'],'reset_generation':2,'other_session_unchanged':True}
            third=new_session('stale');create_change();job('collect-snapshot','snapshot','LIVE RUN');job('run-analysis','analysis','REPLAY')
            page.get_by_test_id('new-revision').click();page.get_by_test_id('create-change').click()
            settled(lambda:any(c['revision']==2 for c in sessionstate()['changes']))
            assert not any(c['current'] for c in sessionstate()['cards'])
            page.get_by_test_id('refresh').click();page.wait_for_timeout(400)
            page.get_by_test_id('tab-inbox').click();page.get_by_test_id('role').select_option('initiator');page.screenshot(path=str(OUT/'04-stale.png'),full_page=True)
            before_restart=sessionstate();stop();start();assert sessionstate()==before_restart
            report['scenarios']['restart']={'status':'PASS','persisted_session':third['session_id']}
            # Return explicitly to first session using the opaque session header for deletion/export checks.
            response=context.request.post(URL+'/api/lab/sessions/delete-research',headers={'x-lab-session':first['session_id']},data={});assert response.ok
            response=context.request.get(URL+'/api/lab/sessions/export',headers={'x-lab-session':first['session_id']});assert not response.json()['observations']
            assert sessionstate(first['session_id'])['decisions']==first_state['decisions']
            page.locator('#session-end').click();settled(lambda:current()['status']=='ENDED')
            report['scenarios'].update(confirmed={'status':'PASS','patch':'REPLAY','verifier':'fresh isolated PostgreSQL/RabbitMQ R1-R5'},unknown_owner={'status':'PASS','ownership':'explicit CONTROL','catalogs':'LIVE RUN'},stale={'status':'PASS','revision':2},live_unavailable={'status':'PASS','failed_job':failed['id'],'fallback':'explicit subsequent REPLAY job','provider_calls':0},research={'status':'PASS','consent':'explicit','export':'synthetic-session-export.json','deletion':'research only; technical decisions retained'},authentication={'status':'PASS','unauthenticated':401,'transport':'CI loopback HTTP only; no public deployment HTTPS claim'},apply={'status':'PASS','direct_api':403})
            browser.close()
        from lab.product.independent_rehearsal import run as rehearse
        rehearsal=rehearse(URL,env['LAB_AUTH_USERNAME'],env['LAB_AUTH_PASSWORD'],OUT/'independent')
        report['independent_rehearsal']={'target':'CI_ONLY','situations':[{k:i[k] for k in ('scenario','result')} for i in rehearsal['situations']]}
        assert all(i['result']=='COMPLETED' for i in rehearsal['situations']),'INDEPENDENT_REHEARSAL_INCOMPLETE'
        report['outcome']='PASS'
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__,'message':str(exc)[:1500] if isinstance(exc,AssertionError) else 'bounded step failed'})
        try:
            page.screenshot(path=str(OUT/'failure.png'),full_page=True)
            (OUT/'state-failed.json').write_text(json.dumps(sessionstate(),indent=2))
        except Exception:pass
        import traceback
        traceback.print_exc()
    finally:
        stop()
        try:cmd(['down','--volumes','--remove-orphans'],120);report['cleanup']='PASS'
        except Exception:report['cleanup']='BLOCKED';report['outcome']='FAIL'
        (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    return 0 if report['outcome']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())
