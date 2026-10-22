#!/bin/bash
set -euo pipefail
umask 077
sha="$1"
image="$2"
[[ "$sha" =~ ^[a-f0-9]{40}$ ]]
[[ "$image" =~ ^sha256:[a-f0-9]{64}$ ]]
incoming=/home/dmadmin/agent-graph-demo-delivery
release="/opt/agent-graph-demo/releases/$sha"
core=/opt/agent-graph-demo/cores/a9385c565d5471698da62987b226dcff4cbdea86
test ! -e /etc/agent-graph-demo/web.json || { echo 'Existing demo configuration: stop for explicit upgrade/backup'; exit 1; }
cd "$incoming"
sha256sum -c SHA256SUMS
python3 - "$sha" "$image" <<'PY'
import json,sys,tarfile
from pathlib import PurePosixPath
p=json.load(open('image-audit.json'))
assert p['status']=='PASS' and p['source_sha']==sys.argv[1] and p['image_id']==sys.argv[2]
assert p['architecture']=='amd64' and p['os']=='linux'
for name in ('release.tar.gz','core.tar.gz','wheels.tar.gz'):
    with tarfile.open(name) as archive:
        for m in archive:
            path=PurePosixPath(m.name)
            assert not path.is_absolute() and '..' not in path.parts and (m.isfile() or m.isdir())
PY
backup="/var/backups/agent-graph-demo/$(date -u +%Y%m%dT%H%M%SZ)"
install -d -m 700 "$backup"
printf '%s\n' "$backup" > "$incoming/backup-path.txt"
systemctl cat dmrp-ui.service > "$backup/dmrp-ui.service.txt" 2>&1 || true
systemctl cat nginx.service > "$backup/nginx.service.txt" 2>&1 || true
tar -czf "$backup/existing-nginx-and-old-unit.tar.gz" /etc/nginx /etc/systemd/system/dmrp-ui.service 2>/dev/null
systemctl --no-pager --type=service --state=running > "$backup/running-services.txt"
ss -lntp > "$backup/ports.txt"
dpkg-query -W > "$backup/packages.txt"
install -m 700 "$incoming/rollback.sh" "$backup/rollback.sh"
install -d -m 755 "$release" "$core" /etc/agent-graph-demo /var/lib/agent-graph-demo /usr/local/libexec
tar -xzf release.tar.gz -C "$release"
tar -xzf core.tar.gz -C "$core"
gzip -dc image.tar.gz | docker load > "$backup/image-load.txt"
image=$(python3 - "$sha" "$image" <<'PY'
import hashlib,json,subprocess,sys,tarfile
from pathlib import Path
with tarfile.open('image.tar.gz') as archive:
    index=json.load(archive.extractfile('index.json'))
    assert len(index['manifests'])==1
    descriptor=index['manifests'][0]
    digest=descriptor['digest']
    manifest_bytes=archive.extractfile('blobs/sha256/'+digest.split(':')[1]).read()
    assert 'sha256:'+hashlib.sha256(manifest_bytes).hexdigest()==digest
    manifest=json.loads(manifest_bytes)
    assert manifest['config']['digest']==sys.argv[2]
    config_bytes=archive.extractfile('blobs/sha256/'+sys.argv[2].split(':')[1]).read()
    assert 'sha256:'+hashlib.sha256(config_bytes).hexdigest()==sys.argv[2]
    config=json.loads(config_bytes)
target=json.loads(subprocess.check_output(['docker','image','inspect','agent-graph-demo:delivery']))[0]
assert target['Id'] in (sys.argv[2],digest)
assert target['Config']['Labels']['agent-graph-demo.product']==sys.argv[1]
assert target['RootFS']['Layers']==config['rootfs']['diff_ids']
for field in ('User','Env','Cmd','Entrypoint','WorkingDir','Labels'):
    assert target['Config'].get(field)==config['config'].get(field),field
proof=dict(source_sha=sys.argv[1],config_digest=sys.argv[2],oci_manifest_digest=digest,
           installed_image_id=target['Id'],rootfs_layer_count=len(target['RootFS']['Layers']),status='PASS')
Path('loaded-image.json').write_text(json.dumps(proof,indent=2)+'\n')
print(target['Id'])
PY
)
if ! python3 -c 'import ensurepip' >/dev/null 2>&1; then
    apt-get update -qq > "$backup/apt-update.log" 2>&1
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq python3.12-venv > "$backup/apt-install.log" 2>&1
fi
python3 -m venv "$release/operator-venv"
install -d -m 755 "$release/offline-wheels"
tar -xzf wheels.tar.gz -C "$release/offline-wheels"
"$release/operator-venv/bin/python" -m pip install --no-index --require-hashes --find-links "$release/offline-wheels/wheels" -r "$release/infra/agent_graph_demo/requirements.lock" > "$backup/operator-dependencies.log"
find "$release" "$core" -type d -exec chmod 755 {} +
find "$release" "$core" -type f -exec chmod a+r {} +
install -d -o 10001 -g 10001 -m 700 /var/lib/agent-graph-demo/state
install -d -o root -g 10001 -m 750 /var/lib/agent-graph-demo/runtime
install -d -o root -g root -m 700 /var/lib/agent-graph-demo/receipts
python3 - "$sha" "$image" "$core" <<'PY'
import hashlib,json,os,secrets,sys
from pathlib import Path
p=Path('/etc/agent-graph-demo')
password,viewer=secrets.token_urlsafe(30),secrets.token_urlsafe(30)
(p/'operator-password').write_text(password+'\n')
(p/'private-test-logins.json').write_text(json.dumps({'operator':password,'viewer':viewer})+'\n')
users=[dict(subject='operator',role='operator',password_sha256=hashlib.sha256(password.encode()).hexdigest(),allowed_session_ids=[]),dict(subject='viewer',role='viewer',password_sha256=hashlib.sha256(viewer.encode()).hexdigest(),allowed_session_ids=[])]
(p/'auth.json').write_text(json.dumps({'users':users})+'\n')
web=dict(state_root='/var/lib/agent-graph-demo/state',core_root='/core',auth_config_path='/etc/demo/auth.json',runtime_registry_path='/var/lib/agent-graph-demo/runtime/active.json',allowed_origins=['http://127.0.0.1:18081'],public_mode=False,product_sha=sys.argv[1])
(p/'web.json').write_text(json.dumps(web)+'\n')
operator=dict(state_root='/var/lib/agent-graph-demo/state',runtime_root='/var/lib/agent-graph-demo/runtime',product_sha=sys.argv[1],image=sys.argv[2])
(p/'operator.json').write_text(json.dumps(operator)+'\n')
(p/'release.env').write_text('DEMO_IMAGE='+sys.argv[2]+'\nDEMO_CORE_ROOT='+sys.argv[3]+'\n')
for f in p.iterdir():
    os.chmod(f,0o600)
