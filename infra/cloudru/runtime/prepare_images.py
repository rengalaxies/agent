"""Build on CI, export immutable local image IDs; never needs cloud credentials."""
import gzip,hashlib,json,os,pathlib,shutil,subprocess
P=pathlib.Path;out=P('cloud-evidence');out.mkdir(exist_ok=True)
SOURCE='107dfd14292a5ab06593d424bf0b94f1cccb0b90';TREE='540a48cc47d87d1656e744aa20ab996d6af7bca8'
def run(args):return subprocess.check_output(args,text=True).strip()
assert run(['git','-C','release-source','rev-parse','HEAD'])==SOURCE
assert run(['git','-C','release-source','rev-parse','HEAD^{tree}'])==TREE
assert subprocess.run(['git','-C','release-source','config','--get-regexp','http.*extraheader'],capture_output=True).returncode==1
app='agent-cloud-product:'+SOURCE
with (out/'image-build.log').open('w') as log:subprocess.run(['docker','build','--file','infra/cloudru/runtime/Dockerfile','--tag',app,'release-source'],stdout=log,stderr=subprocess.STDOUT,check=True,timeout=900)
images={'app':app,'postgres':'postgres@sha256:38471f330eb885e04de130b768d6db4e10469e2311879c7e5c699f6d2d8a1c74','rabbitmq':'rabbitmq@sha256:e582c0bc7766f3342496d8485efb5a1df782b5ce3886ad017e2eaae442311f69','proxy':'caddy@sha256:4c6e91c6ed0e2fa03efd5b44747b625fec79bc9cd06ac5235a779726618e530d'}
manifest={'product_commit':SOURCE,'product_tree':TREE,'controller_commit':os.environ['GITHUB_SHA'],'images':{}}
for key,ref in images.items():
 if key!='app':subprocess.run(['docker','pull',ref],check=True,timeout=300)
 d=json.loads(run(['docker','image','inspect',ref]))[0];assert d['Architecture']=='amd64' and d['Os']=='linux'
 manifest['images'][key]={'reference':ref,'id':d['Id'],'repo_digests':d['RepoDigests']}
archive=P(os.environ['RUNNER_TEMP'])/'cloud-runtime-images.tar.gz'
with archive.open('wb') as raw,gzip.GzipFile(filename='',mode='wb',fileobj=raw,mtime=0,compresslevel=1) as compressed:
 process=subprocess.Popen(['docker','save',*[item['id'] for item in manifest['images'].values()]],stdout=subprocess.PIPE);shutil.copyfileobj(process.stdout,compressed,1024*1024);assert process.wait()==0
h=hashlib.sha256()
with archive.open('rb') as f:
 for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
manifest.update(archive=str(archive),sha256=h.hexdigest(),bytes=archive.stat().st_size)
assert 0<manifest['bytes']<2*1024**3
(out/'image-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps({k:manifest[k] for k in ['product_commit','product_tree','sha256','bytes']}))
