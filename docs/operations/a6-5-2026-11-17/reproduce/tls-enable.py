import json,pathlib,subprocess,hashlib
root=pathlib.Path('/var/lib/impactmap-tls');live=pathlib.Path('/etc/letsencrypt-impactmap/live/82.202.141.50')
assert (live/'fullchain.pem').exists()
conf=pathlib.Path('/etc/nginx/sites-available/impactmap-ui-ip');old=conf.read_text()
assert 'listen 443' not in old
text='''limit_req_zone $binary_remote_addr zone=impactmap_ui_login:1m rate=6r/m;
'''+old+'''
server {
    listen 443 ssl;
    server_name 82.202.141.50;
    ssl_certificate /etc/letsencrypt-impactmap/live/82.202.141.50/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt-impactmap/live/82.202.141.50/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_session_tickets off;
    server_tokens off;
    access_log off;
    client_max_body_size 8k;
    add_header Strict-Transport-Security "max-age=86400" always;
    location = / { return 302 /ui/changes; }
    location = /ui/api/login {
        limit_req zone=impactmap_ui_login burst=5 nodelay;
        limit_req_status 429;
        include /etc/nginx/snippets/impactmap-ui-upstream.conf;
    }
    location ^~ /ui/ { include /etc/nginx/snippets/impactmap-ui-upstream.conf; }
    location / { return 404; }
}
'''
snippet=pathlib.Path('/etc/nginx/snippets/impactmap-ui-upstream.conf')
assert not snippet.exists()
snippet.write_text('''proxy_pass http://127.0.0.1:18092;
proxy_http_version 1.1;
proxy_set_header Host $http_host;
proxy_set_header Connection "";
proxy_set_header X-Forwarded-For "";
proxy_set_header X-Forwarded-Proto "";
proxy_set_header X-Real-IP "";
proxy_connect_timeout 3s;
proxy_read_timeout 30s;
proxy_buffering off;
proxy_cache off;
''')
conf.write_text(text)
r=subprocess.run(['nginx','-t'],capture_output=True,text=True)
if r.returncode:conf.write_text(old);snippet.unlink();raise RuntimeError('nginx_configuration_invalid')
subprocess.run(['systemctl','reload','nginx'],check=True)
unit=pathlib.Path('/etc/systemd/system/impactmap-tls-renew.service')
assert not unit.exists()
unit.write_text('''[Unit]
Description=Renew ImpactMap public IP TLS certificate
Wants=network-online.target
After=network-online.target
[Service]
Type=oneshot
UMask=0077
ExecStart=/opt/impactmap-tls/venv/bin/certbot renew --quiet --config-dir /etc/letsencrypt-impactmap --work-dir /var/lib/impactmap-tls/work --logs-dir /var/lib/impactmap-tls/logs --deploy-hook "/usr/sbin/nginx -t && /usr/bin/systemctl reload nginx"
''')
pathlib.Path('/etc/systemd/system/impactmap-tls-renew.timer').write_text('''[Unit]
Description=Check ImpactMap IP certificate renewal twice daily
[Timer]
OnCalendar=*-*-* 00,12:00:00
RandomizedDelaySec=1800
Persistent=true
[Install]
WantedBy=timers.target
''')
subprocess.run(['systemctl','daemon-reload'],check=True)
subprocess.run(['systemctl','enable','--now','impactmap-tls-renew.timer'],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
cert=subprocess.check_output(['openssl','x509','-in',str(live/'fullchain.pem'),'-noout','-subject','-issuer','-dates','-ext','subjectAltName'],text=True)
print(json.dumps(dict(https='ENABLED_UI_ONLY',backend='127.0.0.1:18092',certificate=cert,nginx_sha256=hashlib.sha256(text.encode()).hexdigest(),timer=subprocess.check_output(['systemctl','is-active','impactmap-tls-renew.timer'],text=True).strip())))
