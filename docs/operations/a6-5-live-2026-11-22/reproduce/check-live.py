import pathlib,json,sys,sqlite3,hashlib,subprocess,urllib.parse
release=pathlib.Path('/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312');state=pathlib.Path('/var/lib/impactmap-ui-kaiten');etc=pathlib.Path('/etc/impactmap-ui-kaiten')
sys.path[:0]=[str(release/'app/src'),str(release/'app')]
from tools.agent_service.box.config import read_secrets
from agent_service.connectors.kaiten import KaitenConnector
from agent_service.http import HttpClient
from agent_service.diagnostics import resource_diagnostics
cfg=json.loads((etc/'service.json').read_text());rid=next(iter(cfg['kaiten']['bindings']))
c=sqlite3.connect('file:'+str(state/'service/service.sqlite')+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
try:
 d=resource_diagnostics(c,rid);r=c.execute('SELECT snapshot FROM resources WHERE resource_id=?',(rid,)).fetchone();snapshot=json.loads(r[0]) if r else {}
 intents=[dict(x) for x in c.execute('SELECT generation,state,kind,operation,comment_id,body_digest FROM intents WHERE resource_id=? ORDER BY created_at DESC LIMIT 4',(rid,))]
 receipts=c.execute('SELECT count(*) FROM ui_scope_receipts').fetchone()[0]
finally:c.close()
values=read_secrets(etc/'secrets.env');api=KaitenConnector(HttpClient(cfg['kaiten']['base_url'],timeout=12),lambda:'Bearer '+values['IM_KAITEN_TOKEN'],board_ids=['1982649'],bot_id='1000388')
rows=api._list('74759475');owned=[(x,t) for x,t in rows if x.author=='1000388' and x.marker=='50f72df743af8977']
expected='https://82.202.141.50/ui/result?'+urllib.parse.urlencode({'resource_id':rid})
raw=(d.get('analysis') or {}).get('raw') or {}
result=dict(generation=d['resource']['generation'],job=d['current_job'],analysis={k:raw.get(k) for k in ('status','reason_code','code_version')},publication=d.get('publication'),head=snapshot.get('head_sha'),intents=intents,scope_receipts=receipts,owned_marker_count=len(owned),owned=[dict(id=x.comment_id,generation=x.generation,digest=x.digest,protected_link=expected in t,text_sha256=hashlib.sha256(t.encode()).hexdigest()) for x,t in owned],ui_link=expected,live_unit=subprocess.check_output(['systemctl','is-active','impactmap-ui-kaiten'],text=True).strip(),legacy_pid=subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True).strip())
print(json.dumps(result))
