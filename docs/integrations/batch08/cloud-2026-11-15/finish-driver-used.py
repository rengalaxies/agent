import importlib.util,json
s=importlib.util.spec_from_file_location('c','/tmp/impactmap08-cloud-control.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=json.loads((m.PRIVATE/'session.json').read_text());code='ROOT_PATH='+repr(r['root'])+'\n'+m.PRELUDE+r'''
import fcntl,hashlib
from datetime import datetime,timezone
lock=(root/'acceptance.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
last=json.loads((root/'receipts/returned-primary.json').read_text());assert last['status']=='PASS' and last['target_card_id']=='74759475' and last['comment_id'].endswith(',"93817019"]') and not last['reconcile_errors']
ready=json.loads((root/'fault-ready.json').read_text());killed=json.loads((root/'fault-killed.json').read_text());recovered=json.loads((root/'receipts/change-recovered.json').read_text())
errors=recovery_errors(ready,killed,recovered);assert not errors
proof={'status':'PASS','errors':errors,'before_pid':ready['pid'],'after_pid':recovered['pid'],'same_comment_id':ready['comment_id'],'same_database':True,'recovered_sending':recovered['recovered']['sending'],'recovery_wrote':False}
(root/'recovery-proof.json').write_text(json.dumps(proof))
before=json.loads((root/'installed-before.json').read_text());loaded=json.loads(Path('/var/lib/agent-bitbucket/run/loaded.json').read_text());pid=int(subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True))
now={'installed_commit':loaded['commit'],'installed_pid':pid,'installed_service_config_sha256':hashlib.sha256(Path('/etc/agent-bitbucket/service.json').read_bytes()).hexdigest()}
post={'same_installed_runtime':now==before,'before':before,'after':now,'active':subprocess.check_output(['systemctl','is-active','agent-bitbucket'],text=True).strip()};assert post['same_installed_runtime'] and post['active']=='active'
(root/'postflight.json').write_text(json.dumps(post))
secret=root/'secrets.json';assert secret.parent.resolve()==root.resolve() and not secret.is_symlink() and secret.stat().st_mode&0o777==0o600
secret.unlink();fd=os.open(root,os.O_RDONLY);os.fsync(fd);os.close(fd)
cleanup={'status':'PASS','observed_utc':datetime.now(timezone.utc).isoformat(),'test_secrets_file_removed':not secret.exists(),'acceptance_lock_held':True,'production_credential_files_touched':False,'local_original_token_preserved':True}
(root/'cleanup.json').write_text(json.dumps(cleanup));print(json.dumps({'cleanup':cleanup,'postflight':post,'recovery':proof}))
'''
print(json.dumps(m.remote(code,timeout=60)))
