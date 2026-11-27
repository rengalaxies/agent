"""Ephemeral same-VM UI checks. Emits no passwords, cookies or CSRF values."""
import sys,pathlib,json,secrets,http.client,http.cookies,ssl,socket,urllib.parse
release=pathlib.Path(sys.argv[1]);phase=sys.argv[2];sys.path[:0]=[str(release/'app/src'),str(release/'app')]
from agent_service.config import ServiceConfig
from agent_service.ui_auth import AuthStore
from agent_service.ui_scope import scope_for_config
cfg=ServiceConfig.load('/etc/impactmap-ui-kaiten/service.json');scope=scope_for_config(cfg)
auth=AuthStore(pathlib.Path('/var/lib/impactmap-ui-kaiten/ui/auth.sqlite'),create=False)
username='qa-live-'+phase+'-'+secrets.token_hex(4);password=secrets.token_urlsafe(24);auth.create_user(username,password,'operator',scope.identity)
class TLS(http.client.HTTPSConnection):
 def connect(self):self.sock=ssl.create_default_context().wrap_socket(socket.create_connection(('127.0.0.1',443),timeout=8),server_hostname='82.202.141.50')
cookies={}
def request(method,path,data=None,headers=None):
 c=TLS('82.202.141.50',timeout=12) if phase=='public' else http.client.HTTPConnection('127.0.0.1',18093,timeout=12)
 h=dict(Host='82.202.141.50',Cookie='; '.join(k+'='+v for k,v in cookies.items()))
 if data is not None:h['Content-Type']='application/json';data=json.dumps(data)
 h.update(headers or {});c.request(method,path,body=data,headers=h);r=c.getresponse();raw=r.read()
 for k,v in r.getheaders():
  if k.lower()=='set-cookie':
   for name,value in http.cookies.SimpleCookie(v).items():cookies[name]=value.value
 status=r.status;c.close()
 try:body=json.loads(raw)
 except ValueError:body=None
 return status,body
try:
 assert request('GET','/ui/api/resources')[0]==401
 status,data=request('GET','/ui/api/csrf');assert status==200
 assert request('POST','/ui/api/login',dict(username=username,password=password),{'Origin':'https://82.202.141.50','X-CSRF-Token':data['csrf']})[0]==200
 status,me=request('GET','/ui/api/me');assert status==200 and me['installation_id']==cfg.installation_id and me['environment']=='acceptance'
 rid=next(iter(cfg.kaiten.bindings));status,result=request('GET','/ui/api/result?'+urllib.parse.urlencode({'resource_id':rid}));assert status==200 and result['analysis']['compatible']
 assert result['publication']['state']=='DELIVERED'
 assert request('GET','/ui/api/operations')[0]==200
 status,connections=request('GET','/ui/api/connections');assert status==200 and '1982649' in connections['result_html']
 if phase=='public':
  for path in ('/resources','/result','/status','/graph','/webhooks/bitbucket'):assert request('GET',path)[0]==404
 print(json.dumps(dict(status='PASS',phase=phase,scope=scope.identity,namespace=[me['installation_id'],me['environment']],resource=rid,analysis=result['analysis']['result']['status'],publication=result['publication']['state'],generation=result['resource']['generation'],public_api_isolated=phase=='public')))
finally:auth.change_user(username,disabled=True)
