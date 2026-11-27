import json,pathlib,subprocess
root=pathlib.Path('/var/lib/impactmap-tls')
assert (root/'staging/live/82.202.141.50/fullchain.pem').exists()
cmd=['/opt/impactmap-tls/venv/bin/certbot','certonly','--non-interactive','--agree-tos','--register-unsafely-without-email','--required-profile','shortlived','--webroot','--webroot-path',str(root/'acme'),'--ip-address','82.202.141.50','--config-dir','/etc/letsencrypt-impactmap','--work-dir',str(root/'work'),'--logs-dir',str(root/'logs')]
with (root/'production-run.log').open('w') as log:
 p=subprocess.Popen(cmd,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
print(json.dumps(dict(status='REQUESTING_TRUSTED_IP_CERTIFICATE',pid=p.pid)))
