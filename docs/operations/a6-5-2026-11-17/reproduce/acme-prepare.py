import json,pathlib,subprocess,os
root=pathlib.Path('/var/lib/impactmap-tls');web=root/'acme'
(web/'.well-known/acme-challenge').mkdir(parents=True,exist_ok=True,mode=0o755)
# nginx must traverse the webroot, while ACME account/keys live elsewhere0700.
root.chmod(0o755);web.chmod(0o755)
conf=pathlib.Path('/etc/nginx/sites-available/impactmap-ui-ip')
assert not conf.exists(), 'new_site_already_exists'
text='''server {
    listen 80;
    server_name 82.202.141.50;
    access_log off;
    location ^~ /.well-known/acme-challenge/ {
        root /var/lib/impactmap-tls/acme;
        try_files $uri =404;
    }
    location / { return 308 https://82.202.141.50$request_uri; }
}
'''
backup=root/'nginx-before.txt';backup.write_bytes(subprocess.check_output(['nginx','-T'],stderr=subprocess.DEVNULL));backup.chmod(0o600)
conf.write_text(text);conf.chmod(0o644)
link=pathlib.Path('/etc/nginx/sites-enabled/impactmap-ui-ip');link.symlink_to(conf)
r=subprocess.run(['nginx','-t'],capture_output=True,text=True)
if r.returncode:link.unlink();conf.unlink();raise RuntimeError('nginx_configuration_invalid')
subprocess.run(['systemctl','reload','nginx'],check=True)
probe=web/'.well-known/acme-challenge/impactmap-preflight';probe.write_text('impactmap-acme-preflight\n')
cmd=['/opt/impactmap-tls/venv/bin/certbot','certonly','--non-interactive','--agree-tos','--register-unsafely-without-email','--staging','--preferred-profile','shortlived','--webroot','--webroot-path',str(web),'--ip-address','82.202.141.50','--config-dir',str(root/'staging'),'--work-dir',str(root/'staging-work'),'--logs-dir',str(root/'staging-logs')]
with (root/'staging-run.log').open('w') as log:
 p=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
print(json.dumps(dict(nginx='RELOADED_ACME_ONLY',staging_pid=p.pid,probe='/.well-known/acme-challenge/impactmap-preflight')))
