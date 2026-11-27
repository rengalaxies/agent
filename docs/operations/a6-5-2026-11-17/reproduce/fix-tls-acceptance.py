"""Persist one renewal hook used by timer and dry-run; allow canonical /ui.

Run as root on the fixed, owner-authorized82.202.141.50 pilot after tls-enable.
No credential/certificate private-key contents are read or emitted.
"""
import json,pathlib,subprocess,os
root=pathlib.Path('/var/lib/impactmap-tls');config=pathlib.Path('/etc/nginx/sites-available/impactmap-ui-ip')
text=config.read_text();needle='    location = / { return 302 /ui/changes; }'
if 'location = /ui {' not in text:
 assert needle in text
 updated=text.replace(needle,needle+'\n    location = /ui { return 303 /ui/changes; }')
 config.write_text(updated)
 check=subprocess.run(['nginx','-t'],capture_output=True)
 if check.returncode:config.write_text(text);raise RuntimeError('nginx_config_invalid')
 subprocess.run(['systemctl','reload','nginx'],check=True)
hook=pathlib.Path('/etc/letsencrypt-impactmap/renewal-hooks/deploy/20-impactmap-nginx')
hook.parent.mkdir(parents=True,exist_ok=True)
hook.write_text('''#!/bin/sh
set -eu
umask 077
/usr/sbin/nginx -t
/usr/bin/systemctl reload nginx
/usr/bin/date -u +%FT%TZ >> /var/lib/impactmap-tls/reload-proof.log
''');hook.chmod(0o700)
unit=pathlib.Path('/etc/systemd/system/impactmap-tls-renew.service')
content=unit.read_text();content=content.replace(' --deploy-hook "/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx"','');unit.write_text(content)
subprocess.run(['systemctl','daemon-reload'],check=True)
proof=root/'reload-proof.log';before=len(proof.read_text().splitlines()) if proof.exists() else 0
cmd=['/opt/impactmap-tls/venv/bin/certbot','renew','--dry-run','--run-deploy-hooks','--config-dir','/etc/letsencrypt-impactmap','--work-dir',str(root/'work'),'--logs-dir',str(root/'logs')]
with (root/'renew-hook-dry-run.log').open('w') as log:
 p=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
print(json.dumps(dict(status='RENEW_WITH_PERSISTENT_HOOK_STARTED',pid=p.pid,proof_lines_before=before,bare_ui='REDIRECT303')))
