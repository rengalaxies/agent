"""Small sequential interview workspace registry; no shared business state or inference.

Call ``workspace`` once per active session and reuse its Store/Worker. Research
observations are opt-in, enum-only summaries of the existing technical audit.
They deliberately exclude actor, comment, titles, diffs, errors and payloads.
"""
import json
import re
import sqlite3
import threading
import uuid
from pathlib import Path
from lab.runtime.core import Stop, now
from .store import Store, MODES

SCENARIO_VERSION = 'interview-1'
CONSENT_VERSION = 'minimal-observations-1'
CONSENT_NOTICE = ('Optional research recording: random session ID, scenario version, mode, '
                  'timestamps, action/error/decision categories and moderator assistance. '
                  'No names, email, free text, keys or screen capture. Technical execution '
                  'audit is separate. You may decline or delete this session research export.')
SCENARIOS = {
    'confirmed': {'reuses':['A'], 'initial_state':'Empty workspace; load existing breaking example, collect current sources, explicitly choose replay/control.',
                  'expected':'Billing and analytics cards show evidence, risk/reproduction and next action; acknowledgement never permits apply.'},
    'unknown-owner': {'reuses':['C'], 'initial_state':'Empty workspace; use the existing C missing-owner controlled catalog profile.',
                      'expected':'Owner uncertainty is explicit and the coordinator receives the question; no invented owner.'},
    'stale': {'reuses':['D','E'], 'initial_state':'Empty workspace; run existing A then create revision 2 or recollect changed supported basis.',
              'expected':'Earlier cards, decisions and PASS remain history only; fresh assessment required.'},
}
ACTIONS = {'CHANGE_CREATED','JOB_QUEUED','JOB_COMPLETED','JOB_STOPPED','TEAM_DECISION',
           'SCENARIO_STARTED','EXPLICIT_REPLAY_SELECTED','MODERATOR_HELP','SESSION_ENDED'}
DECISIONS = {'acknowledged','reviewed','request_changes','rejected'}
HELP = {'navigation','terminology','technical_error','scenario_instruction','none'}
ERRORS = {'NONE','JOB_BLOCKED','JOB_FAILED','UNKNOWN','API_ERROR','LIVE_UNAVAILABLE'}

