import json
import time
import urllib.request
from datetime import datetime,timezone
from ..knowledge import digest
from ..knowledge_release import request_fingerprint,MappedRelease
from .protocol import WorkItem,required_domains,SignedMessage,verify
from .policy import project,build_distributed_release


def post(peer,path,body,timeout=2,admin=False):
    headers={'Content-Type':'application/json','Authorization':'Bearer '+peer['token']}
    if admin:headers['X-Admin-Token']=peer['admin_token']
    req=urllib.request.Request(peer['url']+path,data=json.dumps(body).encode(),headers=headers,method='POST')
    with urllib.request.urlopen(req,timeout=max(0.01,timeout)) as response:return json.load(response)


class CoordinatorRun:
    def __init__(self,store,snapshot_id,run_id,ttl,migrations=None):
        if ttl<=0:raise ValueError('positive TTL required')
        self.store=store;self.snapshot=store.resolve_snapshot(snapshot_id);self.run_id=run_id
        self.migrations=migrations or [];self.started=time.monotonic();self.deadline=self.started+ttl
        self.messages=[];self.audit=[];self.result=None;self.frozen=None
    def work(self,event_id):return WorkItem(event_id=event_id,run_id=self.run_id,snapshot=self.snapshot,migrations=self.migrations).model_dump(mode='json')
    def receive(self,message):
        now=time.monotonic();payload_hash=digest(message)
        if self.result is not None or now>=self.deadline:
            self.audit.append({'kind':'LATE_IGNORED','elapsed_s':now-self.started,'payload_hash':payload_hash});return False
        self.messages.append(message);self.audit.append({'kind':'RECEIVED','elapsed_s':now-self.started,'payload_hash':payload_hash});return True
    def projection(self):return project(self.snapshot,self.run_id,self.migrations,self.messages,self.store.domain_public_keys,self.store.domain_routes,time.monotonic()>=self.deadline)
    def ready(self):
        p=self.projection()
        return not p['missing'] and not p['conflicts']
    def finish(self,at=None):
        with self.store.lock:
            self.store._ensure_healthy()
            if self.result is not None:return self.result.model_copy(deep=True)
            fingerprint=request_fingerprint(self.snapshot.snapshot_id,self.migrations)
            prior=self.store._release_runs.get(self.run_id)
            if prior:
                if prior['fingerprint']!=fingerprint:raise ValueError('conflicting run_id')
                self.result=MappedRelease.model_validate(prior['result']);return self.result.model_copy(deep=True)
            expired=time.monotonic()>=self.deadline
            p=self.projection()
            if (p['missing'] or p['conflicts']) and not expired:raise ValueError('mandatory responses still pending')
            at=at or datetime.now(timezone.utc)
            self.frozen=json.loads(json.dumps(self.messages))
            result=build_distributed_release(self.store,self.snapshot,self.run_id,at,self.migrations,self.frozen,expired)
            self.store._save_release_event({'kind':'distributed_decision','fingerprint':fingerprint,
                'migrations':[m.model_dump(mode='json') for m in self.migrations],'at':at.isoformat(),
                'messages':self.frozen,'deadline_expired':expired,'result':result.model_dump(mode='json')})
            self.result=result
            return result.model_copy(deep=True)
    def wait_deadline(self):
        while time.monotonic()<self.deadline:time.sleep(min(0.01,self.deadline-time.monotonic()))
