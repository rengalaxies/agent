import pathlib,json,subprocess,pwd,urllib.request,base64,time,hashlib,datetime
root=pathlib.Path('/var/lib/agent-bitbucket');cfg=json.loads(pathlib.Path('/etc/agent-bitbucket/service.json').read_text());assert cfg['publication']=='live';assert cfg['state_path'].endswith('live-acceptance/service/service.sqlite')
env={k:json.loads(v) for k,v in (line.split('=',1) for line in pathlib.Path('/etc/agent-bitbucket/secrets.env').read_text().splitlines())};u=pwd.getpwnam('agent-bitbucket');rid='bitbucket:e0b65402-98d3-432d-9ba0-8e92884d8bfb/ce63c558-64b3-462f-9ab9-1b954c14f5d9#2'
auth=base64.b64encode((env['JIRA_EMAIL']+':'+env['JIRA_API_TOKEN']).encode()).decode()
def api(product,path,method='GET',data=None):
 req=urllib.request.Request('https://api.atlassian.com/ex/'+product+'/d0b47b8d-4655-4cb1-9f81-30573fd372c3'+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as r:
  b=r.read();return json.loads(b) if b else {}
def snap():
 req=urllib.request.Request('http://127.0.0.1:8092/status',headers={'Authorization':'Bearer '+env['AGENT_SERVICE_STATUS_TOKEN']})
 with urllib.request.urlopen(req,timeout=10) as r:status=json.load(r)
 code='import sqlite3,sys,json;c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True);c.row_factory=sqlite3.Row;print(json.dumps({"resources":[dict(r) for r in c.execute("select resource_id,comment_id,generation,published_generation from resources")],"checkpoints":dict(c.execute("select name,value from checkpoints")),"failed_intents":[dict(r) for r in c.execute("select resource_id,state,reason from intents where state=\'FAILED\'")]}))'
 result=subprocess.run(['/usr/bin/python3','-c',code,cfg['state_path']],user=u.pw_uid,group=u.pw_gid,extra_groups=[],check=True,capture_output=True,text=True)
 return {'status':status,**json.loads(result.stdout),'loaded':json.loads((root/'run/loaded.json').read_text())}
def wait(predicate,timeout=150):
 deadline=time.monotonic()+timeout
 while time.monotonic()<deadline:
  try:
   s=snap()
   if predicate(s):return s
  except (OSError,ValueError):pass
  time.sleep(5)
 raise RuntimeError('persistent acceptance timeout')
def resource(s):return next(r for r in s['resources'] if r['resource_id']==rid)
def settled(s):
 return len(s['resources'])==3 and s['status']['jobs'].get('ANALYZED')==1 and not any(s['status']['jobs'].get(x,0) for x in ['RUNNING','QUEUED']) and s['failed_intents']==[{'resource_id':rid[:-1]+'3','state':'FAILED','reason':'exactly_one_linked_jira_required'}] and not s['status']['notices']
before=wait(settled)
assert resource(before)['comment_id']=='jira:10022|10011';assert before['loaded']['commit']=='c4053c6d4a959ff4d0e159c3cb1913fae87f25fb'
oldpid=subprocess.check_output(['systemctl','show','agent-service','-p','MainPID','--value'],text=True).strip()
comment_before=api('jira','/rest/api/3/issue/KAN-8/comment?maxResults=100');ids_before={x['id'] for x in comment_before['comments']}
report={'host':'dm-p1-ui','publication':'live','persistent_systemd_worker':True,'model':'OFF','before':before}
reportpath=root/'live-acceptance/persistent-report.json'
def save():reportpath.write_text(json.dumps(report,indent=2)+'\n')
save()
page=api('confluence','/wiki/api/v2/pages/360725?body-format=storage');marker='CF-PERSISTENT-LIVE-20261107';body=page['body']['storage']['value'];assert marker not in body,'acceptance already performed; inspect persisted report'
version=page['version']['number'];started=time.monotonic()
page=api('confluence','/wiki/api/v2/pages/360725','PUT',{'id':'360725','status':'current','title':page['title'],'body':{'representation':'storage','value':body+'<p>'+marker+': автоматическая проверка актуальности через постоянный worker.</p>'},'version':{'number':version+1,'message':'Persistent Cloud.ru polling acceptance'}})
after=wait(lambda s:resource(s)['generation']>resource(before)['generation'] and resource(s)['published_generation']==resource(s)['generation'] and settled(s),180)
comment=api('jira','/rest/api/3/issue/KAN-8/comment/10011');assert marker in json.dumps(comment['body'],ensure_ascii=False);assert resource(after)['comment_id']=='jira:10022|10011'
report.update(after_poll=after,page_before_version=version,page_after_version=page['version']['number'],poll_to_verified_comment_seconds=round(time.monotonic()-started,2),same_comment_id='10011',manual_reconcile_calls=0);save()
subprocess.run(['systemctl','restart','agent-bitbucket'],check=True)
restarted=wait(lambda s:s['loaded']['pid']!=after['loaded']['pid'] and float(s['checkpoints'].get('reconcile:bitbucket','0'))>float(after['checkpoints'].get('reconcile:bitbucket','0')) and settled(s),120)
assert restarted['resources']==after['resources'];assert restarted['status']==after['status'];assert not restarted['status']['notices']
comments=api('jira','/rest/api/3/issue/KAN-8/comment?maxResults=100');assert {x['id'] for x in comments['comments']}==ids_before
for r in restarted['resources']:
 if r['comment_id'] is None:
  assert r['resource_id']==rid[:-1]+'3'
  continue
 target,cid=r['comment_id'].split('|');native=api('jira','/rest/api/3/issue/'+target.split(':')[1]+'/comment/'+cid);assert native['id']==cid and native['author']['accountId']==cfg['jira']['bot_account_id']
assert subprocess.check_output(['systemctl','show','agent-service','-p','MainPID','--value'],text=True).strip()==oldpid
assert subprocess.check_output(['systemctl','is-enabled','agent-bitbucket'],text=True).strip()=='enabled'
report.update(result='PASS',after_restart=restarted,restart='PASS',same_comment_after_restart=True,new_kan8_comments=0,external_comments_readback='2/2 linked PRs PASS',unlinked_pr3_publication='EXPECTED_REJECTION: exactly_one_linked_jira_required',autostart_enabled=True,old_service_pid_unchanged=oldpid,reboot='NOT_RUN',production_restore='NOT_RUN');save();print(json.dumps(report,indent=2))