class Sessions:
    def __init__(self, root):
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True)
        self.lock=threading.RLock();self.cache={}
        self.db=sqlite3.connect(self.root/'sessions.sqlite',check_same_thread=False,isolation_level=None)
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY, data TEXT NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS observations(session_id TEXT, event_id TEXT, data TEXT, UNIQUE(session_id,event_id))')
        self.db.execute('CREATE TABLE IF NOT EXISTS technical_audit(id INTEGER PRIMARY KEY, session_id TEXT, time TEXT, action TEXT)')
    def _audit(self,sid,action):
        self.db.execute('INSERT INTO technical_audit(session_id,time,action) VALUES(?,?,?)',(sid,now(),action))
    def _save(self,row):
        self.db.execute('INSERT OR REPLACE INTO sessions VALUES(?,?)',(row['session_id'],json.dumps(row)))
    def get(self,sid):
        if not isinstance(sid,str) or not re.fullmatch('[0-9a-f]{32}',sid):raise Stop('Invalid session ID')
        with self.lock:
            row=self.db.execute('SELECT data FROM sessions WHERE id=?',(sid,)).fetchone()
            if not row:raise Stop('Unknown session')
            return json.loads(row[0])
    def create(self,scenario,mode='REPLAY'):
        if scenario not in SCENARIOS or mode not in MODES:raise Stop('Unknown scenario or mode')
        with self.lock:
            sid=uuid.uuid4().hex
            row={'session_id':sid,'scenario':scenario,'scenario_version':SCENARIO_VERSION,'mode':mode,
                 'created_at':now(),'status':'ACTIVE','generation':1,'research_consent':False,'consent_version':None}
            self._save(row);self._audit(sid,'SESSION_CREATED');self.workspace(sid)
            return row
    def paths(self,sid):
        row=self.get(sid);directory=self.root/sid/('generation-'+str(row['generation']))
        return directory/'state.sqlite',directory/'artifacts'
    def workspace(self,sid):
        with self.lock:
            row=self.get(sid)
            if row['status']!='ACTIVE':raise Stop('Session ended')
            key=(sid,row['generation'])
            if key not in self.cache:
                db,artifacts=self.paths(sid);artifacts.mkdir(parents=True,exist_ok=True)
                self.cache[key]=Store(db)
            return self.cache[key]
    def consent(self,sid,enabled,notice_version):
        if type(enabled) is not bool or notice_version!=CONSENT_VERSION:raise Stop('Explicit consent and current notice version required')
        with self.lock:
            row=self.get(sid);row.update(research_consent=enabled,consent_version=notice_version,consent_at=now())
            self._save(row);self._audit(sid,'RESEARCH_CONSENT_ENABLED' if enabled else 'RESEARCH_CONSENT_DISABLED')
            return row
    def record(self,sid,event_id,action,*,error='NONE',decision=None,help_category=None,mode=None):
        # No **kwargs: arbitrary notes/payload/actor cannot enter the research schema.
        if not isinstance(event_id,str) or not re.fullmatch('[0-9a-f]{32}',event_id):raise Stop('Opaque event ID required')
        if (mode is not None and mode not in MODES) or action not in ACTIONS or error not in ERRORS or (decision is not None and decision not in DECISIONS) or (help_category is not None and help_category not in HELP):raise Stop('Unsupported observation category')
        with self.lock:
            row=self.get(sid)
            if row['status']!='ACTIVE':raise Stop('Session ended')
            if not row['research_consent']:return {'recorded':False,'reason':'CONSENT_NOT_ENABLED'}
            event={k:row[k] for k in ('session_id','scenario','scenario_version','mode','generation')}
            event.update(time=now(),action=action,error=error,decision=decision,moderator_help=help_category)
            if mode is not None:event['mode']=mode
            self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?)',(sid,event_id,json.dumps(event)))
            return {'recorded':True}
    def sync_audit(self,sid):
        """Project only allowlisted categories, never copy raw journal or free text.

        Events preceding consent are not collected retrospectively.
        """
        row=self.get(sid)
        if not row['research_consent']:return
        store=self.workspace(sid)
        for event in store.rows('journal'):
            if event['created_at']<row['consent_at'] or event.get('action') not in ACTIONS:continue
            decision=None
            if event['action']=='TEAM_DECISION':
                found=[d for d in store.rows('decisions') if d['id']==event.get('decision_id')]
                if found:decision=found[0]['decision']
            error='NONE'
            if event['action']=='JOB_STOPPED':
                jobs=[j for j in store.rows('jobs') if j['id']==event.get('job_id')]
                error='JOB_FAILED' if jobs and jobs[0]['status']=='FAILED' else 'JOB_BLOCKED'
            self.record(sid,event['id'],event['action'],error=error,decision=decision,mode=event['mode'])
    def export(self,sid):
        with self.lock:
            row=self.get(sid)
            if row['status']=='ACTIVE':self.sync_audit(sid)
            events=[json.loads(r[0]) for r in self.db.execute('SELECT data FROM observations WHERE session_id=? ORDER BY rowid',(sid,))]
            self._audit(sid,'RESEARCH_EXPORTED')
            return {'schema':'interview-observations-1','session_id':sid,'scenario_version':row['scenario_version'],
                    'consent_enabled':row['research_consent'],'observations':events,
                    'interpretation':'Observed actions only; no inference of understanding or time saved.'}
    def delete_research(self,sid):
        with self.lock:
            row=self.get(sid);self.db.execute('DELETE FROM observations WHERE session_id=?',(sid,))
            row.update(research_consent=False,consent_version=None);row.pop('consent_at',None)
            self._save(row);self._audit(sid,'RESEARCH_DELETED_TECHNICAL_AUDIT_RETAINED')
            return {'deleted':True,'technical_audit_retained':True}
    def reset(self,sid):
        """New empty generation, retain selected session history/evidence, never others.

        Caller must stop/remove its Worker before reset; active jobs prohibit reset.
        """
        with self.lock:
            store=self.workspace(sid)
            if any(j['status'] in ('QUEUED','RUNNING') for j in store.rows('jobs')):raise Stop('Stop/reconcile pending work before reset')
            row=self.get(sid);row['generation']+=1;self._save(row);self._audit(sid,'SESSION_RESET')
            self.workspace(sid);return row
    def end(self,sid):
        with self.lock:
            self.sync_audit(sid)
            row=self.get(sid);row['status']='ENDED';row['ended_at']=now();self._save(row);self._audit(sid,'SESSION_ENDED')
            return row
    def scenario(self,sid):
        row=self.get(sid)
        return {'id':row['scenario'],'version':SCENARIO_VERSION,**SCENARIOS[row['scenario']],
                'origin':'Existing frozen integrated-path-1 A/C/D/E; saved model results explicitly REPLAY; current collection LIVE RUN; missing owner CONTROL.',
                'limitations':['Declared owners, narrow discovery, demo roles, one worker; no deployment authority.',
                               'Starting a session does not claim a scenario ran or seed unverified PASS.'],
                'cleanup':'Stop/reconcile pending jobs; reset only this session to an empty generation; historical evidence retained. Delete research separately.'}


def session_options(manager, sid, worker_options=None):
    """Reuse scenario C's declared-catalog mutation, not a new discovery algorithm.

    DB and broker collection remains real; the owner catalog projection is
    explicitly CONTROL and the derived basis includes that changed catalog.
    """
    import copy
    from lab.runtime.core import digest
    options=dict(worker_options or {})
    if manager.get(sid)['scenario']!='unknown-owner':return options
    collector=options.get('collector')
    def missing_owner():
        if collector is None:
            from .collectors import collect
            snapshot=collect()
        else:snapshot=collector()
        snapshot=copy.deepcopy(snapshot)
        owners=snapshot.get('owners')
        if not isinstance(owners,dict):raise Stop('Unknown-owner scenario requires collected declared owner catalog')
        original=snapshot['basis_digest']
        owners['bindings']=[b for b in owners.get('bindings',[]) if b.get('object_ref')!='lab/app/service.py#consume']
        snapshot['basis_digest']=digest({'collected_basis':original,'controlled_owners':owners,'scenario':SCENARIO_VERSION+':C'})
        snapshot['ownership_control']={'mode':'FIXTURE / CONTROL','source':'Existing scenario C declared catalog mutation',
                                       'removed_object_ref':'lab/app/service.py#consume','original_basis_digest':original}
        snapshot['edges']=[e for e in snapshot.get('edges',[]) if not (e.get('source_kind')=='owner_catalog' and e.get('source')=='lab/app/service.py#consume')]
        snapshot.setdefault('coverage_gaps',[]).append('Interview C ownership is FIXTURE / CONTROL: declared consume owner removed. Database/broker observations retain collector provenance.')
        return snapshot
    options['collector']=missing_owner
    return options
