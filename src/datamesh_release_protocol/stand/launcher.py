"""Portable local launcher; persistent domain identities and independent processes."""
import json
import secrets
import subprocess
import sys
import select
from pathlib import Path
from .protocol import keypair,owned_records


class LocalStand:
    def __init__(self,root,store,snapshots):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.store=store;self.processes={};self.peers={};self.private_keys={};self.public_keys={};self.configs={}
        domains=sorted(set(store.domain_routes.values()))
        existing=[(self.root/(domain+'.json')).exists() for domain in domains]
        if any(existing) and not all(existing):raise ValueError('incomplete persisted domain configuration')
        for domain in domains:
            if all(existing):
                config=json.loads((self.root/(domain+'.json')).read_text());private=config['private_key'];public=config['public_keys'][domain]
                if config['domain_id']!=domain or config['routes']!=store.domain_routes:raise ValueError('persisted domain identity differs')
                self.configs[domain]=config
            else:private,public=keypair()
            self.private_keys[domain]=private;self.public_keys[domain]=public
        store.domain_public_keys=dict(self.public_keys)
        try:
            for domain in domains:
                if not existing[0]:
                    records={r.record_id:r for snapshot in snapshots.values() for r in owned_records(snapshot,domain,store.domain_routes)}
                    config={'domain_id':domain,'host':'127.0.0.1','port':0,'database':str(self.root/(domain+'.sqlite3')),
                        'token':secrets.token_hex(24),'admin_token':secrets.token_hex(24),'private_key':self.private_keys[domain],
                        'public_keys':self.public_keys,'routes':store.domain_routes,'records':[r.model_dump(mode='json') for r in records.values()]}
                    path=self.root/(domain+'.json');path.write_text(json.dumps(config));path.chmod(0o600);self.configs[domain]=config
                elif self.configs[domain]['public_keys']!=self.public_keys:raise ValueError('persisted trust configuration differs')
                self.restart(domain)
        except Exception:self.close();raise
    def restart(self,domain):
        if domain in self.processes:self.stop(domain)
        config=self.configs[domain];path=self.root/(domain+'.json')
        process=subprocess.Popen([sys.executable,'-m','datamesh_release_protocol.stand.node','--config',str(path)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        self.processes[domain]=process
        if not select.select([process.stdout],[],[],10)[0]:raise TimeoutError('domain startup exceeded 10 seconds')
        line=process.stdout.readline()
        if not line:raise RuntimeError('domain startup failed: '+process.stderr.read()[:1800])
        ready=json.loads(line)
        self.peers[domain]={'url':ready['url'],'token':config['token'],'admin_token':config['admin_token'],'pid':process.pid}
    def stop(self,domain):
        process=self.processes[domain]
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=5)
        if process.stdout:process.stdout.close()
        if process.stderr:process.stderr.close()
    def close(self):
        for domain in self.processes:self.stop(domain)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
