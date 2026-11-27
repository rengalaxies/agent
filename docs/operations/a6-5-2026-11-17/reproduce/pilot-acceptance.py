import json,pathlib,subprocess,sys,os,socket,ssl,time,http.client,http.cookies,hashlib,sqlite3,types
state=pathlib.Path('/var/lib/impactmap-ui-pilot');etc=pathlib.Path('/etc/impactmap-ui-pilot');root=pathlib.Path('/var/tmp/impactmap-a65-20261117')
release=next(pathlib.Path('/opt/impactmap-ui-pilot/releases').iterdir());sys.path[:0]=[str(release/'app/src'),str(release/'app')]
from tools.agent_service.box import state as backups
from tools.agent_service.box.layout import Layout
from agent_service.ui_auth import AuthStore,UIError
access=json.loads((state/'ui/initial-access.json').read_text())
class TLS(http.client.HTTPSConnection):
 def connect(self):
  self.sock=ssl.create_default_context().wrap_socket(socket.create_connection(('127.0.0.1',443),timeout=8),server_hostname='82.202.141.50')
class Browser:
 def __init__(self):self.cookies={};self.flags=[]
 def request(self,method,path,data=None,headers=None):
  c=TLS('82.202.141.50',timeout=10)
  h=dict(Host='82.202.141.50',Cookie='; '.join(k+'='+v for k,v in self.cookies.items()))
  if data is not None:h['Content-Type']='application/json';data=json.dumps(data)
  h.update(headers or {});c.request(method,path,body=data,headers=h);r=c.getresponse();raw=r.read()
  for k,v in r.getheaders():
   if k.lower()=='set-cookie':
    jar=http.cookies.SimpleCookie(v)
    for name,item in jar.items():
     self.cookies[name]=item.value
     if name=='__Host-impactmap_session' and item.value:self.flags.append(all(x in v for x in ('Secure','HttpOnly','SameSite=strict')))
  status,location=r.status,r.getheader('location');c.close()
  try:body=json.loads(raw)
  except ValueError:body=None
  return status,body,location
 def login(self,name):
  code,data,_=self.request('GET','/ui/api/csrf');assert code==200
  code,_,_=self.request('POST','/ui/api/login',dict(username=name,password=access[name]['password']),{'Origin':'https://82.202.141.50','X-CSRF-Token':data['csrf']});assert code==200
report=dict(profile='ISOLATED_OFFLINE_UI_NOT_LIVE',checks={})
a=Browser();assert a.request('GET','/ui/api/resources')[0]==401
for path in ('/status','/resources','/webhooks/github','/graph'):
 assert a.request('GET',path)[0]==404
report['checks']['public_api_allowlist']=True
anon=a.request('GET','/ui/result?resource_id=bitbucket%3Aoffline-pilot%2Forders%235-change')
assert anon[0]==303 and anon[2].startswith('/ui/login?next=')
report['checks']['anonymous_deep_link_redirect']=True
a.login('qa-operator');assert a.flags==[True]
code,data,_=a.request('GET','/ui/api/me');assert code==200 and data['role']=='operator'
code,data,_=a.request('GET','/ui/api/resources');assert code==200
report['checks']['operator_results']=len(data['items'])
assert len(data['items'])==2
for path in ('/ui/api/operations','/ui/api/connections'):assert a.request('GET',path)[0]==200
b=Browser();b.login('qa-reviewer')
for path in ('/ui/api/operations','/ui/api/connections'):assert b.request('GET',path)[0]==403
report['checks']['reviewer_operator403']=True
report['checks']['secure_cookie_flags']=True
pid_before=subprocess.check_output(['systemctl','show','impactmap-ui-pilot','-p','MainPID','--value'],text=True).strip()
subprocess.run(['systemctl','restart','impactmap-ui-pilot'],check=True)
for _ in range(30):
 try:
  if a.request('GET','/ui/api/me')[0]==200:break
 except OSError:pass
 time.sleep(.2)
else:raise RuntimeError('ui_restart_failed')
pid_after=subprocess.check_output(['systemctl','show','impactmap-ui-pilot','-p','MainPID','--value'],text=True).strip();assert pid_before!=pid_after
report['checks']['restart_persisted_session']=dict(before=pid_before,after=pid_after)
layout=types.SimpleNamespace(state=state,backups=pathlib.Path('/var/backups/impactmap-ui-pilot'),config=etc/'service.json',bindings=lambda name:etc)
meta=backups.create(layout,label='a65-pilot',release=dict(name=release.name))
assert 'state/ui/auth.sqlite' in meta['files'];backups.verify(layout,meta['name'])
scratch=Layout.at(root/'restore-check');scratch.backups.mkdir(parents=True,exist_ok=True)
import shutil
shutil.copytree(layout.backups/meta['name'],scratch.backups/meta['name'])
scratch.state.mkdir(parents=True,exist_ok=True)
backups.restore(scratch,meta['name'])
assert backups.counts(scratch.state)==meta['counts']
restored=AuthStore(scratch.state/'ui/auth.sqlite',create=False)
with restored.transaction() as c:
 assert c.execute('SELECT count(*) FROM users WHERE disabled=0').fetchone()[0]==0
 assert c.execute('SELECT count(*) FROM sessions').fetchone()[0]==0
 assert c.execute('SELECT count(*) FROM challenges').fetchone()[0]==0
report['checks']['verified_backup_scratch_restore']=dict(name=meta['name'],counts=meta['counts'],files=list(meta['files']),restored_accounts_disabled=True)
report['checks']['legacy_worker']=dict(pid=subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True).strip(),release=subprocess.check_output(['readlink','-f','/opt/agent-bitbucket/current'],text=True).strip())
report['loaded']=json.loads((state/'run/loaded.json').read_text())
report['status']='PASS'
(root/'pilot-acceptance.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report))