for name in ('auth.json','web.json'):
    os.chown(p/name,0,10001);os.chmod(p/name,0o640)
PY
ln -s "$release" /opt/agent-graph-demo/current
cat > /usr/local/sbin/agent-graph-demo-operator <<'SH'
#!/bin/sh
set -eu
test "$(id -u)" = 0
release=/opt/agent-graph-demo/current
exec /usr/bin/systemd-run --quiet --wait --pipe --collect -p CPUQuota=50% -p MemoryMax=256M -p TasksMax=64 /usr/bin/env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$release/src:$release" "$release/operator-venv/bin/python" "$release/tools/agent_graph_demo/run_scenario.py" --config /etc/agent-graph-demo/operator.json "$@"
SH
chmod 755 /usr/local/sbin/agent-graph-demo-operator
cat > /usr/local/libexec/agent-graph-demo-observe.py <<'PY'
import json,subprocess
from pathlib import Path
p=Path('/var/lib/agent-graph-demo/runtime/active.json')
if p.exists():
    state=json.loads(p.read_text())
    if state['state'] in ('STOPPED','RUNNING'):
        subprocess.run(['/usr/local/sbin/agent-graph-demo-operator','observe','--expected-generation',str(state['generation'])],check=True)
PY
chmod 755 /usr/local/libexec/agent-graph-demo-observe.py
install -m 644 "$release/infra/agent_graph_demo/agent-graph-demo.service" /etc/systemd/system/agent-graph-demo.service
install -d -m 755 /etc/systemd/system/agent-graph-demo.service.d
cat > /etc/systemd/system/agent-graph-demo.service.d/10-runtime-observation.conf <<'UNIT'
[Unit]
PartOf=docker.service
[Service]
ExecStartPost=-/usr/bin/python3 /usr/local/libexec/agent-graph-demo-observe.py
UNIT
cat > /etc/systemd/system/agent-graph-demo-observe.service <<'UNIT'
[Unit]
Description=Observe existing graph demo sandbox (never start or reconcile)
After=agent-graph-demo.service
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/libexec/agent-graph-demo-observe.py
MemoryMax=128M
CPUQuota=25%
UNIT
cat > /etc/systemd/system/agent-graph-demo-observe.timer <<'UNIT'
[Unit]
Description=Keep graph demo runtime observations fresh
[Timer]
OnBootSec=60
OnUnitActiveSec=60
AccuracySec=5
[Install]
WantedBy=timers.target
UNIT
/usr/local/sbin/agent-graph-demo-operator reconcile --expected-generation 0 > "$backup/initial-reconciliation.json"
systemctl daemon-reload
systemctl enable --now agent-graph-demo.service
# Enable observations after target acceptance; each manual check refreshes registry meanwhile.
systemctl enable agent-graph-demo-observe.timer
cp image-audit.json SHA256SUMS loaded-image.json "$backup/"
python3 - "$sha" "$image" "$backup" <<'PY'
import json,sys
from pathlib import Path
Path('/etc/agent-graph-demo/installation.json').write_text(json.dumps(dict(source_sha=sys.argv[1],image_id=sys.argv[2],backup=sys.argv[3],bind='127.0.0.1:18081',model_mode='UNAVAILABLE_NO_CALLS'))+'\n')
PY
printf 'INSTALLED source=%s image=%s backup=%s\n' "$sha" "$image" "$backup"
docker ps --format '{{.Names}} {{.Status}} {{.Ports}}'
ss -lntp | grep ':18081'
