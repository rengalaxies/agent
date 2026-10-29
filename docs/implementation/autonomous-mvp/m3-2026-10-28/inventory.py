#!/usr/bin/env python3
"""Read-only inventory; run on the verified target as root, keep output private for review.

Does not read process environments, secret files, private keys or application DBs.
No service changes. Raw Nginx configuration is never included in the report.
"""
import datetime
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def run(*args, timeout=20):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {"exit": p.returncode, "stdout": p.stdout[:48000], "truncated": len(p.stdout) > 48000}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": type(e).__name__}


def listing(directory):
    try:
        result = []
        for p in sorted(Path(directory).iterdir())[:100]:
            s = p.lstat()
            result.append({"path": str(p), "mode": oct(s.st_mode & 0o7777), "uid": s.st_uid,
                           "gid": s.st_gid, "bytes": s.st_size, "symlink": p.is_symlink()})
        return result
    except OSError as e:
        return {"error": type(e).__name__}


def main():
    if platform.system() != "Linux":
        raise SystemExit("Run on the verified Linux target, not the operator laptop.")
    report = {"checked_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "hostname": platform.node(), "platform": platform.platform(), "euid": os.geteuid(),
              "cpu_count": os.cpu_count(), "loadavg": os.getloadavg(),
              "boot_id": Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
              "memory": Path('/proc/meminfo').read_text(),
              "disk": run('df', '-hT'), "processes": run('ps', '-eo', 'pid,ppid,user,%cpu,%mem,rss,comm'),
              "listeners": run('ss', '-lntup'),
              "services": run('systemctl', 'list-units', '--type=service', '--all', '--no-pager'),
              "enabled": run('systemctl', 'list-unit-files', '--no-pager'),
              "timers": run('systemctl', 'list-timers', '--all', '--no-pager'),
              "python": run('python3', '--version'), "git": run('git', '--version'),
              "nginx_test": run('nginx', '-t'),
              "paths": {p: listing(p) for p in ['/opt', '/srv', '/var/lib', '/var/backups', '/etc/nginx/sites-enabled',
                                                '/etc/agent-service', '/var/lib/agent-service-box']},
              "service_user": run('getent', 'passwd', 'agent-service')}
    # Inspect routing/TLS privately after inventory. Even a location/proxy_pass
    # line can contain credentials; do not copy raw configuration into evidence.
    if shutil.which('docker'):
        report['containers'] = run('docker', 'ps', '--all', '--format', '{{.Names}} {{.Image}} {{.Ports}} {{.Status}}')
        report['volumes'] = run('docker', 'volume', 'ls', '--format', '{{.Name}}')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
