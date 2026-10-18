"""Fixed deployment, invoked as root with a private stdin configuration."""
import base64,hashlib,json,os,pathlib,secrets,shutil,socket,subprocess,sys,time
from datetime import datetime,timezone
P=pathlib.Path;cfg=json.load(sys.stdin);SOURCE='107dfd14292a5ab06593d424bf0b94f1cccb0b90';stage=P('/home/dmadmin/agent-lab-staging')/SOURCE/'checkout';root=P('/opt/agent-cloud-runtime');incoming=P(cfg['incoming'])
assert os.getuid()==0 and socket.gethostname()=='dm-p1-ui'
def run(args,timeout=180):
 p=subprocess.run(args,capture_output=True,text=True,timeout=timeout)
 if p.returncode:raise RuntimeError('STEP_FAILED:'+args[0]+':'+(args[1] if len(args)>1 else '')+':'+str(p.returncode))
 return p.stdout.strip()
assert run(['git','-C',str(stage),'rev-parse','HEAD'])==SOURCE
assert run(['git','-C',str(stage),'rev-parse','HEAD^{tree}'])=='540a48cc47d87d1656e744aa20ab996d6af7bca8'
assert not run(['git','-C',str(stage),'status','--porcelain'])
assert '45.151.31.140' in socket.gethostbyname_ex('45-151-31-140.sslip.io')[2]
assert not any(':'+str(port)+' ' in run(['ss','-lnt']) for port in [443]) or (root/'compose.json').exists(),'UNEXPECTED_443_OWNER'
root.mkdir(mode=0o700,exist_ok=True)
for name in ['runtime','state','attestation','proxy-data','proxy-config']:
 (root/name).mkdir(mode=0o700,exist_ok=True)
for name in ['state','attestation','proxy-data','proxy-config']:os.chown(root/name,10001,10001)
for name in ['cloud_server.py','Dockerfile','attest.py']:shutil.copyfile(incoming/name,root/'runtime'/name);os.chmod(root/'runtime'/name,0o644)
os.chmod(root/'runtime',0o755)
secretpath=root/'secrets.json'
if secretpath.exists():secret=json.loads(secretpath.read_text())
else:
 secret={k:secrets.token_hex(24) for k in ['PG_ADMIN_PASSWORD','ORDERS_PASSWORD','BILLING_PASSWORD','VERIFIER_PASSWORD','RABBIT_PASSWORD','MONITOR_PASSWORD','INTERNAL_PASSWORD']};secretpath.write_text(json.dumps(secret));secretpath.chmod(0o600)
image='agent-cloud-product:'+SOURCE
if subprocess.run(['docker','image','inspect',image],capture_output=True).returncode:
 run(['docker','build','--file',str(root/'runtime'/'Dockerfile'),'--tag',image,str(stage)],900)
