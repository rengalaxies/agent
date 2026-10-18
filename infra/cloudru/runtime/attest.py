"""Root controller only. No Docker authority is granted to web."""
import json,pathlib,subprocess,os
from datetime import datetime,timezone
root=pathlib.Path('/opt/agent-cloud-runtime')
p=subprocess.run(['docker','compose','-f',str(root/'compose.json'),'exec','-T','rabbitmq','rabbitmqctl','list_user_permissions','cloud_monitor','--formatter=json'],capture_output=True,text=True,timeout=30,check=True)
permission=next(x for x in json.loads(p.stdout) if x['vhost']=='/')
assert all(permission[k]=='^$' for k in ['configure','write','read'])
value={'username':'cloud_monitor',**permission,'broker_identity':'rabbit@rabbitmq','collected_at':datetime.now(timezone.utc).isoformat(),'source':'trusted CI rabbitmqctl list_user_permissions','issuer':'Cloud.ru root controller; legacy collector source enum retained','controller':'/opt/agent-cloud-runtime/runtime/attest.py'}
tmp=root/'attestation'/'permission.next';tmp.write_text(json.dumps(value));tmp.chmod(0o444);os.replace(tmp,root/'attestation'/'permission.json')
