"""Single-node trusted control registry. Not enterprise IAM or a distributed scheduler.

Every API call authenticates an opaque token; membership is exact, never inherited
from an organization or combined across departments. Control paths are supplied
only by an operator. Queue leases are fencing tokens, not automatic retry timers.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import uuid

from .adapters import read_repository_file
from .models import TransitionSpec
from .run_cli import operator_path, read_operator_file
from .runtime import run_transition
from .store import RunStore
from .verification import TrustPolicy, digest_bytes, load_json
from .verify_cli import TrustConfig

PERMISSIONS = frozenset({'read', 'enqueue', 'work'})


def _now():
    return datetime.now(timezone.utc).timestamp()


def _hash(token):
    if not isinstance(token, str) or len(token) < 32:
        raise PermissionError('invalid_identity')
    return hashlib.sha256(token.encode()).hexdigest()


def _json(value):
    result = json.dumps(value, sort_keys=True, allow_nan=False)
    if len(result.encode()) > 1024 * 1024:
        raise ValueError('oversized_record')
    return result


def _name(value):
    if not isinstance(value, str) or not value or len(value) > 128 or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_.:' for c in value):
        raise ValueError('invalid_identifier')
    return value


class ControlPlane:
    def __init__(self, path, clock=_now):
        self.path = operator_path(path)
        self.clock = clock
        if self.path.exists() and not self.path.is_file():
            raise ValueError('invalid_registry')
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self._db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS identities(actor TEXT PRIMARY KEY, token TEXT UNIQUE NOT NULL, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0, operator INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS scopes(id TEXT PRIMARY KEY, kind TEXT NOT NULL, parent TEXT REFERENCES scopes(id));
                CREATE TABLE IF NOT EXISTS memberships(actor TEXT REFERENCES identities(actor), scope TEXT REFERENCES scopes(id), permissions TEXT NOT NULL, expires REAL NOT NULL, PRIMARY KEY(actor,scope));
                CREATE TABLE IF NOT EXISTS bindings(id TEXT PRIMARY KEY, scope TEXT REFERENCES scopes(id), config TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, binding TEXT REFERENCES bindings(id), request_key TEXT NOT NULL, status TEXT NOT NULL, worker TEXT, lease TEXT, deadline REAL, result TEXT, retry_of TEXT, retry_key TEXT, UNIQUE(binding,request_key));
                CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT, at REAL NOT NULL, actor TEXT NOT NULL, scope TEXT, kind TEXT NOT NULL, details TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit BEGIN SELECT RAISE(ABORT,'append-only audit'); END;
                CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit BEGIN SELECT RAISE(ABORT,'append-only audit'); END;
            ''')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(tasks)')}
            for column in ('retry_of', 'retry_key'):
                if column not in columns:
                    db.execute(f'ALTER TABLE tasks ADD COLUMN {column} TEXT')

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA journal_mode=WAL')
            db.execute('PRAGMA synchronous=FULL')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _identity(self, db, token):
        row = db.execute('SELECT * FROM identities WHERE token=?', (_hash(token),)).fetchone()
        if row is None or row['revoked'] or row['expires'] <= self.clock():
            raise PermissionError('identity_revoked_expired_or_unknown')
        return row

    def _authorize(self, db, token, scope=None, permission=None, operator=False):
        row = self._identity(db, token)
        if operator:
            if not row['operator']:
                raise PermissionError('operator_required')
        elif scope is not None:
            membership = db.execute('SELECT * FROM memberships WHERE actor=? AND scope=?', (row['actor'], scope)).fetchone()
            if membership is None or membership['expires'] <= self.clock() or permission not in json.loads(membership['permissions']):
                raise PermissionError('scope_permission_required')
        return row['actor']

    def _audit(self, db, actor, scope, kind, details):
        db.execute('INSERT INTO audit(at,actor,scope,kind,details) VALUES (?,?,?,?,?)', (self.clock(), actor, scope, kind, _json(details)))

    def bootstrap(self, token, actor='operator'):
        with self._db() as db:
            if db.execute('SELECT 1 FROM identities').fetchone():
                raise ValueError('already_initialized')
            db.execute('INSERT INTO identities(actor,token,expires,operator) VALUES (?,?,?,1)', (_name(actor), _hash(token), self.clock()+365*86400))
            self._audit(db, actor, None, 'BOOTSTRAP', {})

    def recover_restored(self, new_token, new_actor, *, confirmed_authority=False):
        """OS-operator recovery after restore, never reactivating old identities.

        This unauthenticated local provisioning entry point works only once for
        a restored registry marked by state_transfer. It is not an HTTP route.
        """
        if confirmed_authority is not True:
            raise PermissionError('explicit_restored_authority_attestation_required')
        with self._db() as db:
            if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='restore_quarantine'").fetchone():
                raise ValueError('registry_not_restored')
            marker = db.execute('SELECT acknowledged FROM restore_quarantine WHERE singleton=1').fetchone()
            if marker is None or marker['acknowledged'] != 0:
                raise ValueError('restore_recovery_already_acknowledged_or_unavailable')
            actor, token_hash = _name(new_actor), _hash(new_token)
            if db.execute('SELECT 1 FROM identities WHERE actor=? OR token=?', (actor, token_hash)).fetchone():
                raise ValueError('fresh_identity_and_token_required')
            db.execute('INSERT INTO identities(actor,token,expires,operator) VALUES (?,?,?,1)', (actor, token_hash, self.clock()+365*86400))
            db.execute('UPDATE restore_quarantine SET acknowledged=1 WHERE singleton=1')
            self._audit(db, actor, None, 'RESTORED_AUTHORITY_RECOVERED', {'requires_fresh_memberships_and_binding_review': True})

    def add_scope(self, token, scope_id, kind, parent=None):
        with self._db() as db:
            actor = self._authorize(db, token, operator=True)
            expected = {'organization': None, 'division': 'organization', 'department': 'division'}
            if kind not in expected:
                raise ValueError('invalid_scope_kind')
            prow = db.execute('SELECT kind FROM scopes WHERE id=?', (parent,)).fetchone() if parent else None
            if (expected[kind] is None and parent is not None) or (expected[kind] is not None and (prow is None or prow['kind'] != expected[kind])):
                raise ValueError('invalid_scope_parent')
            db.execute('INSERT INTO scopes VALUES (?,?,?)', (_name(scope_id), kind, parent))
            self._audit(db, actor, scope_id, 'SCOPE_REGISTERED', {'kind': kind, 'parent': parent})

    def add_identity(self, token, new_token, actor, expires_at):
        with self._db() as db:
            admin = self._authorize(db, token, operator=True)
            if not self.clock() < expires_at <= self.clock()+365*86400:
                raise ValueError('invalid_identity_expiry')
            db.execute('INSERT INTO identities(actor,token,expires) VALUES (?,?,?)', (_name(actor), _hash(new_token), expires_at))
            self._audit(db, admin, None, 'IDENTITY_REGISTERED', {'actor': actor})

    def grant(self, token, actor, scope_id, permissions, expires_at):
        with self._db() as db:
            admin = self._authorize(db, token, operator=True)
            permissions = set(permissions)
            if not permissions or not permissions <= PERMISSIONS or not self.clock() < expires_at <= self.clock()+365*86400:
                raise ValueError('invalid_membership')
            db.execute('INSERT INTO memberships VALUES (?,?,?,?) ON CONFLICT(actor,scope) DO UPDATE SET permissions=excluded.permissions,expires=excluded.expires', (actor, scope_id, _json(sorted(permissions)), expires_at))
            self._audit(db, admin, scope_id, 'MEMBERSHIP_GRANTED', {'actor': actor, 'permissions': sorted(permissions)})

    def revoke(self, token, actor):
        with self._db() as db:
            admin = self._authorize(db, token, operator=True)
            if admin == actor:
                raise ValueError('cannot_revoke_self')
            if not db.execute('UPDATE identities SET revoked=1 WHERE actor=?', (actor,)).rowcount:
                raise KeyError('unknown_identity')
            self._audit(db, admin, None, 'IDENTITY_REVOKED', {'actor': actor})

    def register(self, token, scope_id, binding_id, *, repository, expectations, state, worker_actor, transition=None, fixtures=None, trust=None, profile='sql-window/1', approved_suite_sha256=None, changes_path=None):
        with self._db() as db:
            self._authorize(db, token, operator=True)
        paths = {key: str(operator_path(value).resolve()) for key, value in locals().copy().items() if key in {'repository', 'transition', 'expectations', 'fixtures', 'trust', 'state', 'changes_path'} and value is not None}
        root = Path(paths['repository']).resolve()
        if profile not in {'sql-window/1', 'contract-python-sql/1'}:
            raise ValueError('unsupported_profile')
        if profile == 'sql-window/1' and (not all(key in paths for key in ('transition', 'fixtures', 'trust')) or not Path(paths['fixtures']).is_dir()):
            raise ValueError('sql_control_artifacts_required')
        if not root.is_dir():
            raise ValueError('invalid_binding_directory')
        for key, value in paths.items():
            if key != 'repository' and Path(value).resolve().is_relative_to(root):
                raise ValueError('control_artifact_inside_repository')
        if self.path.resolve().is_relative_to(root):
            raise ValueError('registry_inside_repository')
        if changes_path is not None and profile != 'contract-python-sql/1':
            raise ValueError('changes_only_supported_for_contract_profile')
        changes_sha = digest_bytes(read_operator_file(paths['changes_path'])) if changes_path is not None else None
        suite_sha = digest_bytes(read_operator_file(paths['expectations']))
        if profile == 'sql-window/1':
            spec_data = read_operator_file(paths['transition'])
            spec = TransitionSpec.model_validate(load_json(spec_data))
            transition_id, spec_sha = spec.transition_id, digest_bytes(spec_data)
        else:
            if approved_suite_sha256 != suite_sha:
                raise ValueError('explicit_independent_suite_approval_required')
            transition_id, spec_sha = 'contract:' + _name(binding_id), None
        config = {**paths, 'profile': profile, 'changes_sha256': changes_sha, 'worker_actor': _name(worker_actor), 'transition_id': transition_id, 'spec_sha256': spec_sha, 'suite_sha256': suite_sha}
        with self._db() as db:
            actor = self._authorize(db, token, operator=True)
            if db.execute('SELECT 1 FROM identities WHERE actor=? AND revoked=0', (worker_actor,)).fetchone() is None:
                raise ValueError('unknown_worker')
            # A bound namespace is unique: identical transition IDs cannot cross departments or states.
            for row in db.execute('SELECT config FROM bindings'):
                old = json.loads(row['config'])
                if old['transition_id'] == transition_id or old['state'] == paths['state']:
                    raise ValueError('binding_namespace_conflict')
            db.execute('INSERT INTO bindings VALUES (?,?,?)', (_name(binding_id), scope_id, _json(config)))
            self._audit(db, actor, scope_id, 'TRANSITION_REGISTERED', {'binding_id': binding_id, 'spec_sha256': config['spec_sha256'], 'suite_sha256': config['suite_sha256']})

    def rebind_worker(self, token, binding_id, new_worker, *, confirmed_binding_review=False):
        """Re-authorize one reviewed binding; preserve independent input pins."""
        if confirmed_binding_review is not True:
            raise PermissionError('explicit_binding_review_required')
        with self._db() as db:
            actor = self._authorize(db, token, operator=True)
            row = db.execute('SELECT * FROM bindings WHERE id=?', (binding_id,)).fetchone()
            if row is None:
                raise KeyError('unknown_binding')
            worker = db.execute('SELECT * FROM identities WHERE actor=?', (new_worker,)).fetchone()
            membership = db.execute('SELECT * FROM memberships WHERE actor=? AND scope=?', (new_worker, row['scope'])).fetchone()
            if worker is None or worker['revoked'] or worker['expires'] <= self.clock() or membership is None or membership['expires'] <= self.clock() or 'work' not in json.loads(membership['permissions']):
                raise PermissionError('fresh_scoped_worker_authority_required')
            if db.execute("SELECT 1 FROM tasks WHERE binding=? AND status='RUNNING'", (binding_id,)).fetchone():
                raise ValueError('binding_has_inflight_task')
            config = json.loads(row['config'])
            for key in ('repository', 'transition', 'expectations', 'fixtures', 'trust', 'state', 'changes_path'):
                if key in config:
                    operator_path(config[key])
            if digest_bytes(read_operator_file(config['expectations'])) != config['suite_sha256']:
                raise ValueError('registered_input_changed')
            if config.get('spec_sha256') and digest_bytes(read_operator_file(config['transition'])) != config['spec_sha256']:
                raise ValueError('registered_input_changed')
            if config.get('changes_sha256') and digest_bytes(read_operator_file(config['changes_path'])) != config['changes_sha256']:
                raise ValueError('registered_intent_changed')
            old_worker = config['worker_actor']
            config['worker_actor'] = _name(new_worker)
            db.execute('UPDATE bindings SET config=? WHERE id=?', (_json(config), binding_id))
            self._audit(db, actor, row['scope'], 'BINDING_REVIEWED_AND_REBOUND', {'binding_id': binding_id, 'old_worker': old_worker, 'new_worker': new_worker, 'suite_sha256': config['suite_sha256'], 'spec_sha256': config['spec_sha256'], 'runtime_trust_grants_require_independent_review': True})

    def enqueue(self, token, binding_id, idempotency_key):
        _name(idempotency_key)
        with self._db() as db:
            row = db.execute('SELECT scope FROM bindings WHERE id=?', (binding_id,)).fetchone()
            if row is None:
                raise KeyError('unknown_binding')
            actor = self._authorize(db, token, row['scope'], 'enqueue')
            existing = db.execute('SELECT id,status FROM tasks WHERE binding=? AND request_key=?', (binding_id, idempotency_key)).fetchone()
            if existing:
                return dict(existing)
            task_id = uuid.uuid4().hex
            db.execute('INSERT INTO tasks(id,binding,request_key,status) VALUES (?,?,?,?)', (task_id, binding_id, idempotency_key, 'QUEUED'))
            self._audit(db, actor, row['scope'], 'TASK_ENQUEUED', {'task_id': task_id, 'binding_id': binding_id})
            return {'id': task_id, 'status': 'QUEUED'}

    def retry(self, token, task_id, new_key):
        """Explicit operator retry of a recorded terminal runtime failure.

        A crashed/expired lease stays UNKNOWN; a fresh key never resolves it.
        """
        _name(new_key)
        if len(new_key) < 8:
            raise ValueError('retry_key_too_short')
        with self._db() as db:
            actor = self._authorize(db, token, operator=True)
            prior = db.execute('SELECT tasks.*,bindings.scope FROM tasks JOIN bindings ON bindings.id=tasks.binding WHERE tasks.id=?', (task_id,)).fetchone()
            if prior is None:
                raise KeyError('unknown_task')
            self._authorize(db, token, prior['scope'], 'enqueue')
            result = json.loads(prior['result']) if prior['result'] else {}
            if prior['status'] not in {'STOP', 'FAIL'} or not result.get('run_id') or not result.get('context_sha256'):
                raise ValueError('retry_requires_recorded_terminal_runtime_failure')
            existing = db.execute('SELECT id,status,retry_of FROM tasks WHERE binding=? AND request_key=?', (prior['binding'], new_key)).fetchone()
            if existing:
                if existing['retry_of'] != result['run_id']:
                    raise ValueError('idempotency_payload_conflict')
                return {'id': existing['id'], 'status': existing['status']}
            task_id = uuid.uuid4().hex
            db.execute('INSERT INTO tasks(id,binding,request_key,status,retry_of,retry_key) VALUES (?,?,?,?,?,?)', (task_id, prior['binding'], new_key, 'QUEUED', result['run_id'], new_key))
            self._audit(db, actor, prior['scope'], 'EXPLICIT_RETRY_ENQUEUED', {'task_id': task_id, 'prior_run_id': result['run_id']})
            return {'id': task_id, 'status': 'QUEUED'}

    def _claim(self, token, lease_seconds):
        if not isinstance(lease_seconds, int) or not 1 <= lease_seconds <= 3600:
            raise ValueError('invalid_lease')
        with self._db() as db:
            actor = self._authorize(db, token)
            for row in db.execute("SELECT tasks.*,bindings.scope,bindings.config FROM tasks JOIN bindings ON bindings.id=tasks.binding WHERE status='RUNNING' AND deadline<=?", (self.clock(),)).fetchall():
                db.execute("UPDATE tasks SET status='UNKNOWN' WHERE id=?", (row['id'],))
                self._audit(db, 'lease-monitor', row['scope'], 'LEASE_EXPIRED_NO_RETRY', {'task_id': row['id']})
            rows = db.execute("SELECT tasks.*,bindings.scope,bindings.config FROM tasks JOIN bindings ON bindings.id=tasks.binding WHERE status='QUEUED' ORDER BY tasks.rowid").fetchall()
            for row in rows:
                config = json.loads(row['config'])
                if actor != config['worker_actor']:
                    continue
                try:
                    self._authorize(db, token, row['scope'], 'work')
                except PermissionError:
                    continue
                lease = uuid.uuid4().hex
                db.execute("UPDATE tasks SET status='RUNNING',worker=?,lease=?,deadline=? WHERE id=?", (actor, lease, self.clock()+lease_seconds, row['id']))
                self._audit(db, actor, row['scope'], 'TASK_CLAIMED', {'task_id': row['id'], 'lease': lease})
                return {**dict(row), 'lease': lease, 'config': config}
            return None

    def work_once(self, token, lease_seconds=120):
        task = self._claim(token, lease_seconds)
        if task is None:
            return {'status': 'IDLE'}
        config = task['config']
        try:
            suite = read_operator_file(config['expectations'])
            if digest_bytes(suite) != config['suite_sha256']:
                raise ValueError('registered_input_changed')
            def check_authority():
                with self._db() as db:
                    self._authorize(db, token, task['scope'], 'work')
                    current = db.execute('SELECT status,lease,deadline FROM tasks WHERE id=?', (task['id'],)).fetchone()
                    if current['status'] != 'RUNNING' or current['lease'] != task['lease'] or current['deadline'] <= self.clock():
                        raise PermissionError('lease_unavailable')
            def policy_loader():
                check_authority()
                parsed = TrustConfig.model_validate(load_json(read_operator_file(config['trust'])))
                return TrustPolicy(**{key: getattr(parsed, key) for key in TrustConfig.model_fields})
            check_authority()
            if config.get('profile', 'sql-window/1') == 'contract-python-sql/1':
                from .contract_profile import check_profile, generate_candidate
                candidate = Path(config['repository'])
                if config.get('changes_path'):
                    changes = read_operator_file(config['changes_path'])
                    if digest_bytes(changes) != config['changes_sha256']:
                        raise ValueError('registered_intent_changed')
                    candidate_parent = operator_path(config['state'])/'candidates'
                    candidate_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    operator_path(candidate_parent)
                    candidate = candidate_parent/task['id']
                    generate_candidate(Path(config['repository']), candidate, load_json(changes))
                    check_authority()
                    if digest_bytes(read_operator_file(config['changes_path'])) != config['changes_sha256']:
                        raise ValueError('registered_intent_changed')
                result = check_profile(candidate, suite, config['suite_sha256'])
                if config.get('changes_path'):
                    if digest_bytes(read_operator_file(config['changes_path'])) != config['changes_sha256']:
                        raise ValueError('registered_intent_changed')
                    result['candidate_path'] = str(candidate)
                    result['intent_sha256'] = config['changes_sha256']
                result['verification_status'] = result['status']
                result['status'] = 'READY_FOR_REVIEW' if result['status'] == 'PASS' else result['status']
                result['transition_id'] = config['transition_id']
            else:
                spec_bytes = read_operator_file(config['transition'])
                if digest_bytes(spec_bytes) != config['spec_sha256']:
                    raise ValueError('registered_input_changed')
                spec = TransitionSpec.model_validate(load_json(spec_bytes))
                policy_loader()
                result = run_transition(Path(config['repository']), spec, suite, lambda uri: read_repository_file(Path(config['fixtures']), uri), policy_loader, RunStore(Path(config['state'])/'runs.sqlite3'), actor=config['worker_actor'], clock=lambda: datetime.fromtimestamp(self.clock(), timezone.utc), **({'retry_of': task['retry_of'], 'retry_key': task['retry_key']} if task.get('retry_of') else {}))
                policy_loader()
            check_authority()
            status = result['status']
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, sqlite3.Error):
            status, result = 'STOP', {'status': 'STOP', 'reason_codes': ['registered_input_or_authority_unavailable'], 'effects_authorized': False}
        with self._db() as db:
            row = db.execute('SELECT status,lease,deadline FROM tasks WHERE id=?', (task['id'],)).fetchone()
            if row['status'] != 'RUNNING' or row['lease'] != task['lease'] or row['deadline'] <= self.clock():
                db.execute("UPDATE tasks SET status='UNKNOWN' WHERE id=? AND status='RUNNING'", (task['id'],))
                self._audit(db, 'lease-monitor', task['scope'], 'COMPLETION_FENCED', {'task_id': task['id']})
                return {'id': task['id'], 'status': 'UNKNOWN', 'effects_authorized': False}
            try:
                self._authorize(db, token, task['scope'], 'work')
            except PermissionError:
                status, result = 'STOP', {'status': 'STOP', 'reason_codes': ['authority_revoked_before_commit'], 'effects_authorized': False}
            db.execute('UPDATE tasks SET status=?,result=? WHERE id=?', (status, _json(result), task['id']))
            self._audit(db, config['worker_actor'], task['scope'], 'TASK_FINISHED', {'task_id': task['id'], 'status': status})
        return {'id': task['id'], 'status': status, 'result': result}

    def history(self, token, scope_id):
        with self._db() as db:
            self._authorize(db, token, scope_id, 'read')
            tasks = [dict(row) for row in db.execute('SELECT tasks.id,binding,request_key,status,worker,deadline,result,retry_of,retry_key FROM tasks JOIN bindings ON bindings.id=tasks.binding WHERE bindings.scope=? ORDER BY tasks.rowid', (scope_id,))]
            for task in tasks:
                task['result'] = json.loads(task['result']) if task['result'] else None
            audit = [dict(row) for row in db.execute('SELECT seq,at,actor,kind,details FROM audit WHERE scope=? ORDER BY seq', (scope_id,))]
            return {'scope': scope_id, 'tasks': tasks, 'audit': audit}


def run_worker_loop(plane, token, *, max_jobs=10, max_seconds=60, poll_seconds=1,
                    monotonic=None, sleep=None):
    """Poll queued tasks autonomously within operator-set scheduling budgets.

    A running bounded profile finishes before the loop checks time again; this
    is not a process-killing timeout. Authority failures propagate immediately.
    UNKNOWN tasks remain fenced and are never requeued here.
    """
    import math
    import time
    if type(max_jobs) is not int or not 1 <= max_jobs <= 1000:
        raise ValueError('invalid_job_budget')
    for value, lower, upper in ((max_seconds, 0.01, 3600), (poll_seconds, 0.01, 5)):
        if type(value) not in (int, float) or not math.isfinite(value) or not lower <= value <= upper:
            raise ValueError('invalid_worker_time_budget')
    monotonic = monotonic or time.monotonic
    sleep = sleep or time.sleep
    deadline = monotonic() + max_seconds
    completed = []
    while len(completed) < max_jobs:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return {'status': 'WORKER_STOPPED', 'reason': 'time_budget', 'processed': completed}
        result = plane.work_once(token)
        if result['status'] == 'IDLE':
            remaining = deadline - monotonic()
            if remaining > 0:
                sleep(min(poll_seconds, remaining))
            continue
        completed.append({'id': result['id'], 'status': result['status']})
    return {'status': 'WORKER_STOPPED', 'reason': 'job_budget', 'processed': completed}
