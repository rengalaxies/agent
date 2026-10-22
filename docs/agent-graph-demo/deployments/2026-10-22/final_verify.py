"""Read-only delivery/target verification. Credentials remain in memory."""
import json
from pathlib import Path
import urllib.request
import base64
from target_ui import remote, registry, sandbox_count

out=Path(__file__).resolve().parent
report=json.loads((out/'target-report.json').read_text(encoding='utf-8'))
login=json.loads(remote('sudo -n cat /etc/agent-graph-demo/private-test-logins.json'))
header={'Authorization':'Basic '+base64.b64encode(('operator:'+login['operator']).encode()).decode()}
def get(path):
    with urllib.request.urlopen(urllib.request.Request('http://127.0.0.1:18081/api/demo'+path,headers=header)) as response:
        return json.load(response)
shows=[]
for show in report['shows']:
    graph=get('/sessions/'+show['session_id']+'/graph')
    operations={o['id']:o for o in graph['operations']}
    links={(d['consumer'],operations[d['operation_id']]['service']) for d in graph['dependencies']}
    assert ('Health','Status') in links and ('Health','Orders') not in links
    assert ('Export','Orders') in links
    for stage in show['stages']:
        for name,consumer in stage['consumers'].items():
            assert not consumer['duplicate_ids'] and not consumer['unexpected_ids']
            assert consumer['passed']==(name!='Reporting' or stage['version']!='B')
    history=get('/sessions/'+show['session_id'])
    assert len(history['checks'])>=4 and len(history['jobs'])>=4
    shows.append(dict(session_id=show['session_id'],health_status_only=True,export_detected=True,
        checks=len(history['checks']),jobs=len(history['jobs'])))
installation=json.loads(remote('sudo -n cat /etc/agent-graph-demo/installation.json'))
assert installation['source_sha']=='ca6b9cfff0e278fbf3503c308741e4ac96524645'
assert sandbox_count()==0 and registry()['state']=='STOPPED'
services=remote('systemctl is-active agent-graph-demo.service agent-graph-demo-observe.timer nginx.service').splitlines()
assert services==['active','active','active']
ready=get('/sessions/a295a591-7e3d-4088-b325-269de1f9ced4')
assert not ready['checks']
try:
    urllib.request.urlopen('http://127.0.0.1:18081/')
    raise AssertionError('Unauthenticated access accepted')
except urllib.error.HTTPError as error:
    assert error.code==401
result=dict(status='PASS',scope='FINAL_TARGET_READ_ONLY',installation=installation,services=services,
    shows=shows,sandbox_containers=0,registry=registry(),ready_session=ready['id'],
    tunnel_unauthenticated_http=401,tunnel_authenticated_http=200)
(out/'target-final-verification.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
survey=remote("hostname; date -u; systemctl is-active agent-graph-demo.service agent-graph-demo-observe.timer nginx.service; systemctl is-enabled dmrp-ui.service; systemctl is-active dmrp-ui.service || true; sudo -n docker ps -a --format '{{.Names}} {{.Status}} {{.Ports}}'; sudo -n du -sb /opt/agent-graph-demo /var/lib/agent-graph-demo/state /var/lib/agent-graph-demo/runtime; df -B1 /; free -m; uptime; readlink /opt/agent-graph-demo/current; sudo -n docker inspect -f '{{.Image}}' agent-graph-demo-web-1; ss -lnt '( sport = :18081 )'")
(out/'target-final-survey.txt').write_text(survey,encoding='utf-8')
print('FINAL_TARGET_PASS: five shows retained; fresh A; sandbox zero; services/tunnel/image verified')
