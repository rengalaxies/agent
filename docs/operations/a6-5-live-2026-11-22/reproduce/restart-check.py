import pathlib,sys,json,subprocess,time,contextlib,io,hashlib,stat,sqlite3
etc=pathlib.Path('/etc/impactmap-ui-kaiten')
def probe():
 out=io.StringIO()
 with contextlib.redirect_stdout(out):exec(compile((etc/'check-live.py').read_text(),'check-live.py','exec'),{})
 return json.loads(out.getvalue())
before=probe()
assert before['generation']==9 and before['job']['state']=='DONE'
assert before['analysis']['status']=='ABSTAINED' and before['publication']['state']=='DELIVERED'
assert before['owned_marker_count']==1 and before['owned'][0]['protected_link']
oldpid=subprocess.check_output(['systemctl','show','impactmap-ui-kaiten','-p','MainPID','--value'],text=True).strip()
subprocess.run(['systemctl','restart','impactmap-ui-kaiten'],check=True,timeout=50)
newpid=subprocess.check_output(['systemctl','show','impactmap-ui-kaiten','-p','MainPID','--value'],text=True).strip()
assert oldpid!=newpid and newpid!='0'
time.sleep(5)
after=probe()
for key in ('generation','job','analysis','publication','head','intents','scope_receipts','owned_marker_count','owned'):
 assert before[key]==after[key],key
assert after['legacy_pid']=='60331'
secret=(etc/'secrets.env').stat();assert secret.st_uid==0 and stat.S_IMODE(secret.st_mode)==0o600
release=pathlib.Path('/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312');sys.path[:0]=[str(release/'app/src'),str(release/'app')]
from agent_service.config import ServiceConfig,build_bitbucket_reader
cfg=ServiceConfig.load('/etc/agent-bitbucket/service.json');pid=after['legacy_pid']
env=dict(x.split('=',1) for x in pathlib.Path(f'/proc/{pid}/environ').read_text().split('\0') if '=' in x)
reader=build_bitbucket_reader(cfg,env_secret=lambda n:env[n]);orders=reader.repository('agent-pilot-orders');reporting=reader.repository('agent-pilot-reporting')
pr4=reader.pull_request(orders,4);pr5=reader.pull_request(orders,5)
refs=dict(orders_main=reader.branch(orders),reporting_main=reader.branch(reporting),pr4_head=pr4.head_sha,pr4_state=pr4.state,pr5_head=pr5.head_sha,pr5_state=pr5.state)
assert refs['orders_main']=='5d405f22a0d919dd395fa02339c9170de20a89f7'
assert refs['reporting_main']=='6ebf07174eb9ef4018a98ccf14da1cb94b6a69e3'
assert refs['pr5_head']=='5759f4d415b3fa9c65ae4684cab9772d5ce88dd0' and refs['pr5_state']=='OPEN'
print(json.dumps(dict(status='RESTART_PRESERVES_DELIVERED_RESULT',before_pid=oldpid,after_pid=newpid,before=before,after=after,refs=refs,live_enabled=subprocess.check_output(['systemctl','is-enabled','impactmap-ui-kaiten'],text=True).strip(),secret_mode='0600',secret_uid=0,legacy_release=str(pathlib.Path('/opt/agent-bitbucket/current').resolve()),legacy_config_sha256=hashlib.sha256(pathlib.Path('/etc/agent-bitbucket/service.json').read_bytes()).hexdigest(),checked_at=time.time())))
