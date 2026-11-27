import importlib.util,json,hashlib,subprocess
from pathlib import Path
spec=importlib.util.spec_from_file_location('control','/tmp/impactmap08-cloud-control.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
root='/var/tmp/impactmap-kaiten-cloud-20261115-a59cd9f8'
paths=subprocess.check_output(['git','ls-files','-z','src','tests','tools','constitutions','examples','pyproject.toml'],cwd=m.ROOT).decode().split('\0')
paths=sorted(set(p for p in paths if p)|{'tools/agent_service/kaiten_live_acceptance.py','tests/service/test_kaiten_live_acceptance.py'})
manifest={p:hashlib.sha256((m.ROOT/p).read_bytes()).hexdigest() for p in paths}
setup='ROOT_PATH='+repr(root)+'\nPR_NUMBER=5\nSECONDARY_CARD="74807549"\nCODE_VERSION='+repr('e22413a+cloud-helper:'+manifest['tools/agent_service/kaiten_live_acceptance.py'][:12])+'\n'
code=setup+r'''
from pathlib import Path
import json,os,subprocess,hashlib
root=Path(ROOT_PATH);app=root/'app';manifest=json.loads((root/'candidate-files.json').read_text())
assert all(hashlib.sha256((app/n).read_bytes()).hexdigest()==h for n,h in manifest.items())
assert (root/'secrets.json').stat().st_mode&0o777==0o600
prod=json.loads(Path('/etc/agent-bitbucket/service.json').read_text());policy=json.loads(Path(prod['core']['policy_path']).read_text())
loaded=json.loads(Path('/var/lib/agent-bitbucket/run/loaded.json').read_text());pid=int(subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True))
'''+m.BOOTSTRAP[m.BOOTSTRAP.index("for repo in policy['repositories']:"):]
code=code.replace(" subprocess.run(['git','-c'", " subprocess.run(['git','-c'")
# Existing completed mirrors are never discarded. In this failed bootstrap no config or queue existed.
code=code.replace(" subprocess.run(['git','-c','safe.directory='+repo['root'],'clone','--mirror','--no-hardlinks','--quiet',repo['root'],str(dest)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)", "\n if not dest.exists():\n  r=subprocess.run(['git','-c','safe.directory='+repo['root'],'clone','--mirror','--no-hardlinks','--quiet',repo['root'],str(dest)],capture_output=True,text=True)\n  if r.returncode:\n   print(json.dumps({'status':'CLONE_FAILED','repo':repo['id'],'reason_tags':[x for x in ('dubious ownership','Permission denied','transport','not a git repository') if x.lower() in r.stderr.lower()]}));raise SystemExit(1)\n assert subprocess.check_output(['git','--git-dir',str(dest),'rev-parse','--is-bare-repository'],text=True).strip()=='true'")
compile(code,'<resume>','exec')
code=code.replace("r=subprocess.run(['git','-c'", "clone_env={**os.environ,'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'safe.directory','GIT_CONFIG_VALUE_0':str(Path(repo['root']).resolve())}\n  r=subprocess.run(['git','-c'")
code=code.replace("capture_output=True,text=True)","capture_output=True,text=True,env=clone_env)")
code=code.replace("'clone','--mirror'","'clone','--upload-pack='+__import__('shlex').join(['git','-c','safe.directory='+str(Path(repo['root']).resolve()),'upload-pack']),'--mirror'")
compile(code,'<resume>','exec')
result=m.remote(code,timeout=90)
expected=hashlib.sha256((json.dumps(manifest,sort_keys=True,indent=2)+'\n').encode()).hexdigest();assert result['manifest_sha256']==expected
(m.PRIVATE/'session.json').write_text(json.dumps(result,indent=2)+'\n');(m.PRIVATE/'candidate-files.json').write_text(json.dumps(manifest,sort_keys=True,indent=2)+'\n');print(json.dumps(result))
