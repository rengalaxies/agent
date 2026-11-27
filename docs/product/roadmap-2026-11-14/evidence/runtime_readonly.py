import hashlib
import json
from pathlib import Path
import subprocess
import urllib.request
from datetime import datetime, timezone

def cmd(*args):
    return subprocess.check_output(args, text=True).strip()

result = {'observed_utc': datetime.now(timezone.utc).isoformat(), 'scope': 'read-only runtime, config summary, authenticated status and installed source hashes; no reconcile/restart/API mutations'}
result['host'] = {'kernel': cmd('uname', '-srmo'), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), 'cpu_count': cmd('getconf', '_NPROCESSORS_ONLN'), 'memory_total_kib': int(Path('/proc/meminfo').read_text().splitlines()[0].split()[1])}
result['units'] = {u: cmd('systemctl', 'show', u, '-p', 'ActiveState', '-p', 'SubState', '-p', 'MainPID', '-p', 'UnitFileState') for u in ['agent-bitbucket', 'agent-service', 'nginx', 'docker']}
current = Path('/opt/agent-bitbucket/current')
result['current'] = str(current.resolve())
result['loaded'] = json.loads(Path('/var/lib/agent-bitbucket/run/loaded.json').read_text())
pid = int(cmd('systemctl', 'show', 'agent-bitbucket', '-p', 'MainPID', '--value'))
result['loaded_pid_matches_systemd'] = pid == result['loaded']['pid']
config = json.loads(Path('/etc/agent-bitbucket/service.json').read_text())
result['configuration'] = {'publication': config.get('publication'), 'reconcile_seconds': config.get('reconcile_seconds'), 'bitbucket_mode': config.get('bitbucket', {}).get('mode'), 'refresh_mirrors': config.get('bitbucket', {}).get('refresh_mirrors'), 'jira_comment_format': config.get('jira', {}).get('comment_format'), 'model_qualification_configured': config.get('core', {}).get('model_qualification') is not None}
policy_path = config.get('core', {}).get('policy_path')
if policy_path and str(policy_path).endswith('.json'):
    policy = json.loads(Path(policy_path).read_text())
    repos = policy.get('repositories', {})
    repo_names = sorted(repos) if isinstance(repos, dict) else sorted(r.get('id', r.get('name', 'unknown')) for r in repos)
    result['policy_summary'] = {'model_configured': bool(policy.get('model')), 'repositories': repo_names}
env = dict(item.split(b'=', 1) for item in Path(f'/proc/{pid}/environ').read_bytes().split(b'\0') if b'=' in item)
token = env.get(b'AGENT_SERVICE_STATUS_TOKEN', b'').decode()
result['http'] = {}
for route in ['/healthz', '/status']:
    headers = {'Authorization': 'Bearer ' + token} if route == '/status' else {}
    req = urllib.request.Request('http://127.0.0.1:8092' + route, headers=headers)
    with urllib.request.urlopen(req, timeout=10) as response:
        result['http'][route] = {'status': response.status, 'body': json.load(response)}
source_root = current / 'app' / 'src'
result['source_sha256'] = {str(p.relative_to(current / 'app')): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(source_root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.suffix == '.py'}
print(json.dumps(result, ensure_ascii=False, indent=2))
