import pathlib,json,subprocess,pwd,urllib.request,base64,time,copy
root=pathlib.Path('/var/lib/agent-bitbucket');cfg=json.loads(pathlib.Path('/etc/agent-bitbucket/service.json').read_text());u=pwd.getpwnam('agent-bitbucket');rid='bitbucket:e0b65402-98d3-432d-9ba0-8e92884d8bfb/ce63c558-64b3-462f-9ab9-1b954c14f5d9#4'
e={k:json.loads(v) for k,v in (l.split('=',1) for l in pathlib.Path('/etc/agent-bitbucket/secrets.env').read_text().splitlines())};auth=base64.b64encode((e['JIRA_EMAIL']+':'+e['JIRA_API_TOKEN']).encode()).decode()
def api(path,method='GET',data=None):
 req=urllib.request.Request('https://api.atlassian.com/ex/jira/d0b47b8d-4655-4cb1-9f81-30573fd372c3'+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as r:
  b=r.read();return json.loads(b) if b else {}
def resource():
 code='import sqlite3,json,sys;c=sqlite3.connect("file:"+sys.argv[1]+"?mode=ro",uri=True);c.row_factory=sqlite3.Row;print(json.dumps(dict(c.execute("select generation,published_generation,comment_id,snapshot from resources where resource_id=?",(sys.argv[2],)).fetchone())))'
 r=subprocess.run(['/usr/bin/python3','-c',code,cfg['state_path'],rid],user=u.pw_uid,group=u.pw_gid,extra_groups=[],check=True,capture_output=True,text=True);return json.loads(r.stdout)
original=api('/rest/api/3/issue/KAN-9?fields=description')['fields']['description'];backup=pathlib.Path('/var/backups/agent-bitbucket/reliability-20261108');backup.mkdir(mode=0o700,exist_ok=True)
p=backup/'KAN-9-description.json'
if p.exists():assert json.loads(p.read_text())==original,'prior test not restored; inspect backup'
else:p.write_text(json.dumps(original));p.chmod(0o600)
report={'host':'dm-p1-ui','manual_reconcile_calls':0,'same_comment':'10046','checks':[]};out=root/'live-acceptance/reliability-links.json'
def save():out.write_text(json.dumps(report,indent=2)+'\n')
def step(name,desc,check):
 before=resource();start=time.monotonic();api('/rest/api/3/issue/KAN-9','PUT',{'fields':{'description':desc}})
 for _ in range(36):
  r=resource()
  if r['generation']>before['generation'] and r['published_generation']==r['generation']:
   c=api('/rest/api/3/issue/KAN-9/comment/10046');text=json.dumps(c['body'],ensure_ascii=False)
   if check(text):break
  time.sleep(5)
 else:raise RuntimeError('poll verification timeout: '+name)
 assert r['comment_id']=='jira:10023|10046'
 report['checks'].append({'name':name,'result':'PASS','before_generation':before['generation'],'after_generation':r['generation'],'elapsed_seconds':round(time.monotonic()-start,2),'comment_updated':c['updated']});save();print(name+' PASS',flush=True)
removed=copy.deepcopy(original);removed['content']=[x for x in removed['content'] if '360725' not in json.dumps(x)]
assert '360725' not in json.dumps(removed)
missing=copy.deepcopy(removed);missing['content'].append({'type':'paragraph','content':[{'type':'text','text':'https://rengalaxies.atlassian.net/wiki/spaces/OOP/pages/9999999999'}]})
restored=False
try:
 step('explicit_link_removed',removed,lambda text:'Связанная документация Confluence' not in text and 'CF-PERSISTENT-LIVE' not in text)
 step('confluence_missing_page_no_cached_text',missing,lambda text:'Confluence UNAVAILABLE' in text and '9999999999' in text and 'CF-PERSISTENT-LIVE' not in text)
 step('original_link_restored',original,lambda text:'360725' in text and 'CF-PERSISTENT-LIVE-20261107' in text and 'Confluence UNAVAILABLE' not in text);restored=True
 comments=api('/rest/api/3/issue/KAN-9/comment?maxResults=100');assert comments['total']<=100
 ids=[c['id'] for c in comments['comments'] if 'marker=bbc3df769e4f04d5' in json.dumps(c['body'])];assert ids==['10046']
 report.update(result='PASS',jira_description_restored=True,service_comment_count=1);save()
finally:
 if not restored:api('/rest/api/3/issue/KAN-9','PUT',{'fields':{'description':original}})
