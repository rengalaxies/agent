"""Real disposable services + API/browser scenarios, then separately gated live model path."""
import copy,hashlib,json,os,secrets,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
import httpx

ROOT=Path.cwd();OUT=ROOT/'product-evidence';OUT.mkdir(exist_ok=True);OUT.chmod(0o777)
URL='http://127.0.0.1:8088';client=httpx.Client(base_url=URL,timeout=15)

def main(live=False):
    env=dict(os.environ);project='dm-product-'+secrets.token_hex(5);env['LAB_APP_IMAGE']=project+':app'
    for name in ['PG_ADMIN_PASSWORD','ORDERS_PASSWORD','BILLING_PASSWORD','VERIFIER_PASSWORD','RABBIT_PASSWORD']:
        env[name]=secrets.token_hex(24);print('::add-mask::'+env[name])
    override=OUT/'compose-ci.json';override.write_text(json.dumps({'services':{'postgres':{'ports':['127.0.0.1::5432']},'rabbitmq':{'ports':['127.0.0.1::15672']}},'networks':{'lab':{'internal':False}}}))
    base=['docker','compose','-p',project,'-f','lab/compose.yaml','-f',str(override)]
    report={'outcome':'FAIL','source_commit':env['GITHUB_SHA'],'mode':'LIVE RUN' if live else 'INTEGRATION + REPLAY / CONTROL',
        'actions_run':'https://github.com/'+env['GITHUB_REPOSITORY']+'/actions/runs/'+env['GITHUB_RUN_ID'],
        'execution_permission':False,'vm_actions':[],'external_notifications':0,'scenarios':{},'errors':[]}
    server=None
    def cmd(args,timeout=180):
        p=subprocess.run(base+args,env=env,capture_output=True,text=True,timeout=timeout)
        if p.returncode:raise RuntimeError('COMPOSE_'+args[0]+'_FAILED')
        return p.stdout
    def post(path,data,status=200):
        r=client.post('/api/lab'+path,json=data);assert r.status_code==status,(path,r.status_code,r.text[:200]);return r.json()
    def state():return client.get('/api/lab/state').json()
    def wait(cid,op,mode,key=None,allow_fail=False):
        j=post('/jobs',dict(change_id=cid,operation=op,mode=mode,idempotency_key=key or secrets.token_hex(12)),202)
        deadline=time.monotonic()+600
        while time.monotonic()<deadline:
            value=next(x for x in state()['jobs'] if x['id']==j['id'])
            if value['status'] not in ['QUEUED','RUNNING']:
                if not allow_fail:assert value['status']=='SUCCEEDED',value
                return value
            time.sleep(.2)
        raise AssertionError('JOB_TIMEOUT')
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
        example=client.get('/api/lab/examples').json();(OUT/'examples.json').write_text(json.dumps(example,indent=2))
        # The UI itself creates, collects, analyses, records a team decision, stages and verifies.
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True);page=browser.new_page(viewport={'width':1440,'height':1050});page.goto(URL)
            page.get_by_test_id('change-id').fill('live-new' if live else 'ui-breaking')
            page.get_by_test_id('create-change').click();page.get_by_test_id('tab-details').click()
            cid='live-new' if live else 'ui-breaking'
            def browserjob(button,operation,mode):
                before={j['id'] for j in state()['jobs']};page.get_by_test_id('mode').select_option(mode);page.get_by_test_id(button).click()
                deadline=time.monotonic()+600
                while time.monotonic()<deadline:
                    jobs=[j for j in state()['jobs'] if j['change_id']==cid and j['operation']==operation and j['id'] not in before]
                    if jobs and jobs[-1]['status'] not in ['QUEUED','RUNNING']:
                        assert jobs[-1]['status']=='SUCCEEDED',jobs[-1];page.get_by_test_id('refresh').click();time.sleep(.4);return jobs[-1]
                    time.sleep(.2)
                raise AssertionError('BROWSER_JOB_TIMEOUT_'+operation)
            browserjob('collect-snapshot','snapshot','LIVE RUN');page.screenshot(path=str(OUT/'01-sources.png'),full_page=True)
            mode='LIVE RUN' if live else 'REPLAY'
            browserjob('run-analysis','analysis',mode)
            cards=[c for c in state()['cards'] if c['change_id']==cid and c['current']];assert {c['team'] for c in cards}=={'billing','analytics'}
            page.get_by_test_id('tab-inbox').click();page.get_by_test_id('role').select_option('billing');page.get_by_test_id('save-decision').first.click()
            for _ in range(40):
                if any(d['change_id']==cid for d in state()['decisions']):break
                time.sleep(.1)
            assert any(d['change_id']==cid and not d['grants_execution'] for d in state()['decisions'])
            page.screenshot(path=str(OUT/'02-inbox.png'),full_page=True)
            page.get_by_test_id('tab-patch').click();browserjob('prepare-patch','prepare',mode)
            page.screenshot(path=str(OUT/'03-patch.png'),full_page=True)
            browserjob('verify-patch','verify',mode);page.screenshot(path=str(OUT/'04-verification.png'),full_page=True)
            verification=[v for v in state()['verifications'] if v['change_id']==cid][-1];assert verification['outcome']=='PASS'
            assert post('/apply',{'role':'initiator','approved':True},403)
            report['scenarios']['A']={'status':'PASS','layers':['browser','API','live catalogs','fresh PostgreSQL/RabbitMQ financial verifier'],'mode':mode,'verification_id':verification['id']}
            report['scenarios']['H']={'status':'PASS','layers':['browser disabled apply','direct API 403']}
            if not live:
                page.get_by_test_id('tab-changes').click();page.get_by_test_id('change-id').fill('safe-docs');page.get_by_test_id('kind').select_option('safe');page.get_by_test_id('create-change').click()
                for _ in range(40):
                    if any(c['change_id']=='safe-docs' for c in state()['changes']):break
                    time.sleep(.1)
                wait('safe-docs','snapshot','LIVE RUN');wait('safe-docs','analysis','FIXTURE / CONTROL')
                assert not any(c['change_id']=='safe-docs' and c['current'] for c in state()['cards'])
                report['scenarios']['B']={'status':'PASS','layers':['browser creation','API','server docs-only profile control']}
                page.get_by_test_id('tab-details').click();page.get_by_test_id('selected-change').select_option(cid)
                original=state();change=next(c for c in original['changes'] if c['change_id']==cid);revision={k:change[k] for k in ['change_id','title','intent','proposed_diff','proposed_files','source_commit','kind']};revision['revision']=2
                post('/changes',revision);assert not any(x['current'] for kind in ['cards','decisions','candidates','verifications','assessments'] for x in state()[kind] if x['change_id']==cid)
                page.get_by_test_id('refresh').click();time.sleep(.4);page.screenshot(path=str(OUT/'05-stale.png'),full_page=True)
                report['scenarios']['D']={'status':'PASS','layers':['API','browser stale display'],'old_verification':verification['id']}
                # New server collector reads a deliberately edited owner catalog from a copied repository.
                import shutil
                owner_root=OUT/'owner-control-root';(owner_root/'lab').mkdir(parents=True)
                for folder in ['app','sql','contracts','catalog']:shutil.copytree(ROOT/'lab'/folder,owner_root/'lab'/folder)
                # collect() needs exact source commit: use inherited real Git metadata as read-only source.
                (owner_root/'.git').write_text('gitdir: '+str(ROOT/'.git')+'\n')
                owners=json.loads((owner_root/'lab/catalog/owners.json').read_text());owners['bindings']=[b for b in owners['bindings'] if b['object_ref']!='lab/app/service.py#consume'];(owner_root/'lab/catalog/owners.json').write_text(json.dumps(owners))
                stop();env['LAB_REPO_ROOT']=str(owner_root);start()
                unknown=copy.deepcopy(example['breaking']);unknown.update(change_id='unknown-owner',title='unknown-owner',kind='breaking',revision=1,source_commit=env['GITHUB_SHA']);post('/changes',unknown)
                wait('unknown-owner','snapshot','LIVE RUN');wait('unknown-owner','analysis','FIXTURE / CONTROL')
                assert any(c['change_id']=='unknown-owner' and c['team']=='COORDINATOR' for c in state()['cards'])
                report['scenarios']['C']={'status':'PASS','layers':['API','declared owner catalog controlled mutation'],'mode':'FIXTURE / CONTROL ownership; live DB/broker catalogs'}
                stop();env['LAB_REPO_ROOT']=str(ROOT);start()
                # E actual broker change, then a new real collection invalidates an existing assessment.
                e=copy.deepcopy(example['breaking']);e.update(change_id='binding-change',title='binding-change',kind='breaking',revision=1,source_commit=env['GITHUB_SHA']);post('/changes',e)
                wait('binding-change','snapshot','LIVE RUN');wait('binding-change','analysis','FIXTURE / CONTROL');before=state()['snapshots'][-1]
                code="from lab.app.service import rabbit\nc=rabbit();c.channel().queue_bind(queue='billing',exchange='orders.events',routing_key='control.changed');c.close()"
                cmd(['run','--rm','--entrypoint','python','app','-c',code]);wait('binding-change','snapshot','LIVE RUN');after=state()['snapshots'][-1]
                assert before['basis_digest']!=after['basis_digest'];assert not any(a['change_id']=='binding-change' and a['current'] for a in state()['assessments'])
                (OUT/'binding-before.json').write_text(json.dumps(before,indent=2));(OUT/'binding-after.json').write_text(json.dumps(after,indent=2))
                report['scenarios']['E']={'status':'PASS','layers':['real RabbitMQ mutation','live collector','API invalidation'],'before':before['basis_digest'],'after':after['basis_digest']}
                # F real asynchronous API job with explicitly deterministic delayed analysis control.
                stop();start(delay_analysis='2')
                f=copy.deepcopy(example['breaking']);f.update(change_id='late-analysis',title='late-analysis',kind='breaking',revision=1,source_commit=env['GITHUB_SHA']);post('/changes',f);wait('late-analysis','snapshot','LIVE RUN')
                j=post('/jobs',dict(change_id='late-analysis',operation='analysis',mode='FIXTURE / CONTROL',idempotency_key='late'),202)
                for _ in range(40):
                    if next(x for x in state()['jobs'] if x['id']==j['id'])['status']=='RUNNING':break
                    time.sleep(.1)
                f['revision']=2;post('/changes',f)
                for _ in range(60):
                    job=next(x for x in state()['jobs'] if x['id']==j['id'])
                    if job['status']=='SUCCEEDED':break
                    time.sleep(.1)
                assert job['status']=='SUCCEEDED';assert all(not a['current'] for a in state()['assessments'] if a['change_id']=='late-analysis')
                report['scenarios']['F']={'status':'PASS','layers':['asynchronous API','delayed CONTROL worker'],'job':j['id']}
                # G kill actual API/worker process while collector job RUNNING; restart same SQLite.
                stop();start(delay_collect='20');g=copy.deepcopy(example['breaking']);g.update(change_id='restart-job',title='restart-job',kind='breaking',revision=1,source_commit=env['GITHUB_SHA']);post('/changes',g)
                j=post('/jobs',dict(change_id='restart-job',operation='snapshot',mode='LIVE RUN',idempotency_key='restart'),202)
                for _ in range(50):
                    if next(x for x in state()['jobs'] if x['id']==j['id'])['status']=='RUNNING':break
                    time.sleep(.1)
                previous=state();stop(kill=True);start();restored=state();restoredjob=next(x for x in restored['jobs'] if x['id']==j['id']);assert restoredjob['status']=='UNKNOWN'
                for kind in ['changes','cards','decisions','journal']:assert restored[kind]==previous[kind]
                same=post('/jobs',dict(change_id='restart-job',operation='snapshot',mode='LIVE RUN',idempotency_key='restart'),202);assert same['id']==j['id'] and same['status']=='UNKNOWN'
                report['scenarios']['G']={'status':'PASS','layers':['SIGKILL server process','SQLite restart','API idempotency'],'job':j['id']}
            else:
                report['live_usage']=[x for x in state()['journal'] if x['action']=='LLM_USAGE']
                report['snapshot_digest']=next(x['basis_digest'] for x in state()['snapshots'] if x['change_id']==cid)
                assert len(report['live_usage'])==2 and all(x['usage_complete'] for x in report['live_usage'])
                report['token_total']=sum(x['tokens'] for x in report['live_usage']);assert report['token_total']<=64000
            browser.close()
        snapshot=state()
        for row in snapshot['journal']:row.pop('artifact_ref',None)
        (OUT/'state.json').write_text(json.dumps(snapshot,indent=2,ensure_ascii=False))
        # Preserve private model requests/responses, no auth headers or environment dumped.
        stop()
        report['outcome']='PASS'
    except Exception as exc:
        report['errors'].append({'type':type(exc).__name__,'message':str(exc)[:1500] if isinstance(exc,AssertionError) else 'bounded step failed'})
        try:(OUT/'state-failed.json').write_text(json.dumps(state(),indent=2))
        except Exception:pass
    finally:
        stop()
        try:cmd(['down','--volumes','--remove-orphans'],120);report['cleanup']='PASS'
        except Exception:report['cleanup']='BLOCKED';report['outcome']='FAIL'
        (OUT/'report.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    return 0 if report['outcome']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main('--live' in sys.argv))
