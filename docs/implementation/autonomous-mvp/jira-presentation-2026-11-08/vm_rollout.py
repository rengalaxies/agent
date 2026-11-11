"""Explicit update of the existing Bitbucket worker; no generic GitHub box install."""
import tempfile, sqlite3
import argparse, datetime, hashlib, importlib.util, json, os, pathlib, pwd, shlex, shutil, subprocess, sys, tarfile, urllib.request
P=pathlib.Path
SHA='a02ffa7854dcc38cecc7fe5c5317466059926cd9'
NAME='agent-service-0.1.0-ga02ffa7854dc-linux-x86_64-cp312'
ARCHIVE='050e03668023a138d0500affa9359b4395ed3ac5595cb1edbde342e84eb267a3'
MANIFEST='6fcf7e1303185ae1f009f16b15cbaf6cf8a4fa403bbb91bdbe48b5fd35f9f0ba'
WORK=P('/var/tmp/agent-summary-a02'); CURRENT=P('/opt/agent-bitbucket/current'); CFG=P('/etc/agent-bitbucket/service.json'); UNIT='agent-bitbucket.service'
def call(*args): return subprocess.check_output(args,text=True).strip()
def manifest(p): return json.loads((p/'manifest.json').read_text())
def env():
 e={'PATH':'/usr/bin:/bin','HOME':'/var/lib/agent-bitbucket','TMPDIR':'/var/lib/agent-bitbucket/tmp'}
 for line in P('/etc/agent-bitbucket/secrets.env').read_text().splitlines():
  if line and not line.startswith('#'):
   k,v=line.split('=',1);e[k]=shlex.split(v)[0]
 return e
def usercode(code):
 u=pwd.getpwnam('agent-bitbucket');assert u.pw_uid!=0
 return subprocess.check_output([str(CURRENT/'venv/bin/python'),'-I','-B','-c',code],user=u.pw_uid,group=u.pw_gid,extra_groups=[],env=env(),text=True).strip()
