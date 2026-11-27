"""Run only AFTER key persistence/transfer consent. Fixed scoped pilot, no proxy switch."""
import pathlib,json,subprocess,sys,os,stat
state=pathlib.Path('/var/lib/impactmap-ui-kaiten');etc=pathlib.Path('/etc/impactmap-ui-kaiten')
release=pathlib.Path('/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312')
assert (etc/'secrets.env').is_file() and not (etc/'secrets.env').is_symlink()
info=(etc/'secrets.env').stat();assert info.st_uid==0 and stat.S_IMODE(info.st_mode)==0o600
cfg=json.loads((etc/'service.json').read_text())
assert cfg['state_path']==str(state/'service/service.sqlite') and cfg['publication']=='live'
assert cfg['kaiten']['base_url']=='https://rengalaxies.kaiten.ru' and cfg['kaiten']['board_ids']==['1982649'] and list(cfg['kaiten']['bindings'].values())==['74759475']
unit=pathlib.Path('/etc/systemd/system/impactmap-ui-kaiten.service');assert not unit.exists()
unit.write_text(f'''[Unit]
Description=ImpactMap live UI acceptance (dedicated Bitbucket PR5 to Kaiten74759475)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
User=impactmap-ui
Group=impactmap-ui
WorkingDirectory={state}
EnvironmentFile={etc}/secrets.env
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=HOME={state}
Environment=TMPDIR={state}/tmp
Environment=GIT_CONFIG_GLOBAL=/dev/null
ExecStart={release}/venv/bin/python -I -B {release}/app/tools/agent_service/box/launch.py --config {etc}/service.json --run {state}/run --host 127.0.0.1 --port 18093
Restart=on-failure
RestartSec=5
TimeoutStopSec=45
UMask=0077
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=yes
PrivateTmp=yes
PrivateDevices=yes
ReadWritePaths={state}
[Install]
WantedBy=multi-user.target
''');unit.chmod(0o644)
subprocess.run(['systemctl','daemon-reload'],check=True)
# Enable at the final decision according to permanent vs temporary consent.
subprocess.run(['systemctl','start','impactmap-ui-kaiten'],check=True)
print(json.dumps(dict(status='SCOPED_LIVE_WORKER_STARTED',unit=unit.name,bind='127.0.0.1:18093',proxy='UNCHANGED_18092')))
