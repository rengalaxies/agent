"""Capture fully loaded target evidence and a real provider-failure UNKNOWN state."""
import json
import os
import shlex
import time
from playwright.sync_api import sync_playwright
from target_ui import BASE, OUT, operator, registry, remote, sandbox_count

os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(OUT/'browser-cache')
logins=json.loads(remote('sudo -n cat /etc/agent-graph-demo/private-test-logins.json'))
sid=json.loads((OUT/'target-report.json').read_text())['shows'][0]['session_id']
ready=json.loads((OUT/'target-extra-report.json').read_text())['ready_session']
report=dict(scope='TARGET_VM_LOADED_UI_AND_REAL_PROVIDER_STOP',started_epoch=time.time())
remote('sudo -n systemctl stop agent-graph-demo-observe.timer')
try:
    receipt=operator('run',sid,'E')
    assert receipt['status']=='PASS'
    report['recheck_E']=receipt
    # Read-only metadata capture while the actual provider containers exist.
    import capture_limits
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1100},http_credentials={'username':'operator','password':logins['operator']})
        page=context.new_page();page.goto(BASE)
        def select_session(value, version):
            page.wait_for_function("v=>Array.from(document.querySelector('#sessions').options).some(o=>o.value===v)",arg=value)
            page.locator('#sessions').select_option(value)
            page.wait_for_function("v=>document.querySelector('#proposed').textContent.startsWith(v)&&!document.querySelector('#prepare').disabled",arg=version)
            assert page.locator('#sessions').input_value()==value
        select_session(sid,'E')
        page.wait_for_function("()=>document.querySelector('#running').textContent==='E' && document.querySelector('#edges').children.length===4")
        page.locator('#edges button').filter(has_text='Export → Orders').click()
        page.wait_for_function("()=>document.querySelector('#evidence-meta').textContent.includes('export / client.py') && !document.querySelector('#source').textContent.includes('Ожидание') && document.querySelector('#source').textContent.length>30")
        page.screenshot(path=str(OUT/'target-desktop-E-confirmed.png'),full_page=True)
        provider=remote("sudo -n docker ps -q --filter label=com.docker.compose.project=agent-graph-demo-sbx-"+sid+" --filter label=com.docker.compose.service=status").strip()
        assert len(provider)==12 and all(c in '0123456789abcdef' for c in provider)
        remote('sudo -n docker stop '+provider)
        try:
            operator('observe')
        except (RuntimeError,AssertionError):
            pass
        assert registry()['state']=='UNKNOWN'
        page.reload();select_session(sid,'E')
        page.wait_for_function("()=>document.querySelector('#running').textContent==='Не подтверждено' && document.querySelector('#edges').children.length===4")
        page.screenshot(path=str(OUT/'target-provider-stop-unknown.png'),full_page=True)
        report['provider_stop']=dict(service='Status',observed_runtime='UNKNOWN',ui_fully_loaded=True,automatic_restart=False)
        operator('reconcile');assert sandbox_count()==0
        page.reload();select_session(ready,'A')
        page.wait_for_function("()=>document.querySelector('#edges').children.length===3 && document.querySelector('#running').textContent==='Остановлено'")
        assert 'Проверка не выполнялась' in page.locator('#checks').inner_text()
        page.screenshot(path=str(OUT/'target-ready-A.png'),full_page=True)
        browser.close()
    report.update(status='PASS',ready_session=ready,sandbox_after_stop=0,finished_epoch=time.time())
finally:
    remote('sudo -n systemctl start agent-graph-demo-observe.timer')
    (OUT/'target-final-ui-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print('TARGET_LOADED_UI_PASS')
