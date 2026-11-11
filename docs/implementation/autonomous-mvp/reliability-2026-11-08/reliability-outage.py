import pathlib,json,subprocess,urllib.request,base64,time,socket
root=pathlib.Path('/var/lib/agent-bitbucket');e={k:json.loads(v) for k,v in (l.split('=',1) for l in pathlib.Path('/etc/agent-bitbucket/secrets.env').read_text().splitlines())}
def status():
 req=urllib.request.Request('http://127.0.0.1:8092/status',headers={'Authorization':'Bearer '+e['AGENT_SERVICE_STATUS_TOKEN']})
 with urllib.request.urlopen(req,timeout=5) as r:return json.load(r)
def wait(check,limit=100):
 start=time.monotonic()
 while time.monotonic()-start<limit:
  try:
   s=status()
   if check(s):return s
  except OSError:pass
  time.sleep(3)
 raise RuntimeError('outage observation timeout')
auth=base64.b64encode((e['JIRA_EMAIL']+':'+e['JIRA_API_TOKEN']).encode()).decode()
def comment():
 req=urllib.request.Request('https://api.atlassian.com/ex/jira/d0b47b8d-4655-4cb1-9f81-30573fd372c3/rest/api/3/issue/KAN-9/comment/10046',headers={'Authorization':'Basic '+auth})
 with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
sock=socket.socket();sock.settimeout(1);assert sock.connect_ex(('127.0.0.1',9))!=0;sock.close()
before=wait(lambda s:not s['notices']);before_comment=comment();oldpid=subprocess.check_output(['systemctl','show','agent-service','-p','MainPID','--value'],text=True).strip()
directory=pathlib.Path('/run/systemd/system/agent-bitbucket.service.d');directory.mkdir(parents=True,exist_ok=True);drop=directory/'90-reliability-proxy.conf';assert not drop.exists()
try:
 drop.write_text('[Service]\nEnvironment="HTTPS_PROXY=http://127.0.0.1:9" "HTTP_PROXY=http://127.0.0.1:9" "https_proxy=http://127.0.0.1:9" "http_proxy=http://127.0.0.1:9" "NO_PROXY=127.0.0.1,localhost" "no_proxy=127.0.0.1,localhost"\n')
 subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','agent-bitbucket'],check=True)
 failed=wait(lambda s:any(x['kind']=='reconcile_failed' for x in s['notices']))
 with urllib.request.urlopen('http://127.0.0.1:8092/healthz',timeout=5) as r:assert r.status==200
 assert comment()['body']==before_comment['body'];assert failed['jobs']==before['jobs'] and failed['intents']==before['intents']
 print('Controlled API transport outage detected; liveness200, existing Jira comment unchanged.',flush=True)
finally:
 drop.unlink(missing_ok=True);subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','restart','agent-bitbucket'],check=True)
after=wait(lambda s:not s['notices']);assert after['jobs']==before['jobs'] and after['intents']==before['intents'];assert comment()['body']==before_comment['body']
assert subprocess.check_output(['systemctl','show','agent-service','-p','MainPID','--value'],text=True).strip()==oldpid
report={'host':'dm-p1-ui','fault':'temporary unit-scoped unreachable loopback HTTPS proxy, not actual provider downtime','before':before,'during':failed,'after':after,'health_during':200,'comment_id':'10046','comment_body_unchanged':True,'manual_reconcile_calls':0,'fault_removed':not drop.exists(),'original_service_pid_unchanged':oldpid,'result':'PASS'}
(root/'live-acceptance/reliability-outage.json').write_text(json.dumps(report,indent=2)+'\n');print('Recovery PASS',flush=True)
