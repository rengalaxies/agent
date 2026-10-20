"""Durable, transactional workflow state and exact-input idempotency."""
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from lab.runtime.core import digest, now, Stop

KINDS = ('changes','snapshots','jobs','assessments','cards','decisions','candidates','verifications','journal')
RESULTS = ('assessments','cards','decisions','candidates','verifications')
MODES = ('LIVE RUN','REPLAY','FIXTURE / CONTROL')

class Store:
    def __init__(self, path):
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS entities (kind TEXT,id TEXT PRIMARY KEY,data TEXT NOT NULL)')
        with self.transaction():
            for job in self.rows('jobs'):
                if job['status']=='RUNNING':
                    job.update(status='UNKNOWN',error='PROCESS_INTERRUPTED; reconcile explicitly; no automatic retry')
                    self.put('jobs',job)
    @contextmanager
    def transaction(self):
        with self.lock:
            self.db.execute('BEGIN IMMEDIATE')
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK'); raise
    def rows(self,kind):
        with self.lock:
            return [json.loads(x[0]) for x in self.db.execute('SELECT data FROM entities WHERE kind=? ORDER BY rowid',(kind,))]
    def put(self,kind,row):
        self.db.execute('INSERT INTO entities VALUES (?,?,?) ON CONFLICT(id) DO UPDATE SET data=excluded.data',(kind,row['id'],json.dumps(row,ensure_ascii=False)))
        return row
    def latest(self,cid):
        found=[c for c in self.rows('changes') if c['change_id']==cid]
        if not found: raise Stop('Unknown change')
        return max(found,key=lambda c:c['revision'])
    def entity(self,kind,eid):
        row=next((r for r in self.rows(kind) if r['id']==eid),None)
        if not row: raise Stop('Unknown '+kind)
        return row
    def base(self,c,mode,**fields):
        return {**dict(id=uuid.uuid4().hex,change_id=c['change_id'],revision=c['revision'],input_digest=c['input_digest'],source_commit=c['source_commit'],mode=mode,created_at=now()),**fields}
    def log(self,c,action,**fields): self.put('journal',self.base(c,fields.pop('mode','FIXTURE / CONTROL'),action=action,**fields))
    def invalidate(self,cid,reason):
        for kind in RESULTS:
            for r in self.rows(kind):
                if r['change_id']==cid and r.get('current'):
                    r.update(current=False,invalidation=reason)
                    if kind=='cards': r['status']='устарело'
                    self.put(kind,r)
    def create_change(self,payload):
        required=('change_id','title','intent','proposed_diff','source_commit')
        if any(not isinstance(payload.get(k),str) or not payload[k].strip() for k in required): raise Stop('Nonempty change fields required')
        if type(payload.get('revision')) is not int or payload['revision']<1: raise Stop('Positive revision required')
        if len(json.dumps(payload).encode())>150000: raise Stop('Change input too large')
        clean={k:payload[k] for k in required};clean.update(revision=payload['revision'],kind=payload.get('kind','breaking'),proposed_files=payload.get('proposed_files',{}))
        clean['diff_digest']=digest(clean['proposed_diff'])
        clean['input_digest']=digest(clean)
        with self.transaction():
            prior=[c for c in self.rows('changes') if c['change_id']==clean['change_id']]
            for c in prior:
                if c['revision']==clean['revision']:
                    if c['input_digest']==clean['input_digest']: return c
                    raise Stop('Changed input requires a new revision')
            if prior and max(c['revision'] for c in prior)>=clean['revision']: raise Stop('Obsolete revision')
            clean.update(id=uuid.uuid4().hex,mode='FIXTURE / CONTROL',created_at=now())
            self.invalidate(clean['change_id'],'NEW_REVISION');self.put('changes',clean);self.log(clean,'CHANGE_CREATED')
        return clean
    def enqueue(self,payload):
        if payload.get('operation') not in ('snapshot','analysis','prepare','verify') or payload.get('mode') not in MODES or not payload.get('idempotency_key'): raise Stop('Invalid operation, mode or idempotency key')
        with self.transaction():
            c=self.latest(payload['change_id']); request={**payload,'revision':c['revision'],'input_digest':c['input_digest']}
            for j in self.rows('jobs'):
                if j['idempotency_key']==payload['idempotency_key']:
                    if j['request_digest']!=digest(request): raise Stop('Idempotency key bound to different input')
                    return j
            if any(j['change_id']==c['change_id'] and j['revision']==c['revision'] and j['status'] in ('QUEUED','RUNNING') for j in self.rows('jobs')): raise Stop('Conflicting operation already pending')
            snapshots=[s for s in self.rows('snapshots') if s['change_id']==c['change_id'] and s['revision']==c['revision']]
            basis=snapshots[-1]['basis_digest'] if snapshots else None
            j=self.base(c,payload['mode'],operation=payload['operation'],status='QUEUED',error=None,result_id=None,idempotency_key=payload['idempotency_key'],request_digest=digest(request),basis_digest=basis)
            self.put('jobs',j);self.log(c,'JOB_QUEUED',job_id=j['id'],mode=j['mode'])
            return j
    def is_current(self,job):
        c=self.latest(job['change_id'])
        snaps=[s for s in self.rows('snapshots') if s['change_id']==c['change_id'] and s['revision']==c['revision']]
        return c['input_digest']==job['input_digest'] and (job['operation']=='snapshot' or (snaps and snaps[-1]['basis_digest']==job['basis_digest']))
    def decide(self,p):
        with self.transaction():
            card=self.entity('cards',p['card_id'])
            if not card.get('current') or any(card[k]!=p.get(k) for k in ('revision','assessment_digest','team')): raise Stop('Stale or mismatched decision')
            if not p.get('actor') or p.get('decision') not in ('acknowledged','reviewed','request_changes','rejected'): raise Stop('Invalid decision')
            allowed={k:p.get(k,'') for k in ('card_id','revision','assessment_digest','team','actor','decision','comment')}
            for d in self.rows('decisions'):
                if d.get('decision_digest')==digest(allowed): return d
            for d in self.rows('decisions'):
                if d['card_id']==card['id'] and d.get('current'):d['current']=False;self.put('decisions',d)
            c=self.latest(card['change_id']); row=self.base(c,card['mode'],**allowed,decision_digest=digest(allowed),basis_digest=card['basis_digest'],current=True,grants_execution=False)
            self.put('decisions',row);self.log(c,'TEAM_DECISION',decision_id=row['id'],mode=card['mode'])
            return row
    def state(self):
        with self.lock: return {**{k:self.rows(k) for k in KINDS},'execution_permission':False,'demo_roles':True}