base=json.loads(run(['python3','-c','import json; print(json.dumps({}))']))
pg='postgres@sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74';rb='rabbitmq@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69'
common={'restart':'unless-stopped','mem_limit':'384m','cpus':0.5,'pids_limit':200,'logging':{'driver':'json-file','options':{'max-size':'5m','max-file':'2'}},'networks':['private']}
services={'postgres':{**common,'image':pg,'environment':{'POSTGRES_PASSWORD':secret['PG_ADMIN_PASSWORD']},'volumes':['postgres-data:/var/lib/postgresql/data'],'healthcheck':{'test':['CMD-SHELL','pg_isready -U postgres'],'interval':'5s','timeout':'3s','retries':30}},'rabbitmq':{**common,'image':rb,'hostname':'rabbitmq','environment':{'RABBITMQ_DEFAULT_USER':'lab','RABBITMQ_DEFAULT_PASS':secret['RABBIT_PASSWORD'],'RABBITMQ_SERVER_ADDITIONAL_ERL_ARGS':'+S 1:1 +A 4'},'volumes':['rabbit-data:/var/lib/rabbitmq'],'healthcheck':{'test':['CMD','rabbitmq-diagnostics','-q','ping'],'interval':'10s','timeout':'5s','retries':30}}}
web_env={'LAB_REQUIRE_AUTH':'1','LAB_AUTH_USERNAME':'internal_proxy','LAB_AUTH_PASSWORD':secret['INTERNAL_PASSWORD'],'LAB_COOKIE_SECURE':'1','LAB_PRODUCT_DB':'/state/state.sqlite','LAB_ARTIFACT_ROOT':'/state/artifacts','LAB_REPO_ROOT':'/work','SOURCE_READ_DSN':'host=postgres dbname=lab_source user=lab_verifier password='+secret['VERIFIER_PASSWORD'],'RABBIT_READ_URL':'http://rabbitmq:15672','RABBIT_READ_USER':'cloud_monitor','RABBIT_READ_PASSWORD':secret['MONITOR_PASSWORD'],'RABBIT_PERMISSION_ATTESTATION_FILE':'/attestation/permission.json','LAB_ENABLE_ISOLATED_VERIFIER':'0'}
services['web']={**common,'image':image,'user':'10001:10001','mem_limit':'640m','cpus':0.75,'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'tmpfs':['/tmp:size=64m,noexec,nosuid,nodev'],'volumes':[str(root/'state')+':/state',str(root/'runtime')+':/runtime:ro',str(root/'attestation')+':/attestation:ro'],'environment':web_env,'command':['-m','uvicorn','cloud_server:app','--app-dir','/runtime','--host','0.0.0.0','--port','8088','--workers','1','--proxy-headers','--forwarded-allow-ips','*','--no-access-log'],'healthcheck':{'test':['CMD','python','-c',"import os,urllib.request,base64;r=urllib.request.Request('http://127.0.0.1:8088/api/lab/readyz',headers={'Authorization':'Basic '+base64.b64encode(('internal_proxy:'+os.environ['LAB_AUTH_PASSWORD']).encode()).decode()});urllib.request.urlopen(r,timeout=5)"],'interval':'15s','timeout':'8s','retries':4}}
# Caddy has no administrative API; only 443 is published, nginx on 80 is untouched.
proxy_image='caddy:2.10.2-alpine';run(['docker','pull',proxy_image],300);proxy_digest=json.loads(run(['docker','image','inspect',proxy_image]))[0]['RepoDigests'][0]
internal=base64.b64encode(('internal_proxy:'+secret['INTERNAL_PASSWORD']).encode()).decode()
caddy='''{\n admin off\n auto_https disable_redirects\n https_port 8443\n}\n45-151-31-140.sslip.io {\n tls {\n  issuer acme {\n   disable_http_challenge\n  }\n }\n basic_auth {\n  admin HASH\n  acceptance TESTHASH\n }\n reverse_proxy web:8088 {\n  header_up Authorization "Basic INTERNAL"\n }\n header {\n  Strict-Transport-Security "max-age=15552000"\n  X-Content-Type-Options nosniff\n  X-Frame-Options DENY\n }\n}\n'''.replace('TESTHASH',cfg['acceptance_hash']).replace('HASH',cfg['admin_hash']).replace('INTERNAL',internal)
(root/'Caddyfile').write_text(caddy);(root/'Caddyfile').chmod(0o600);os.chown(root/'Caddyfile',10001,10001)
services['proxy']={**common,'image':proxy_digest,'user':'10001:10001','mem_limit':'128m','cpus':0.25,'read_only':True,'cap_drop':['ALL'],'security_opt':['no-new-privileges:true'],'tmpfs':['/tmp:size=16m,nosuid,nodev'],'ports':['443:8443'],'networks':['private','edge'],'volumes':[str(root/'Caddyfile')+':/etc/caddy/Caddyfile:ro',str(root/'proxy-data')+':/data',str(root/'proxy-config')+':/config']}
compose={'name':'agent-cloud-runtime','services':services,'networks':{'private':{'internal':True},'edge':{}},'volumes':{'postgres-data':{},'rabbit-data':{}}}
(root/'compose.json').write_text(json.dumps(compose,indent=2));(root/'compose.json').chmod(0o600)
def dc(args,timeout=180):return run(['docker','compose','-f',str(root/'compose.json')]+args,timeout)
dc(['up','-d','--wait','--wait-timeout','180','postgres','rabbitmq'],300)
if not (root/'bootstrap.complete').exists():
 env={'ADMIN_DSN':'host=postgres dbname=postgres user=postgres password='+secret['PG_ADMIN_PASSWORD'],'SOURCE_DSN':'host=postgres dbname=lab_source user=lab_orders password='+secret['ORDERS_PASSWORD'],'BILLING_DSN':'host=postgres dbname=lab_billing user=lab_billing password='+secret['BILLING_PASSWORD'],'RABBITMQ_URL':'amqp://lab:'+secret['RABBIT_PASSWORD']+'@rabbitmq:5672/%2F',**{k:secret[k] for k in ['ORDERS_PASSWORD','BILLING_PASSWORD','VERIFIER_PASSWORD']}}
 efile=root/'bootstrap.env';efile.write_text('\n'.join(k+'='+v for k,v in env.items()));efile.chmod(0o600)
 run(['docker','run','--rm','--memory','256m','--cpus','0.5','--network','agent-cloud-runtime_private','--env-file',str(efile),image,'-m','lab.app.cli','bootstrap'],180);efile.unlink();(root/'bootstrap.complete').write_text(SOURCE)
 users=dc(['exec','-T','rabbitmq','rabbitmqctl','list_users','--formatter=json'])
 if 'cloud_monitor' not in users:dc(['exec','-T','rabbitmq','rabbitmqctl','add_user','cloud_monitor',secret['MONITOR_PASSWORD']])
 dc(['exec','-T','rabbitmq','rabbitmqctl','set_user_tags','cloud_monitor','monitoring']);dc(['exec','-T','rabbitmq','rabbitmqctl','set_permissions','-p','/','cloud_monitor','^$','^$','^$'])
def attest():
 permissions=json.loads(dc(['exec','-T','rabbitmq','rabbitmqctl','list_user_permissions','cloud_monitor','--formatter=json']));permission=next(p for p in permissions if p['vhost']=='/');assert all(permission[k]=='^$' for k in ['configure','write','read'])
 value={'username':'cloud_monitor',**permission,'broker_identity':'rabbit@rabbitmq','collected_at':datetime.now(timezone.utc).isoformat(),'source':'trusted CI rabbitmqctl list_user_permissions'}
 path=root/'attestation'/'permission.json';path.write_text(json.dumps(value));path.chmod(0o444)
attest()
P('/etc/systemd/system/agent-cloud-attest.service').write_text('[Unit]\nDescription=Read-only broker permission attestation\n[Service]\nType=oneshot\nExecStart=/usr/bin/python3 /opt/agent-cloud-runtime/runtime/attest.py\n')
P('/etc/systemd/system/agent-cloud-attest.timer').write_text('[Unit]\nDescription=Refresh broker attestation\n[Timer]\nOnBootSec=2min\nOnUnitActiveSec=5min\n[Install]\nWantedBy=timers.target\n')
run(['systemctl','daemon-reload']);run(['systemctl','enable','--now','agent-cloud-attest.timer'])
dc(['up','-d','--wait','--wait-timeout','120','web','proxy'],240)
report={'status':'RUNTIME_STARTED_TLS_PENDING','product_commit':SOURCE,'runtime_controller_commit':cfg['controller_commit'],'url':'https://45-151-31-140.sslip.io','proxy_image':proxy_digest,'containers':json.loads(dc(['ps','--format','json'])) if False else dc(['ps','--format','json']),'stats':run(['docker','stats','--no-stream','--format','{{json .}}']),'memory':run(['free','-b']),'apply_gate':'BLOCKED','llm_credentials_deployed':False,'docker_socket_exposed':False}
print(json.dumps(report))
