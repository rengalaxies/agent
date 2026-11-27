import pathlib,json,subprocess,pwd,hashlib,sys
etc=pathlib.Path('/etc/impactmap-ui-kaiten');release=pathlib.Path('/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312');user=pwd.getpwnam('impactmap-ui')
script=etc/'qa-ui.py';assert script.is_file()
def check(phase):
 r=subprocess.run([str(release/'venv/bin/python'),'-I','-B',str(script),str(release),phase],user=user.pw_uid,group=user.pw_gid,extra_groups=[],capture_output=True,text=True,timeout=45)
 if r.returncode:raise RuntimeError('ui_check_'+phase+'_failed:'+r.stderr[-300:])
 return json.loads(r.stdout)
pre=check('backend')
snippet=pathlib.Path('/etc/nginx/snippets/impactmap-ui-upstream.conf');old=snippet.read_bytes()
assert old.count(b'http://127.0.0.1:18092;')==1
backup=etc/'rollback-upstream.conf';assert not backup.exists();backup.write_bytes(old);backup.chmod(0o600)
snippet.write_bytes(old.replace(b'http://127.0.0.1:18092;',b'http://127.0.0.1:18093;'))
try:
 subprocess.run(['nginx','-t'],check=True,capture_output=True)
 subprocess.run(['systemctl','reload','nginx'],check=True)
 post=check('public')
except BaseException:
 snippet.write_bytes(old);subprocess.run(['nginx','-t'],check=True,capture_output=True);subprocess.run(['systemctl','reload','nginx'],check=True);raise
subprocess.run(['systemctl','enable','impactmap-ui-kaiten'],check=True,capture_output=True)
print(json.dumps(dict(status='PUBLIC_LIVE_UI_ACTIVE',backend_check=pre,public_check=post,upstream_sha256=hashlib.sha256(snippet.read_bytes()).hexdigest(),rollback=str(backup),offline_service='RETAINED_18092',legacy_pid=subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True).strip())))
