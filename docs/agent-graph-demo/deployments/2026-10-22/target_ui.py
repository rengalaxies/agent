"""Actual target VM UI + SSH operator acceptance. No mocks or LLM calls."""
import json
import os
from pathlib import Path
import shlex
import subprocess
import time
import uuid

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
BASE = 'http://127.0.0.1:18081'
SSH = ['ssh','-i',str(Path.home()/'.ssh/vkr-cloudru-dm-p1-ui-v2'),'-o','IdentitiesOnly=yes',
       '-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','dmadmin@45.151.31.140']


def remote(command, timeout=180):
    r = subprocess.run([*SSH,command],capture_output=True,text=True,encoding='utf-8',timeout=timeout)
    if r.returncode:
        raise RuntimeError('SSH operation failed: '+r.stderr[-500:])
    return r.stdout


def phase(value):
    assert value in {'idle','analysis','actual','restart','queue_probe'}
    remote('printf '+shlex.quote(value)+' | sudo -n tee /var/lib/agent-graph-demo/acceptance-phase >/dev/null')


def registry():
    return json.loads(remote('sudo -n cat /var/lib/agent-graph-demo/runtime/active.json'))


def operator(action, sid=None, version=None):
    args = ['sudo','-n','/usr/local/sbin/agent-graph-demo-operator',action,
            '--expected-generation',str(registry()['generation'])]
    if sid:
        args += ['--session',str(uuid.UUID(sid))]
    if version:
        assert version in {'A','B','D','E'}
        args += ['--version',version,'--check','collection','--output','/var/lib/agent-graph-demo/receipts']
    result = json.loads(remote(shlex.join(args)))
    assert result.get('status') != 'ERROR', result
    return result


def sandbox_count():
    return int(remote("sudo -n docker ps -aq --filter 'label=com.docker.compose.project' | xargs -r sudo -n docker inspect --format '{{index .Config.Labels \"com.docker.compose.project\"}}' | grep -c '^agent-graph-demo-sbx-' || true").strip() or 0)


