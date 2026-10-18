"""Deploy fixed private runtime, test external TLS, revoke temporary acceptance identity."""
import importlib.util,json,os,secrets,time,sys
from pathlib import Path
from runtime_scoped import connect
from scoped_ssh import main,GROUP

def execute(client,command,data=None,timeout=1200):
 stdin,stdout,stderr=client.exec_command(command,timeout=timeout)
 if data is not None:stdin.write(data)
 stdin.channel.shutdown_write();raw=stdout.read(250000);err=stderr.read(16000);status=stdout.channel.recv_exit_status()
 if status:
  # Retain only fixed exception categories, never command output or credentials.
  safe=[x for x in err.decode(errors='replace').splitlines() if x.startswith(('RuntimeError: STEP_FAILED:','AssertionError: UNEXPECTED_443_OWNER'))]
  Path('cloud-evidence').mkdir(exist_ok=True);Path('cloud-evidence/remote-step-error.txt').write_text('\n'.join(safe)+'\n')
  raise ValueError('RULE_RUNTIME_REMOTE_STEP_FAILED_'+str(status)+'_'+__import__('hashlib').sha256(err).hexdigest()[:12])
 return raw.decode()

def deploy(tf,env,selected,resources):
 import bcrypt,requests,httpx
 auth=requests.post('https://iam.api.cloud.ru/api/v1/auth/token',json={'keyId':env['CLOUDRU_KEY_ID'],'secret':env['CLOUDRU_SECRET']},timeout=25);auth.raise_for_status()
 r=requests.get('https://compute.api.cloud.ru/api/v1/security-groups/'+GROUP+'/rules',headers={'Authorization':'Bearer '+auth.json()['access_token']},timeout=25);r.raise_for_status();d=r.json();rules=d['items'];assert len(rules)==d['total']
 if any(x.get('direction')=='ingress' and x.get('remote_ip_prefix')=='0.0.0.0/0' and (x.get('ip_protocol')=='any' or x.get('port_range')=='22:22') for x in rules):raise ValueError('RULE_BROAD_ADMIN_ACCESS')
 password=secrets.token_hex(24);print('::add-mask::'+password)
 report={'outcome':'FAIL','controller_commit':os.environ['GITHUB_SHA'],'product_commit':'107dfd14292a5ab06593d424bf0b94f1cccb0b90','actions_run':'https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],'apply_gate':'BLOCKED','broad_admin_absent':True}
 out=Path('cloud-evidence');out.mkdir(exist_ok=True)
 with connect(env,selected) as client:
  # Survey again only because the previous runner could not establish TCP; no source redelivery.
  survey=json.loads(execute(client,'python3 -',Path('infra/cloudru/lab/runtime_survey.py').read_text(),120));(out/'survey.json').write_text(json.dumps(survey,indent=2))
  if survey['observed_source']+'/32'!=env['TF_VAR_lab_runner_cidr']:raise ValueError('RULE_SERVER_SOURCE_MISMATCH')
  incoming='/home/dmadmin/agent-runtime-upload-'+os.environ['GITHUB_RUN_ID']
  with client.open_sftp() as sftp:
   try:sftp.mkdir(incoming,0o700)
   except IOError:raise ValueError('RULE_PRIOR_UPLOAD_DIRECTORY_EXISTS')
   for name in ['cloud_server.py','Dockerfile','deploy_guest.py','attest.py']:
    sftp.put('infra/cloudru/runtime/'+name,incoming+'/'+name);sftp.chmod(incoming+'/'+name,0o600)
  cfg={'incoming':incoming,'admin_hash':env['CLOUDRU_UI_BASIC_AUTH_HASH'].strip(),'acceptance_hash':bcrypt.hashpw(password.encode(),bcrypt.gensalt()).decode(),'controller_commit':os.environ['GITHUB_SHA']}
  try:
   report['deployment']=json.loads(execute(client,'sudo -n python3 '+incoming+'/deploy_guest.py',json.dumps(cfg),1500))
   for _ in range(60):
    try:
     r=httpx.get('https://45-151-31-140.sslip.io/api/lab/readyz',auth=('acceptance',password),timeout=10)
     if r.status_code==200:break
    except httpx.HTTPError:pass
    time.sleep(3)
   else:raise ValueError('RULE_TRUSTED_HTTPS_NOT_READY')
   spec=importlib.util.spec_from_file_location('cloud_acceptance','infra/cloudru/runtime/acceptance.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
   def restart():execute(client,"sudo -n docker compose -f /opt/agent-cloud-runtime/compose.json restart web",timeout=90)
   report['acceptance']=module.run(password,out,restart)
   measurement='''import json,pathlib,subprocess
p=subprocess.run(['docker','compose','-f','/opt/agent-cloud-runtime/compose.json','ps','-q'],capture_output=True,text=True,check=True)
r=[]
for identity in p.stdout.split():
 d=json.loads(subprocess.check_output(['docker','inspect',identity]))[0];pid=d['State']['Pid'];cg=pathlib.Path('/sys/fs/cgroup')/pathlib.Path('/proc/'+str(pid)+'/cgroup').read_text().strip().split('::',1)[1].lstrip('/')
 r.append({'name':d['Name'],'oom_killed':d['State']['OOMKilled'],'restart_count':d['RestartCount'],'user':d['Config']['User'],'memory_limit':d['HostConfig']['Memory'],'nano_cpus':d['HostConfig']['NanoCpus'],'ports':d['HostConfig']['PortBindings'],'mounts':[x['Destination'] for x in d['Mounts']],'memory_peak':int((cg/'memory.peak').read_text()),'memory_events':(cg/'memory.events').read_text()})
print(json.dumps({'containers':r,'free':subprocess.check_output(['free','-b'],text=True),'disk':subprocess.check_output(['df','-B1','/'],text=True)}))'''
   report['resources']=json.loads(execute(client,'sudo -n python3 -',measurement))
   for row in report['resources']['containers']:
    assert not row['oom_killed'] and 'oom_kill 0' in row['memory_events'] and row['memory_peak']<row['memory_limit']
    assert '/var/run/docker.sock' not in row['mounts']
   report['outcome']='PASS'
  finally:
   # No reusable CI login is left on the public origin, including after failure.
   revoke='''import pathlib,subprocess,json
p=pathlib.Path('/opt/agent-cloud-runtime/Caddyfile')
if p.exists():
 s=p.read_text();p.write_text('\\n'.join(x for x in s.split('\\n') if not x.strip().startswith('acceptance ')));subprocess.run(['docker','compose','-f','/opt/agent-cloud-runtime/compose.json','restart','proxy'],capture_output=True,check=True,timeout=90)
print(json.dumps({'temporary_acceptance_identity':'REMOVED'}))'''
   report['credential_cleanup']=json.loads(execute(client,'sudo -n python3 -',revoke,120));(out/'deployment.json').write_text(json.dumps(report,indent=2)+'\n')
 return {'action':'CLOUD_RUNTIME_DEPLOYMENT','outcome':report['outcome'],'temporary_test_identity':'REMOVED','execution_permission':False}
if __name__=='__main__':raise SystemExit(main(deploy))
