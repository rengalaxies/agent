"""Private durable review/outbox coordination, not authentication or authority.

Callers must authenticate actors and recheck current run freshness/permissions.
Acceptance here means accepted_for_review, never production authorization.
SENDING survives restart without automatic retry: reconcile external effects.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .store import RunStore, _json, _timestamp


def _text(value, name, limit=512):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(f"invalid {name}")
    return value


class WorkflowStore:
    """Own database; never pass a RunStore database path."""

    _connection = RunStore._connection

    def __init__(self, path: Path):
        self.path = Path(path)
        if self.path.is_symlink() or (self.path.exists() and not self.path.is_file()):
            raise ValueError('state path must be a regular file, not a symlink')
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            descriptor = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(descriptor)
        with self._connection() as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='runs'").fetchone():
                raise ValueError('workflow state must use its own database')
            c.executescript('''
                CREATE TABLE IF NOT EXISTS workflows (
                    run_id TEXT PRIMARY KEY, package_digest TEXT NOT NULL,
                    owners TEXT NOT NULL, acceptor TEXT NOT NULL,
                    status TEXT NOT NULL, reviews TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_history (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES workflows(run_id),
                    timestamp TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS workflow_outbox (
                    key TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES workflows(run_id),
                    kind TEXT NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL,
                    receipt TEXT, reason TEXT
                );
                CREATE TRIGGER IF NOT EXISTS workflow_history_no_update
                BEFORE UPDATE ON workflow_history BEGIN SELECT RAISE(ABORT,'append-only'); END;
                CREATE TRIGGER IF NOT EXISTS workflow_history_no_delete
                BEFORE DELETE ON workflow_history BEGIN SELECT RAISE(ABORT,'append-only'); END;
            ''')
            columns = {r['name'] for r in c.execute('PRAGMA table_info(workflows)')}
            if 'final_review' not in columns:
                c.execute('ALTER TABLE workflows ADD COLUMN final_review TEXT')

    @staticmethod
    def _history(c, run_id, kind, payload):
        c.execute("INSERT INTO workflow_history(run_id,timestamp,kind,payload) VALUES (?,?,?,?)",
                  (run_id, _timestamp(), kind, _json(payload)))

    @staticmethod
    def _row(c, run_id):
        row = c.execute("SELECT * FROM workflows WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return dict(row)

    @staticmethod
    def _active(row):
        if row['status'] == 'STALE':
            raise ValueError('workflow is stale')

    def register(self, run_id, package_digest: str, owners: dict[str, str], acceptor: str) -> dict:
        _text(run_id, 'run_id'); _text(package_digest, 'package_digest'); _text(acceptor, 'acceptor')
        if not isinstance(owners, dict) or not owners:
            raise ValueError('owners must be a non-empty component to actor mapping')
        for component, actor in owners.items():
            _text(component, 'component'); _text(actor, 'owner')
        encoded = _json(owners)
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT * FROM workflows WHERE run_id=?', (run_id,)).fetchone()
            if existing:
                if (existing['package_digest'], existing['owners'], existing['acceptor']) != (package_digest, encoded, acceptor):
                    raise ValueError('registered workflow cannot be replaced')
            else:
                c.execute('INSERT INTO workflows(run_id,package_digest,owners,acceptor,status,reviews) VALUES (?,?,?,?,?,?)',
                          (run_id, package_digest, encoded, acceptor, 'PENDING', '{}'))
                self._history(c, run_id, 'REGISTERED', {'package_digest': package_digest})
        return self.get(run_id)

    def review(self, run_id, actor, decision, package_digest, comment='') -> dict:
        _text(actor, 'actor')
        if decision not in {'approve', 'reject'}:
            raise ValueError('invalid decision')
        if not isinstance(comment, str) or len(comment) > 4000:
            raise ValueError('comment exceeds limit')
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._row(c, run_id); self._active(row)
            if package_digest != row['package_digest']:
                raise ValueError('package digest mismatch')
            owners = json.loads(row['owners']); reviews = json.loads(row['reviews'])
            components = [k for k, v in owners.items() if v == actor]
            if not components and actor != row['acceptor']:
                raise ValueError('actor has no review role')
            # When acceptor also owns components, their first approval approves
            # those components; a subsequent approval performs final acceptance.
            pending_owned = any(reviews.get(k, {}).get('decision') != 'approve' for k in components)
            final = actor == row['acceptor'] and not pending_owned
            if final and decision == 'approve' and not all(reviews.get(k, {}).get('decision') == 'approve' for k in owners):
                raise ValueError('all owners must approve before acceptance')
            item = {'actor': actor, 'decision': decision, 'comment': comment, 'package_digest': package_digest}
            final_review = json.loads(row['final_review']) if row['final_review'] else None
            changed = any(reviews.get(component) != item for component in components)
            for component in components:
                reviews[component] = item
            if final:
                final_review = item
            elif changed and final_review and final_review['decision'] == 'approve':
                final_review = None
            rejected = any(r['decision'] == 'reject' for r in reviews.values()) or (final_review and final_review['decision'] == 'reject')
            accepted = final_review and final_review['decision'] == 'approve' and all(reviews.get(k, {}).get('decision') == 'approve' for k in owners)
            status = 'REJECTED' if rejected else ('ACCEPTED_FOR_REVIEW' if accepted else 'PENDING')
            c.execute('UPDATE workflows SET status=?,reviews=?,final_review=? WHERE run_id=?',
                      (status, _json(reviews), _json(final_review) if final_review else None, run_id))
            self._history(c, run_id, 'REVIEWED', {**item, 'components': components, 'final': final})
        return self.get(run_id)

    def invalidate(self, run_id, reason) -> dict:
        _text(reason, 'reason', 4000)
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE'); row = self._row(c, run_id)
            if row['status'] != 'STALE':
                c.execute("UPDATE workflows SET status='STALE',reviews='{}',final_review=NULL WHERE run_id=?", (run_id,))
                c.execute("UPDATE workflow_outbox SET status='CANCELLED',reason=? WHERE run_id=? AND status='PENDING'", (reason, run_id))
                self._history(c, run_id, 'INVALIDATED', {'reason': reason})
        return self.get(run_id)

    def reopen(self, run_id, package_digest) -> dict:
        """Reopen same package after caller rechecks freshness and authority.

        Prior approvals never return. Cancelled entries require explicit enqueue.
        """
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._row(c, run_id)
            if row['status'] != 'STALE' or package_digest != row['package_digest']:
                raise ValueError('only the same stale package can be reopened')
            c.execute("UPDATE workflows SET status='PENDING',reviews='{}',final_review=NULL WHERE run_id=?", (run_id,))
            self._history(c, run_id, 'REOPENED', {'package_digest': package_digest})
        return self.get(run_id)

    def get(self, run_id) -> dict:
        with self._connection() as c:
            c.execute('BEGIN'); result = self._row(c, run_id)
            for name in ('owners', 'reviews'):
                result[name] = json.loads(result[name])
            result['final_review'] = json.loads(result['final_review']) if result['final_review'] else None
            result['history'] = [{**dict(r), 'payload': json.loads(r['payload'])} for r in c.execute(
                'SELECT sequence,timestamp,kind,payload FROM workflow_history WHERE run_id=? ORDER BY sequence', (run_id,))]
            result['outbox'] = [self._delivery(r) for r in c.execute('SELECT * FROM workflow_outbox WHERE run_id=? ORDER BY key', (run_id,))]
            return result

    @staticmethod
    def _delivery(row):
        result = dict(row); result['payload'] = json.loads(result['payload'])
        result['receipt'] = json.loads(result['receipt']) if result['receipt'] else None
        return result

    def enqueue(self, run_id, key, kind, payload: dict) -> dict:
        _text(key, 'key')
        if kind not in {'pr', 'notification'}:
            raise ValueError('invalid delivery kind')
        encoded = _json(payload)
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._row(c, run_id); self._active(row)
            if row['status'] == 'REJECTED':
                raise ValueError('rejected workflow cannot enqueue effects')
            old = c.execute('SELECT * FROM workflow_outbox WHERE key=?', (key,)).fetchone()
            if old:
                if (old['run_id'], old['kind'], old['payload']) != (run_id, kind, encoded):
                    raise ValueError('outbox key collision')
                if old['status'] == 'CANCELLED':
                    # Invalidation only cancels PENDING, never claimed effects.
                    # Explicit preparation after reopening may restore this item.
                    c.execute("UPDATE workflow_outbox SET status='PENDING',reason=NULL WHERE key=?", (key,))
                    self._history(c, run_id, 'REQUEUED', {'key': key, 'kind': kind})
                    old = c.execute('SELECT * FROM workflow_outbox WHERE key=?', (key,)).fetchone()
                return self._delivery(old)
            c.execute('INSERT INTO workflow_outbox(key,run_id,kind,payload,status) VALUES (?,?,?,?,?)', (key, run_id, kind, encoded, 'PENDING'))
            self._history(c, run_id, 'ENQUEUED', {'key': key, 'kind': kind})
            return self._delivery(c.execute('SELECT * FROM workflow_outbox WHERE key=?', (key,)).fetchone())

    def claim_delivery(self, key) -> dict:
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM workflow_outbox WHERE key=?', (key,)).fetchone()
            if row is None: raise KeyError(key)
            workflow = self._row(c, row['run_id']); self._active(workflow)
            if workflow['status'] == 'REJECTED':
                raise ValueError('rejected workflow cannot deliver effects')
            if row['status'] != 'PENDING':
                raise ValueError('delivery already claimed; reconcile rather than retry')
            c.execute("UPDATE workflow_outbox SET status='SENDING' WHERE key=?", (key,))
            self._history(c, row['run_id'], 'DELIVERY_CLAIMED', {'key': key})
            return self._delivery(c.execute('SELECT * FROM workflow_outbox WHERE key=?', (key,)).fetchone())

    def delivered(self, key, receipt) -> None:
        self._finish_delivery(key, 'DELIVERED', _json(receipt), None)

    def uncertain(self, key, reason) -> None:
        self._finish_delivery(key, 'UNKNOWN', None, _text(reason, 'reason', 4000))

    def _finish_delivery(self, key, status, receipt, reason):
        with self._connection() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT * FROM workflow_outbox WHERE key=?', (key,)).fetchone()
            if row is None: raise KeyError(key)
            if row['status'] == status and row['receipt'] == receipt and row['reason'] == reason:
                return
            if row['status'] != 'SENDING': raise ValueError('delivery must be SENDING')
            c.execute('UPDATE workflow_outbox SET status=?,receipt=?,reason=? WHERE key=?', (status, receipt, reason, key))
            self._history(c, row['run_id'], status, {'key': key, 'receipt': json.loads(receipt) if receipt else None, 'reason': reason})