def stage():
 assert os.geteuid()==0 and call('hostname')=='dm-p1-ui'
 WORK.mkdir(mode=0o700,exist_ok=True)
 a=WORK/'release.tar.gz'
 if not a.exists(): urllib.request.urlretrieve('https://github.com/rengalaxies/agent/releases/download/agent-service-0.1.0-ga02ffa7854dc/'+NAME+'.tar.gz',a)
 assert hashlib.sha256(a.read_bytes()).hexdigest()==ARCHIVE
 source=WORK/NAME
 if not source.exists():
  with tarfile.open(a) as t:t.extractall(WORK,filter='data')
 assert hashlib.sha256((source/'manifest.json').read_bytes()).hexdigest()==MANIFEST
 m=manifest(source);old=manifest(CURRENT)
 assert m['code']['commit']==SHA
 for key in ['core','state','recovery']:assert m['contracts'][key]==old['contracts'][key],key
 spec=importlib.util.spec_from_file_location('summary_bootstrap',source/'app/tools/agent_service/box/bootstrap.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
 r=b._module('release',source);l=b._module('layout',source);r.verify_tree(source)
 final=b.stage(source,P('/opt/agent-bitbucket/releases'),r,l)
 result={'stage':'PASS','new_release':str(final),'old_release':str(CURRENT.resolve()),'sha':SHA,'matching_state_core_recovery':True,'worker_changed':False}
 (WORK/'stage.json').write_text(json.dumps(result));print(json.dumps(result))
def activate():
 plan=json.loads((WORK/'stage.json').read_text());assert str(CURRENT.resolve())==plan['old_release']
 assert call('systemctl','is-active',UNIT)=='active'
 oldconfig=CFG.read_bytes();meta=CFG.stat();oldtarget=CURRENT.resolve()
 subprocess.run(['systemctl','stop',UNIT],check=True)
 dest=P('/var/backups/agent-bitbucket')/('summary-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'));dest.mkdir(parents=True,mode=0o700);dest.parent.chmod(0o700)
 started=False
 try:
  a=dest/'snapshot.tar.gz'
  with tarfile.open(a,'x:gz') as t:
   for n in ['etc/agent-bitbucket','var/lib/agent-bitbucket','etc/systemd/system/agent-bitbucket.service']:t.add('/'+n,arcname=n)
  a.chmod(0o600)
  with tempfile.TemporaryDirectory(prefix='summary-backup-check-') as scratch:
   with tarfile.open(a) as t:t.extractall(scratch,filter='data')
   checked=0;dbs=[]
   for root in ['etc/agent-bitbucket','var/lib/agent-bitbucket','etc/systemd/system/agent-bitbucket.service']:
    origin=P('/'+root)
    for f in (origin.rglob('*') if origin.is_dir() else [origin]):
     if f.is_file() and not f.is_symlink():
      restored=P(scratch)/f.relative_to('/')
      assert hashlib.sha256(f.read_bytes()).digest()==hashlib.sha256(restored.read_bytes()).digest()
      checked+=1
      if f.suffix in ('.sqlite','.sqlite3'):
       with sqlite3.connect(restored) as db:assert db.execute('pragma integrity_check').fetchone()[0]=='ok'
       dbs.append(str(f))
   active=json.loads(oldconfig)
   expected={active['state_path'],str(P(active['core']['state_dir'])/'graph.sqlite3')}
   assert expected.issubset(set(dbs)),(expected,dbs)
  (dest/'previous-release.txt').write_text(str(oldtarget)+'\n')
  backup={'archive':str(a),'sha256':hashlib.sha256(a.read_bytes()).hexdigest(),'previous_release':str(oldtarget),'scratch_restore':'PASS','verified_files':checked,'databases':dbs}
  (dest/'verification.json').write_text(json.dumps(backup));(dest/'verification.json').chmod(0o600)
  c=json.loads(oldconfig);assert c['publication']=='live';c['jira']['comment_format']='summary_ru';c['analysis']['code_version']=manifest(P(plan['new_release']))['release_id']
  tmp=CFG.with_suffix('.new');tmp.write_text(json.dumps(c,indent=2)+'\n');os.chown(tmp,meta.st_uid,meta.st_gid);tmp.chmod(meta.st_mode & 0o777);os.replace(tmp,CFG)
  link=CURRENT.with_name('current.summary-next');link.symlink_to(plan['new_release']);os.replace(link,CURRENT)
  code="import sys;sys.path[:0]=['/opt/agent-bitbucket/current/app/src','/opt/agent-bitbucket/current/app'];from agent_service.config import ServiceConfig;c=ServiceConfig.load('/etc/agent-bitbucket/service.json');assert c.jira.comment_format=='summary_ru';assert c.core.model_qualification is None;print('CONFIG_MODEL_OFF_PASS')"
  assert usercode(code)=='CONFIG_MODEL_OFF_PASS'
  code="import sys,json;from pathlib import Path;sys.path[:0]=['/opt/agent-bitbucket/current/app/src','/opt/agent-bitbucket/current/app'];from agent_service.config import ServiceConfig;from agent_service.queue import ServiceStore;c=ServiceConfig.load('/etc/agent-bitbucket/service.json');s=ServiceStore(Path(c.state_path));print(s.reopen_open_resources(reason='jira_presentation_changed',event_id='presentation:a02ffa7854dc:summary_ru',providers={'bitbucket'}))"
  reopened=int(usercode(code))
  subprocess.run(['systemctl','start',UNIT],check=True);started=True
  result={'activated':True,'sha':SHA,'backup':backup,'resources_reopened':reopened,'format':'summary_ru'};(WORK/'activation.json').write_text(json.dumps(result));print(json.dumps(result))
 except BaseException:
  if not started:
   CFG.write_bytes(oldconfig);os.chown(CFG,meta.st_uid,meta.st_gid);CFG.chmod(meta.st_mode & 0o777)
   link=CURRENT.with_name('current.summary-rollback');link.symlink_to(oldtarget);os.replace(link,CURRENT)
   subprocess.run(['systemctl','start',UNIT],check=True)
  raise

def probe():
 loaded=json.loads(P('/var/lib/agent-bitbucket/run/loaded.json').read_text());pid=int(call('systemctl','show',UNIT,'-p','MainPID','--value'));assert loaded['pid']==pid and loaded['commit']==SHA
 e=env();req=urllib.request.Request('http://127.0.0.1:8092/status',headers={'Authorization':'Bearer '+e['AGENT_SERVICE_STATUS_TOKEN']})
 with urllib.request.urlopen(req,timeout=10) as r: status=json.load(r)
 u=pwd.getpwnam('agent-bitbucket');assert int(P('/proc/'+str(pid)+'/status').read_text().split('Uid:')[1].split()[0])==u.pw_uid
 result={'loaded':loaded,'status':status,'uid':u.pw_uid,'autostart':call('systemctl','is-enabled',UNIT),'units':{n:call('systemctl','is-active',n) for n in [UNIT,'agent-service','nginx','docker']}}
 (WORK/'probe.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','activate','probe']);a=p.parse_args();globals()[a.action]()
