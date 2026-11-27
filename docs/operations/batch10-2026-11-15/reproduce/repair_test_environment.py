"""One isolated test-environment correction; source/package/runtime lock unchanged."""
from pathlib import Path
import importlib.util,io,json,tarfile
LOCAL=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('driver',LOCAL/'linux_driver.py');d=importlib.util.module_from_spec(spec);spec.loader.exec_module(d)
meta=json.loads((LOCAL/'linux-tools-meta.json').read_text());fields=dict(line.split(': ',1) for line in meta['metadata'].splitlines() if ': ' in line)
files={'test-requirements-v2.txt':LOCAL/'test-requirements.txt','ci-final-runner.py':LOCAL/'final_ci_runner.py'}
files.update({'test-wheels-v2/'+p.name:p for p in (LOCAL/'test-wheels').glob('*.whl')})
buffer=io.BytesIO()
with tarfile.open(fileobj=buffer,mode='w') as t:
 for name,p in files.items():
  raw=p.read_bytes();m=tarfile.TarInfo(name);m.size=len(raw);t.addfile(m,io.BytesIO(raw))
code=r'''
from pathlib import Path
import hashlib,io,json,os,subprocess,sys,tarfile,urllib.request
root=Path(ROOT);status=json.loads((root/'status.json').read_text())
assert status['status']=='FAILED' and status['source_commit']==SOURCE
assert not (root/'status-infra-v1.json').exists()
(root/'status-infra-v1.json').write_text((root/'status.json').read_text())
with tarfile.open(fileobj=io.BytesIO(sys.stdin.buffer.read()),mode='r:') as t:
 for m in t.getmembers():
  p=Path(m.name);assert m.isfile() and not p.is_absolute() and '..' not in p.parts
  dest=root/p;dest.parent.mkdir(exist_ok=True);dest.write_bytes(t.extractfile(m).read())
url='https://archive.ubuntu.com/ubuntu/'+FILENAME
with urllib.request.urlopen(url,timeout=45) as response:raw=response.read(5_000_001)
assert hashlib.sha256(raw).hexdigest()==RG_SHA
(root/'ripgrep.deb').write_bytes(raw)
subprocess.run(['dpkg-deb','-x',str(root/'ripgrep.deb'),str(root/'testtools')],check=True)
(root/'env/bin/rg').symlink_to(root/'testtools/usr/bin/rg')
rg=subprocess.check_output([str(root/'env/bin/rg'),'--version'],text=True)
(root/'rg.json').write_text(json.dumps(dict(version=rg,source=url,sha256=RG_SHA)))
with (root/'install-test-deps-v2.log').open('w') as f:
 subprocess.run([str(root/'env/bin/python'),'-m','pip','install','--no-index','--no-cache-dir','--no-deps','--upgrade','--target',str(root/'testdeps'),'--find-links',str(root/'test-wheels-v2'),'-r',str(root/'test-requirements-v2.txt')],stdout=f,stderr=f,check=True)
uid,gid=UID,GID
(root/'test-user.json').write_text(json.dumps(dict(uid=uid,gid=gid)))
for base,dirs,names in os.walk(root,followlinks=False):
 os.chown(base,uid,gid,follow_symlinks=False)
 for name in dirs+names:os.chown(Path(base)/name,uid,gid,follow_symlinks=False)
with (root/'ci-final-runner.log').open('w') as log:
 p=subprocess.Popen([sys.executable,str(root/'ci-final-runner.py')],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True)
print(json.dumps(dict(status='STARTED_FINAL_CI',pid=p.pid,uid=uid,gid=gid,rg=rg.splitlines()[0])))
'''.replace('ROOT',repr(d.REMOTE)).replace('SOURCE',repr(d.SHA)).replace('FILENAME',repr(fields['Filename'])).replace('RG_SHA',repr(fields['SHA256'])).replace('UID',str(meta['uid'])).replace('GID',str(meta['gid']))
print(json.dumps(d.remote(code,buffer.getvalue(),timeout=120)))
