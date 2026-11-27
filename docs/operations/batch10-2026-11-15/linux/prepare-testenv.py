from pathlib import Path
import hashlib,io,json,os,subprocess,sys,tarfile,urllib.request
root=Path('/var/tmp/impactmap-batch10-5d508a2e301d-20261115');status=json.loads((root/'status.json').read_text())
assert status['status']=='FAILED' and status['source_commit']=='5d508a2e301dc8991672903f978c8c377ba8041d'
assert (root/'status-infra-v1.json').read_text()==(root/'status.json').read_text()
assert not (root/'ci-final-runner.py').exists()
(root/'status-infra-v1.json').write_text((root/'status.json').read_text())
archive=Path('/tmp/impactmap10-testenv-5d508a2.tar')
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='637000d0443320e14633310fd09cbc4c229b4d3fb541910d12d2bf2eee055390'
with tarfile.open(archive,mode='r:') as t:
 for m in t.getmembers():
  p=Path(m.name);assert m.isfile() and not p.is_absolute() and '..' not in p.parts
  dest=root/p;dest.parent.mkdir(exist_ok=True);dest.write_bytes(t.extractfile(m).read())
url='https://archive.ubuntu.com/ubuntu/'+'pool/universe/r/rust-ripgrep/ripgrep_14.1.0-1_amd64.deb'
with urllib.request.urlopen(url,timeout=45) as response:raw=response.read(5_000_001)
assert hashlib.sha256(raw).hexdigest()=='c5ae63c7bee915b1cfc9f0bd07c55b4ce7f2bcd1133cba4da56719aac26101a4'
(root/'ripgrep.deb').write_bytes(raw)
subprocess.run(['dpkg-deb','-x',str(root/'ripgrep.deb'),str(root/'testtools')],check=True)
(root/'env/bin/rg').symlink_to(root/'testtools/usr/bin/rg')
rg=subprocess.check_output([str(root/'env/bin/rg'),'--version'],text=True)
(root/'rg.json').write_text(json.dumps(dict(version=rg,source=url,sha256='c5ae63c7bee915b1cfc9f0bd07c55b4ce7f2bcd1133cba4da56719aac26101a4')))
with (root/'install-test-deps-v2.log').open('w') as f:
 subprocess.run([str(root/'env/bin/python'),'-m','pip','install','--no-index','--no-cache-dir','--no-deps','--upgrade','--target',str(root/'testdeps'),'--find-links',str(root/'test-wheels-v2'),'-r',str(root/'test-requirements-v2.txt')],stdout=f,stderr=f,check=True)
uid,gid=1000,1002
(root/'test-user.json').write_text(json.dumps(dict(uid=uid,gid=gid)))
for base,dirs,names in os.walk(root,followlinks=False):
 os.chown(base,uid,gid,follow_symlinks=False)
 for name in dirs+names:os.chown(Path(base)/name,uid,gid,follow_symlinks=False)
with (root/'ci-final-runner.log').open('w') as log:
 p=subprocess.Popen([sys.executable,str(root/'ci-final-runner.py')],stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True,close_fds=True)
print(json.dumps(dict(status='STARTED_FINAL_CI',pid=p.pid,uid=uid,gid=gid,rg=rg.splitlines()[0])))
