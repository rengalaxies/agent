"""Target API boundaries, actual restarts, history and ready-state verification."""
import base64
import json
from pathlib import Path
import shlex
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import uuid

from target_ui import BASE, SSH, OUT, operator, phase, registry, remote, sandbox_count
from playwright.sync_api import sync_playwright

RESULT={}


def main():
    logins=json.loads(remote('sudo -n cat /etc/agent-graph-demo/private-test-logins.json'))
    credential=base64.b64encode(('operator:'+logins['operator']).encode()).decode()
    def request(path, body=None):
        headers={'Authorization':'Basic '+credential,'Origin':BASE,'Content-Type':'application/json'}
        req=Request(BASE+'/api/demo'+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
        try:
            with urlopen(req,timeout=15) as r:
                return r.status,json.load(r)
        except HTTPError as e:
            return e.code,json.load(e)
    def get(path):
        status,value=request(path)
        assert status==200,(path,status)
        return value
    def create():
        status,value=request('/sessions',{})
        assert status==201
        return value['id']
    def prepare(sid):
        session=get('/sessions/'+sid)
        status,job=request('/sessions/'+sid+'/jobs',dict(action='prepare_context',expected_revision=session['revision'],idempotency_key=str(uuid.uuid4()),payload={}))
        assert status==202,job
        wait=time.monotonic()+180
        while True:
            current=get('/jobs/'+job['id'])
            if current['status'] in ('PARTIAL','SUCCEEDED'):
                return current
            assert current['status'] not in ('FAILED','UNKNOWN_AFTER_RESTART','CANCELLED'),current
            assert time.monotonic()<wait
            time.sleep(.2)
    def ready():
        until=time.monotonic()+60
        while True:
            try:
                if request('/sessions')[0]==200:
                    return
            except (URLError,OSError):
                pass
            assert time.monotonic()<until,'backend did not recover'
            time.sleep(.5)

    report=RESULT
    report.update(scope='TARGET_VM_API_AND_SERVICE_RECOVERY',status='RUNNING',started_epoch=time.time())
    def save():
        (OUT/'target-extra-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    # Queue is genuinely blocked by the same installation workload lock used by operator.
    phase('queue_probe')
    sessions=[create() for _ in range(5)]
    lock_command="sudo -n flock -x /var/lib/agent-graph-demo/state/workload.lock sh -c 'echo LOCKED; sleep 12'"
    proc=subprocess.Popen([*SSH,lock_command],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    assert proc.stdout.readline().strip()=='LOCKED'
    jobs=[]
    try:
        codes=[]
        for sid in sessions:
            code,job=request('/sessions/'+sid+'/jobs',dict(action='prepare_context',expected_revision=1,idempotency_key=str(uuid.uuid4()),payload={}))
            codes.append(code)
            if code==202:
                jobs.append(job['id'])
        assert codes==[202,202,202,202,429],codes
        assert all(get('/jobs/'+j)['status']=='QUEUED' for j in jobs)
        report['queue']=dict(admissions=codes,queued_while_operator_lock_held=4)
        save()
    finally:
        proc.wait(timeout=20)
    peak_running=0
    until=time.monotonic()+180
    phase('analysis')
    while True:
        query="import sqlite3,json;c=sqlite3.connect('file:/var/lib/agent-graph-demo/state/web.sqlite?mode=ro',uri=True);ids="+repr(jobs)+"; rows=c.execute('SELECT doc FROM jobs WHERE id IN ('+','.join('?' for _ in ids)+')',ids).fetchall();print(json.dumps([json.loads(r[0])['status'] for r in rows]))"
        states=json.loads(remote('sudo -n docker exec agent-graph-demo-web-1 python -c '+shlex.quote(query)))
        assert len(states)==len(jobs)
        peak_running=max(peak_running,states.count('RUNNING'))
        assert states.count('RUNNING')<=1
        if all(s in ('SUCCEEDED','PARTIAL') for s in states):
            break
        assert not set(states)&{'FAILED','UNKNOWN_AFTER_RESTART','CANCELLED'},states
        assert time.monotonic()<until
        time.sleep(.1)
    report['queue'].update(observed_peak_running=peak_running,all_admitted_jobs_finished=True)
    intervals=sorted([get('/jobs/'+j) for j in jobs],key=lambda j:j['started_at'])
    assert all(a['finished_at']<=b['started_at'] for a,b in zip(intervals,intervals[1:]))
    report['queue'].update(atomic_snapshot_method='single readonly SELECT on web journal, not core store',
                          intervals=[{k:j[k] for k in ('id','started_at','finished_at')} for j in intervals],
                          no_overlapping_execution=True)
    save()

    original=json.loads((OUT/'target-report.json').read_text(encoding='utf-8'))['shows'][0]['session_id']
    source=get('/sessions/'+original)
    graph=get('/sessions/'+original+'/graph')
    code,body=request('/sessions/'+original+'/jobs',dict(action='investigate',expected_revision=source['revision'],idempotency_key=str(uuid.uuid4()),payload={'context_id':graph['context_id']}))
    assert code==503 and body['error']=='model_unavailable'
    code,_=request('/sessions/'+original+'/jobs',dict(action='prepare_context',expected_revision=source['revision'],idempotency_key=str(uuid.uuid4()),payload={'root':'/etc'}))
    assert code==422
    report['api_boundaries']=dict(model_disabled=503,arbitrary_path_rejected=422)
    save()

    probe="""
import json,os,shutil
from pathlib import Path
def readable(p):
 try: Path(p).read_bytes();return True
 except OSError:return False
status=Path('/proc/self/status').read_text()
v=dict(uid=os.getuid(),gid=os.getgid(),docker_socket=Path('/var/run/docker.sock').exists(),sudo_binary=shutil.which('sudo'),
       operator_config_readable=readable('/etc/demo/operator.json'),password_readable=readable('/etc/demo/operator-password'),
       cloud_env_names=[k for k in os.environ if any(x in k for x in ('CLOUDRU','AWS_','GH_TOKEN','GITHUB_TOKEN'))],
       state_writable=os.access('/var/lib/agent-graph-demo/state',os.W_OK),runtime_writable=os.access('/var/lib/agent-graph-demo/runtime',os.W_OK),
       core_writable=os.access('/core/src/agent_graph',os.W_OK),cap_eff=next(l.split()[1] for l in status.splitlines() if l.startswith('CapEff:')),
       no_new_privs=next(l.split()[1] for l in status.splitlines() if l.startswith('NoNewPrivs:')))
assert v['uid']==v['gid']==10001 and not v['docker_socket'] and v['sudo_binary'] is None
assert not v['operator_config_readable'] and not v['password_readable'] and not v['cloud_env_names']
assert v['state_writable'] and not v['runtime_writable'] and not v['core_writable']
assert int(v['cap_eff'],16)==0 and v['no_new_privs']=='1'
print(json.dumps(v))
"""
    report['web_privileges']=json.loads(remote('sudo -n docker exec agent-graph-demo-web-1 python -c '+shlex.quote(probe)))
    report['host_files']=remote("sudo -n stat -c '%a %u:%g %n' /etc/agent-graph-demo/auth.json /etc/agent-graph-demo/operator.json /etc/agent-graph-demo/release.env /var/lib/agent-graph-demo/state /var/lib/agent-graph-demo/runtime /var/lib/agent-graph-demo/runtime/active.json /var/lib/agent-graph-demo/state/web.sqlite")
    save()

    # Create a known A runtime, then restart real services, preserving all earlier history.
    sid=create();prepare(sid)
    phase('actual')
    receipt=operator('run',sid,'A')
    assert receipt['status']=='PASS' and sandbox_count()==2
    baseline=get('/sessions/'+original)
    before=dict(jobs=len(baseline['jobs']),checks=len(baseline['checks']),context=baseline['current_context_id'])
    phase('restart')
    remote('sudo -n systemctl restart agent-graph-demo.service')
    ready()
    after=get('/sessions/'+original)
    assert before==dict(jobs=len(after['jobs']),checks=len(after['checks']),context=after['current_context_id'])
    assert sandbox_count()==2
    report['backend_restart']=dict(status='PASS',history_before=before,history_after=before)
    save()
    # Refuse a daemon restart if an unexpected running container has appeared.
    projects=remote("sudo -n docker ps -q | xargs -r sudo -n docker inspect --format '{{index .Config.Labels \"com.docker.compose.project\"}}'").splitlines()
    assert all(p=='agent-graph-demo' or p.startswith('agent-graph-demo-sbx-') for p in projects),projects
    remote('sudo -n systemctl restart docker.service',timeout=180)
    ready()
    current=registry()
    if current['state']=='RUNNING':
        try:
            operator('observe')
        except (RuntimeError,AssertionError):
            pass
    assert registry()['state']=='UNKNOWN',registry()
    target=get('/sessions/'+sid)
    assert target['runtime']['state']=='UNKNOWN' and target['running_version'] is None
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        context=browser.new_context(viewport={'width':1440,'height':1100},http_credentials={'username':'operator','password':logins['operator']})
        page=context.new_page();page.goto(BASE)
        page.wait_for_function("()=>document.querySelector('#running').textContent==='Не подтверждено'")
        page.screenshot(path=str(OUT/'target-after-docker-unknown.png'),full_page=True)
        browser.close()
    assert before==dict(jobs=len(get('/sessions/'+original)['jobs']),checks=len(get('/sessions/'+original)['checks']),context=get('/sessions/'+original)['current_context_id'])
    operator('reconcile')
    assert sandbox_count()==0
    phase('actual')
    assert operator('run',sid,'A')['status']=='PASS'
    operator('stop',sid)
    assert sandbox_count()==0
    report['docker_restart']=dict(status='PASS',backend_automatically_recovered=True,
                                  sandbox_did_not_restart=True,runtime_after_restart='UNKNOWN',
                                  explicit_reconcile_and_rerun='PASS',history_preserved=True)
    # Ready state: fresh A, no runtime; historical shows are retained.
    old=get('/sessions/'+sid)
    code,fresh=request('/sessions/'+sid+'/reset',dict(expected_revision=old['revision'],idempotency_key=str(uuid.uuid4())))
    assert code==201
    prepare(fresh['id'])
    assert get('/sessions/'+fresh['id'])['scenario_version']=='A'
    assert get('/sessions/'+fresh['id'])['running_version'] is None
    phase('idle')
    remote('sudo -n systemctl start agent-graph-demo-observe.timer')
    report.update(status='PASS',finished_epoch=time.time(),ready_session=fresh['id'],
                  sandbox_after_stop=sandbox_count(),history_sessions=len(get('/sessions')),
                  observation_timer='enabled and active',whole_vm_reboot=False)
    (OUT/'target-extra-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('TARGET_EXTRA_ACCEPTANCE_PASS',flush=True)


if __name__=='__main__':
    try:
        main()
    except BaseException as exc:
        RESULT.update(status='FAIL',failure=type(exc).__name__,finished_epoch=time.time())
        (OUT/'target-extra-report.json').write_text(json.dumps(RESULT,ensure_ascii=False,indent=2),encoding='utf-8')
        raise
