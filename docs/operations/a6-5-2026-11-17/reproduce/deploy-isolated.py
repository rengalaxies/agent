import json,pathlib,subprocess,sys,os,shutil,pwd
root=pathlib.Path('/var/tmp/impactmap-a65-20261117');package=next((root/'release').iterdir())
sys.path[:0]=[str(package/'app/src'),str(package/'app')]
from tools.agent_service.box import bootstrap,release,layout
installed=bootstrap.stage(package,pathlib.Path('/opt/impactmap-ui-pilot/releases'),release,layout)
try:user=pwd.getpwnam('impactmap-ui')
except KeyError:
 subprocess.run(['useradd','--system','--user-group','--no-create-home','--shell','/usr/sbin/nologin','impactmap-ui'],check=True);user=pwd.getpwnam('impactmap-ui')
state=pathlib.Path('/var/lib/impactmap-ui-pilot');etc=pathlib.Path('/etc/impactmap-ui-pilot')
assert not state.exists() and not etc.exists(), 'isolated_state_already_exists'
state.mkdir(mode=0o750);etc.mkdir(mode=0o750)
for d in ('service','core','mirrors','run','ui','tmp','dry-run'):(state/d).mkdir(mode=0o700)
old=pathlib.Path('/var/tmp/impactmap-kaiten-cloud-20261115-a59cd9f8')
policy=json.loads((old/'policy.json').read_text());policy.update(installation_id='impactmap-ui-pilot',environment='offline-pins-20261115',subject='Saved author-pilot pins; no live tracker or source API')
for repo in policy['repositories']:
 dest=state/'mirrors'/pathlib.Path(repo['root']).name;shutil.copytree(repo['root'],dest)
 (dest/'config').write_text('[core]\nrepositoryformatversion = 0\nbare = true\n')
 repo['root']=str(dest)
(etc/'policy.json').write_text(json.dumps(policy,indent=2)+'\n')
cfg=dict(installation_id=policy['installation_id'],environment=policy['environment'],
 state_path=str(state/'service/service.sqlite'),publication='dry_run',dry_run_dir=str(state/'dry-run'),
 ui_config_path=str(state/'ui/ui.json'),analysis={'code_version':json.loads((installed/'manifest.json').read_text())['release_id']},
 core=dict(policy_path=str(etc/'policy.json'),state_dir=str(state/'core'),constitution_path=str(installed/'app/constitutions/agent-service-v1.yaml')))
(etc/'service.json').write_text(json.dumps(cfg,indent=2)+'\n')
(state/'ui/ui.json').write_text(json.dumps(dict(database=str(state/'ui/auth.sqlite'),origin='https://82.202.141.50'))+'\n')
for base in (state,etc):
 for d,ds,fs in os.walk(base):
  os.chown(d,0 if base==etc else user.pw_uid,user.pw_gid)
  for f in fs:
   p=pathlib.Path(d)/f;os.chown(p,0 if base==etc else user.pw_uid,user.pw_gid)
   if base==etc:p.chmod(0o640)
(state/'ui/ui.json').chmod(0o600)
# Script passed as bytes from the current checked-in operations source.
seed=etc/'seed-offline-pilot.py';shutil.copyfile(root/'seed-offline-pilot.py',seed)
os.chown(seed,0,user.pw_gid);seed.chmod(0o640)
run=subprocess.run([str(installed/'venv/bin/python'),'-I','-B',str(seed),str(installed)],
 user=user.pw_uid,group=user.pw_gid,extra_groups=[],env=dict(PATH=os.defpath,HOME=str(state),TMPDIR=str(state/'tmp'),PYTHONDONTWRITEBYTECODE='1'),capture_output=True,text=True,timeout=180)
(root/'seed.log').write_text(run.stdout+'\n'+run.stderr)
assert run.returncode==0, 'offline_seed_failed_see_private_log'
unit=pathlib.Path('/etc/systemd/system/impactmap-ui-pilot.service');assert not unit.exists()
unit.write_text(f'''[Unit]
Description=ImpactMap UI pilot (isolated, saved offline author pins)
After=network.target
[Service]
Type=simple
User=impactmap-ui
Group=impactmap-ui
WorkingDirectory={state}
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=HOME={state}
Environment=TMPDIR={state}/tmp
ExecStart={installed}/venv/bin/python -I -B {installed}/app/tools/agent_service/box/launch.py --config {etc}/service.json --run {state}/run --host 127.0.0.1 --port 18092
Restart=on-failure
RestartSec=5
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ReadWritePaths={state}
ReadOnlyPaths={state}/mirrors
[Install]
WantedBy=multi-user.target
''')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','impactmap-ui-pilot'],check=True,capture_output=True)
print(json.dumps(dict(status='UI_PILOT_STARTED',release=str(installed),seed=json.loads(run.stdout),unit='impactmap-ui-pilot.service',origin='https://82.202.141.50',tracker_keys='NOT_COPIED',old_worker='UNTOUCHED')))
