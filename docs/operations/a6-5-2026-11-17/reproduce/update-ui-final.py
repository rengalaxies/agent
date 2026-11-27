import json,pathlib,subprocess,sys,os,pwd,stat,secrets,time,types
root=pathlib.Path('/var/tmp/impactmap-a65-20261117/final');package=next((root/'release').iterdir())
sys.path[:0]=[str(package/'app/src'),str(package/'app')]
from tools.agent_service.box import bootstrap,release,layout,state as backups,config
installed=bootstrap.stage(package,pathlib.Path('/opt/impactmap-ui-pilot/releases'),release,layout)
state=pathlib.Path('/var/lib/impactmap-ui-pilot');etc=pathlib.Path('/etc/impactmap-ui-pilot');user=pwd.getpwnam('impactmap-ui')
old=json.loads((state/'run/loaded.json').read_text());unit=pathlib.Path('/etc/systemd/system/impactmap-ui-pilot.service')
# Only this new, isolated UI stops. The original worker is untouched.
subprocess.run(['systemctl','stop','impactmap-ui-pilot'],check=True)
# Protect operator config namespace via pinned descriptors before privileged writes.
dfd=os.open(etc,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
try:
 os.fchown(dfd,0,user.pw_gid);os.fchmod(dfd,0o750)
 for name in ('service.json','policy.json','seed-offline-pilot.py'):
  fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW,dir_fd=dfd)
  try:
   info=os.fstat(fd);assert stat.S_ISREG(info.st_mode) and info.st_nlink==1
   os.fchown(fd,0,user.pw_gid);os.fchmod(fd,0o640)
  finally:os.close(fd)
finally:os.close(dfd)
L=types.SimpleNamespace(state=state,backups=pathlib.Path('/var/backups/impactmap-ui-pilot'),config=etc/'service.json',bindings=lambda name:etc)
meta=backups.create(L,label='pre-ui-update',release=dict(name=old['release']))
cfg=json.loads((etc/'service.json').read_text());assert cfg['state_path']==str(state/'service/service.sqlite')
cfg['core']['constitution_path']=str(installed/'app/constitutions/agent-service-v1.yaml')
cfg['analysis']['code_version']=json.loads((installed/'manifest.json').read_text())['release_id']
config.write_bytes(etc/'service.json',(json.dumps(cfg,indent=2)+'\n').encode(),0o640);os.chown(etc/'service.json',0,user.pw_gid)
oldrelease='/opt/impactmap-ui-pilot/releases/'+old['release'];text=unit.read_text();assert oldrelease in text
unit.write_text(text.replace(oldrelease,str(installed)))
subprocess.run(['systemctl','daemon-reload'],check=True);subprocess.run(['systemctl','start','impactmap-ui-pilot'],check=True)
import urllib.request
for _ in range(30):
 try:
  req=urllib.request.Request('http://127.0.0.1:18092/ui/login',headers={'Host':'82.202.141.50'})
  with urllib.request.urlopen(req,timeout=2) as r:assert r.status==200
  break
 except OSError:time.sleep(.2)
else:raise RuntimeError('ui_readiness_failed')
print(json.dumps(dict(status='FINAL_UI_RELEASE_STARTED',commit=json.loads((state/'run/loaded.json').read_text())['commit'],backup=meta['name'],legacy_pid=subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True).strip(),configuration_owner='root:impactmap-ui',accounts='PRESERVED')))