def main():
    os.environ['PLAYWRIGHT_BROWSERS_PATH'] = str(OUT/'browser-cache')
    # Passwords stay in process memory; never printed or copied into reports.
    logins = json.loads(remote('sudo -n cat /etc/agent-graph-demo/private-test-logins.json'))
    report = dict(scope='TARGET_VM_DM_P1_UI_VIA_LOCAL_SSH_TUNNEL',status='RUNNING',
                  started_epoch=time.time(),base_url=BASE,shows=[],screenshots=[],model_calls=0)
    (OUT/'target-report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            anon=browser.new_context()
            assert anon.request.get(BASE).status == 401
            anon.close()
            ctx=browser.new_context(viewport={'width':1440,'height':1100},http_credentials={'username':'operator','password':logins['operator']})
            page=ctx.new_page()
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto(BASE)
            page.wait_for_selector('#sessions')

            def get(path):
                response=ctx.request.get(BASE+'/api/demo'+path)
                assert response.status == 200, (path,response.status)
                return response.json()

            def new_show():
                old=page.locator('#sessions').input_value()
                page.get_by_role('button',name='Новый показ',exact=True).click()
                page.wait_for_function("old=>document.querySelector('#sessions').value.length===36 && document.querySelector('#sessions').value!==old && document.querySelector('#message').textContent.includes('Новый показ A')",arg=old)
                return page.locator('#sessions').input_value()

            def prepare():
                phase('analysis')
                previous=len(get('/sessions/'+sid)['jobs'])
                page.get_by_role('button',name='Обследовать исходники',exact=True).click()
                deadline=time.monotonic()+180
                while True:
                    jobs=get('/sessions/'+sid)['jobs']
                    if len(jobs)>previous and jobs[-1]['status'] in ('SUCCEEDED','PARTIAL'):
                        break
                    assert time.monotonic()<deadline, 'target prepare timeout'
                    time.sleep(0.15)
                page.wait_for_function("()=>document.querySelector('#edges').children.length===3 && !document.querySelector('#prepare').disabled",timeout=180000)
                assert page.locator('#coverage').inner_text().startswith('Неполные данные')

            def select(version, running):
                phase('analysis')
                name={'B':'B · Лимит 100','D':'D · Исправить Reporting','E':'E · Добавить Export'}[version]
                page.get_by_role('button',name=name,exact=True).click()
                page.wait_for_function("v=>document.querySelector('#proposed').textContent.startsWith(v) && !document.querySelector('#prepare').disabled",arg=version,timeout=180000)
                assert page.locator('#running').inner_text()==running

            def actual(sid, version):
                phase('actual')
                result=operator('run',sid,version)
                assert result['status']==('FAIL' if version=='B' else 'PASS'), result
                assert result['consumers']['Billing']['actual_count']==250
                assert result['consumers']['Reporting']['actual_count']==(100 if version=='B' else 250)
                if version=='B':
                    assert result['consumers']['Reporting']['missing_ids']==list(range(101,251))
                if version=='E':
                    assert result['consumers']['Export']['actual_count']==250
                    assert result['consumers']['Export']['passed']
                assert result['health_control']=={'status':'available','service':'Status'}
                assert sandbox_count()==2
                page.get_by_role('button',name='Получить результаты',exact=True).click()
                page.wait_for_function("v=>document.querySelector('#running').textContent===v",arg=version)
                if version=='B':
                    page.wait_for_function("()=>document.querySelector('#checks').textContent.includes('Есть потери данных')")
                return result

            def shot(name):
                page.screenshot(path=str(OUT/name),full_page=True)
                report['screenshots'].append(name)

            for index in range(5):
                sid=new_show()
                prepare()
                graph=get('/sessions/'+sid+'/graph')
                operations={o['id']:o for o in graph['operations']}
                links={(d['consumer'],operations[d['operation_id']]['service']) for d in graph['dependencies']}
                assert ('Health','Status') in links and ('Health','Orders') not in links
                assert ('Reporting','Orders') in links and ('Billing','Orders') in links
                stages=[actual(sid,'A')]
                select('B','A')
                page.locator('#edges button').filter(has_text='Reporting → Orders').click()
                page.wait_for_function("()=>document.querySelector('#evidence-meta').textContent.includes('reporting / client.py')")
                assert 'requests.get' in page.locator('#source').inner_text()
                stages.append(actual(sid,'B'))
                if index==0:
                    shot('target-desktop-B.png')
                    page.set_viewport_size({'width':390,'height':844});shot('target-mobile-B.png')
                    assert page.evaluate('()=>document.documentElement.scrollWidth<=window.innerWidth')
                    page.set_viewport_size({'width':1440,'height':1100})
                    prepare()
                    refreshed_b=[j for j in get('/sessions/'+sid)['jobs'] if j['action']=='prepare_context'][-1]
                select('D','B');stages.append(actual(sid,'D'))
                select('E','D')
                assert page.locator('#edges button').count()==4
                page.locator('#edges button').filter(has_text='Export → Orders').click()
                page.wait_for_function("()=>document.querySelector('#evidence-meta').textContent.includes('export / client.py')")
                stages.append(actual(sid,'E'))
                page.locator('#history button').filter(has_text='Анализ B').first.click()
                page.wait_for_function("()=>document.querySelector('#freshness').textContent.includes('Исторический')")
                assert 'Export' not in page.locator('#graph-drawing').text_content()
                page.get_by_role('button',name='Вернуться к текущему результату').click()
                page.wait_for_function("()=>!document.querySelector('#freshness').textContent.includes('Исторический')")
                if index==0:
                    historical_diff=get('/sessions/'+sid+'/diff?job_id='+refreshed_b['id'])
                    assert historical_diff['version']=='B' and 'B/orders/app.py' in historical_diff['text']
                    report['historical_refresh_diff']='PASS: B retained after E'
                    page.locator('#edges button').filter(has_text='Export → Orders').click()
                    shot('target-desktop-E.png')
                operator('stop',sid)
                assert sandbox_count()==0
                report['shows'].append(dict(session_id=sid,stages=stages,sandbox_after_stop=0,
                                             health_identity='PASS',history_and_evidence='PASS',proposed_running='PASS'))
                (OUT/'target-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                print('TARGET_SHOW_PASS '+str(index+1),flush=True)

            first=report['shows'][0]['session_id']
            assert get('/sessions/'+first)['jobs']
            assert get('/sessions/'+first)['checks']
            report['auth']={'anonymous':401}
            response=ctx.request.post(BASE+'/api/demo/sessions',data={},headers={'Origin':'https://attacker.invalid'})
            assert response.status==403
            report['auth']['wrong_origin']=403
            # Explicit server-side viewer scope, never a client-supplied role.
            remote("sudo -n python3 -c "+shlex.quote("import json;from pathlib import Path;p=Path('/etc/agent-graph-demo/auth.json');d=json.loads(p.read_text());d['users'][1]['allowed_session_ids']=['"+first+"'];p.write_text(json.dumps(d)+chr(10))"))
            viewer=browser.new_context(http_credentials={'username':'viewer','password':logins['viewer']})
            assert viewer.request.get(BASE+'/api/demo/sessions/'+first).status==200
            assert viewer.request.get(BASE+'/api/demo/sessions/'+report['shows'][1]['session_id']).status==403
            assert viewer.request.post(BASE+'/api/demo/sessions',data={},headers={'Origin':BASE}).status==403
            report['auth'].update(viewer_read=200,viewer_foreign=403,viewer_mutation=403)
            viewer.close()
            assert not errors, errors
            phase('idle')
            report.update(status='PASS',finished_epoch=time.time(),browser_errors=errors,
                          sequential_full_shows=5,sandbox_containers_after_stop=0,
                          note='Actual target host services/receipts; CI results not substituted')
            print('TARGET_UI_ACCEPTANCE_PASS',flush=True)
        except BaseException as exc:
            report.update(status='FAIL',failure=type(exc).__name__,finished_epoch=time.time())
            try:
                page.screenshot(path=str(OUT/'target-failure.png'),full_page=True)
            except Exception:
                pass
            raise
        finally:
            (OUT/'target-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            browser.close()


if __name__=='__main__':
    main()
