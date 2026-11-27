"""Local pilot accounts and opaque durable sessions. No service credentials here."""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
from urllib.parse import urlsplit

USERNAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z')
SCOPE = re.compile(r'[a-f0-9]{64}\Z')
IDLE_SECONDS = 1200
SESSION_SECONDS = 28800
CHALLENGE_SECONDS = 300
_slots = threading.BoundedSemaphore(2)


class UIError(Exception):
    def __init__(self, code: str, status: int = 401):
        self.code, self.status = code, status
        super().__init__(code)


def private_file(path: Path, *, create=False):
    if os.name!='posix':raise ValueError('ui_posix_required')
    if path.is_symlink():
        raise ValueError('ui_private_file_required')
    if create and not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        os.close(fd)
    stat = path.stat()
    if not path.is_file() or stat.st_mode & 0o077 or stat.st_uid != os.getuid():
        raise ValueError('ui_private_file_required')
    if path.parent.stat().st_mode & 0o022:
        raise ValueError('ui_private_directory_required')


@dataclass(frozen=True)
class UISettings:
    database: Path
    origin: str
    allow_insecure_loopback: bool = False

    def __post_init__(self):
        if not isinstance(self.origin,str) or not isinstance(self.database,Path):raise ValueError('invalid_ui_settings')
        if not self.origin.isascii() or any(ord(c)<33 or ord(c)==127 for c in self.origin):raise ValueError('invalid_ui_settings')
        u = urlsplit(self.origin)
        if (type(self.allow_insecure_loopback) is not bool or not self.database.is_absolute()
                or not u.hostname or u.username or u.password or u.path or u.query or u.fragment
                or self.origin != self.origin.rstrip('/') or u.netloc != u.netloc.lower()
                or u.scheme not in ('https', 'http')):
            raise ValueError('invalid_ui_settings')
        # An insecure exception can never expose real deployment cookies to a LAN origin.
        if u.scheme == 'http' and not (self.allow_insecure_loopback and u.hostname == '127.0.0.1'):
            raise ValueError('ui_https_required')
        if self.allow_insecure_loopback and (u.scheme != 'http' or u.hostname != '127.0.0.1'):
            raise ValueError('invalid_loopback_exception')
        _ = u.port  # Reject malformed ports before serving.

    @property
    def secure(self): return not self.allow_insecure_loopback

    @property
    def cookie(self): return '__Host-impactmap_session' if self.secure else 'impactmap_loopback_session'

    def validate_bind(self,host):
        if self.allow_insecure_loopback and host!='127.0.0.1':raise ValueError('ui_loopback_bind_required')

    @property
    def challenge_cookie(self): return '__Host-impactmap_login' if self.secure else 'impactmap_loopback_login'

    @classmethod
    def load(cls, path):
        path = Path(path); private_file(path)
        data = json.loads(path.read_text())
        if not isinstance(data, dict) or set(data) - {'database','origin','allow_insecure_loopback'}:
            raise ValueError('invalid_ui_settings')
        if not isinstance(data.get('database'),str) or not isinstance(data.get('origin'),str):
            raise ValueError('invalid_ui_settings')
        return cls(database=Path(data['database']), origin=data['origin'],
                   allow_insecure_loopback=data.get('allow_insecure_loopback',False))


def _key(token):
    return hashlib.sha256(token.encode()).hexdigest()


def _derive(password, salt):
    return hashlib.scrypt(password.encode('utf-8'),salt=salt,n=32768,r=8,p=3,
                          maxmem=128*1024*1024,dklen=32)


def hash_password(password: str) -> str:
    if not isinstance(password,str) or not 12 <= len(password.encode('utf-8')) <= 1024:
        raise ValueError('invalid_password_length')
    salt = secrets.token_bytes(16)
    return 'scrypt-v1$'+salt.hex()+'$'+_derive(password,salt).hex()


def verify_password(password: str, encoded: str) -> bool:
    try:
        if not isinstance(password,str) or len(password.encode('utf-8'))>1024: return False
        kind,salt,expected = encoded.split('$')
        if kind!='scrypt-v1' or len(salt)!=32 or len(expected)!=64: return False
        return hmac.compare_digest(_derive(password,bytes.fromhex(salt)),bytes.fromhex(expected))
    except (ValueError,TypeError,UnicodeError):
        return False


@lru_cache(maxsize=1)
def _dummy(): return hash_password('not-a-real-account-password')


@dataclass(frozen=True)
class Actor:
    username: str
    role: str
    scope: str
    csrf: str
    expires_at: float
    valid_until: float


class AuthStore:
    def __init__(self, path: Path, *, clock=time.time, create=True):
        self.path,self.clock = Path(path),clock
        private_file(self.path,create=create)
        with self.transaction() as c:
            c.executescript('''
              CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, password TEXT NOT NULL,
                role TEXT NOT NULL, scope TEXT NOT NULL, version INTEGER NOT NULL, disabled INTEGER NOT NULL);
              CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY, username TEXT NOT NULL,
                version INTEGER NOT NULL, scope TEXT NOT NULL, csrf TEXT NOT NULL,
                created REAL NOT NULL, last_seen REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS challenges(token_hash TEXT PRIMARY KEY, csrf_hash TEXT NOT NULL, expires REAL NOT NULL);
              CREATE TABLE IF NOT EXISTS attempts(bucket TEXT NOT NULL, at REAL NOT NULL);
              CREATE INDEX IF NOT EXISTS attempts_due ON attempts(bucket,at);
              CREATE TABLE IF NOT EXISTS audit(seq INTEGER PRIMARY KEY AUTOINCREMENT,
                at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, outcome TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS ui_auth_meta(version INTEGER NOT NULL);
            ''')
            row=c.execute('SELECT version FROM ui_auth_meta').fetchone()
            if row is None:c.execute('INSERT INTO ui_auth_meta VALUES(1)')
            elif row[0]!=1:raise ValueError('unsupported_ui_auth_schema')

    @contextmanager
    def transaction(self):
        c=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        c.row_factory=sqlite3.Row
        try:
            c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except BaseException:
            c.rollback();raise
        finally:c.close()

    def _audit(self,c,actor,action,outcome):
        c.execute('INSERT INTO audit(at,actor,action,outcome) VALUES(?,?,?,?)',
                  (self.clock(),actor,action,outcome))
        c.execute('DELETE FROM audit WHERE seq <= (SELECT COALESCE(MAX(seq),0)-10000 FROM audit)')

    @staticmethod
    def _user_inputs(username,role,scope):
        if not USERNAME.fullmatch(username) or role not in ('reviewer','operator') or not SCOPE.fullmatch(scope):
            raise ValueError('invalid_ui_user')

    def create_user(self,username,password,role,scope):
        self._user_inputs(username,role,scope);encoded=hash_password(password)
        with self.transaction() as c:
            if c.execute('SELECT 1 FROM users WHERE username=?',(username,)).fetchone():
                raise ValueError('ui_user_exists')
            c.execute('INSERT INTO users VALUES(?,?,?,?,1,0)',(username,encoded,role,scope))
            self._audit(c,username,'local_create','ok')

    def change_user(self,username,*,password=None,role=None,scope=None,disabled=None):
        encoded=hash_password(password) if password is not None else None
        with self.transaction() as c:
            row=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            if row is None:raise ValueError('ui_user_not_found')
            role=role if role is not None else row['role'];scope=scope if scope is not None else row['scope']
            self._user_inputs(username,role,scope)
            if disabled is not None and type(disabled) is not bool:raise ValueError('invalid_disabled')
            c.execute('UPDATE users SET password=?,role=?,scope=?,disabled=?,version=version+1 WHERE username=?',
                      (encoded or row['password'],role,scope,row['disabled'] if disabled is None else int(disabled),username))
            c.execute('DELETE FROM sessions WHERE username=?',(username,))
            self._audit(c,username,'local_update','revoked_sessions')

    def revoke_user(self,username):
        self.change_user(username)

    def challenge(self):
        cookie,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32);now=self.clock()
        with self.transaction() as c:
            c.execute('DELETE FROM challenges WHERE expires<=?',(now,))
            c.execute('DELETE FROM challenges WHERE token_hash IN (SELECT token_hash FROM challenges ORDER BY expires DESC LIMIT -1 OFFSET 511)')
            c.execute('INSERT INTO challenges VALUES(?,?,?)',(_key(cookie),_key(csrf),now+CHALLENGE_SECONDS))
        return cookie,csrf

    def consume_challenge(self,cookie,csrf):
        if not cookie or not csrf or len(cookie)>128 or len(csrf)>128:raise UIError('csrf_rejected',403)
        with self.transaction() as c:
            row=c.execute('SELECT * FROM challenges WHERE token_hash=?',(_key(cookie),)).fetchone()
            if row is None or row['expires']<=self.clock() or not hmac.compare_digest(row['csrf_hash'],_key(csrf)):
                raise UIError('csrf_rejected',403)
            c.execute('DELETE FROM challenges WHERE token_hash=?',(_key(cookie),))

    def _limit_login(self,username,peer):
        now=self.clock();peer_key='peer:'+_key(peer);user_key='user:'+_key(peer+'|'+username)
        with self.transaction() as c:
            c.execute('DELETE FROM attempts WHERE at<=?',(now-900,))
            allowed=c.execute('SELECT count(*) FROM attempts').fetchone()[0]<20000
            for key,seconds,limit in ((peer_key,60,60),(user_key,900,5)):
                if c.execute('SELECT count(*) FROM attempts WHERE bucket=? AND at>?',(key,now-seconds)).fetchone()[0]>=limit:
                    allowed=False
            if allowed:c.executemany('INSERT INTO attempts VALUES(?,?)',[(peer_key,now),(user_key,now)])
            else:self._audit(c,'anonymous','login','throttled')
        if not allowed:raise UIError('login_throttled',429)
        return user_key

    def login(self,username,password,scope,peer,*,old_token=None):
        bucket=self._limit_login(username,peer)
        if not _slots.acquire(blocking=False):raise UIError('login_throttled',429)
        try:
            with self.transaction() as c:row=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            valid=verify_password(password,row['password'] if row else _dummy())
        finally:_slots.release()
        token,csrf=secrets.token_urlsafe(32),secrets.token_urlsafe(32);now=self.clock();actor=None
        with self.transaction() as c:
            current=c.execute('SELECT * FROM users WHERE username=?',(username,)).fetchone()
            if (valid and row and current and not current['disabled'] and current['scope']==scope
                    and current['role'] in ('reviewer','operator') and current['version']==row['version']
                    and current['password']==row['password']):
                c.execute('DELETE FROM sessions WHERE created<=? OR last_seen<=?',(now-SESSION_SECONDS,now-IDLE_SECONDS))
                if old_token and len(old_token)<=128:c.execute('DELETE FROM sessions WHERE token_hash=?',(_key(old_token),))
                c.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?)',(_key(token),username,current['version'],scope,csrf,now,now))
                c.execute('DELETE FROM attempts WHERE bucket=?',(bucket,))
                actor=Actor(username,current['role'],scope,csrf,now+SESSION_SECONDS,now+min(SESSION_SECONDS,IDLE_SECONDS))
                self._audit(c,username,'login','ok')
            else:self._audit(c,'anonymous','login','invalid_credentials')
        if actor is None:raise UIError('invalid_credentials')
        return token,actor

    def session(self,token,scope):
        if not token or len(token)>128:raise UIError('authentication_required')
        now=self.clock();actor=None;scope_changed=False
        with self.transaction() as c:
            row=c.execute('SELECT s.*,u.role,u.disabled,u.scope AS user_scope,u.version AS user_version FROM sessions s JOIN users u USING(username) WHERE token_hash=?',(_key(token),)).fetchone()
            if row is not None:
                if row['disabled'] or row['version']!=row['user_version'] or now>=row['created']+SESSION_SECONDS or now>=row['last_seen']+IDLE_SECONDS:
                    c.execute('DELETE FROM sessions WHERE token_hash=?',(_key(token),));self._audit(c,row['username'],'session','expired_or_revoked')
                elif row['scope']!=scope or row['user_scope']!=scope:
                    scope_changed=True
                elif row['role'] in ('reviewer','operator'):
                    c.execute('UPDATE sessions SET last_seen=? WHERE token_hash=?',(now,_key(token)))
                    actor=Actor(row['username'],row['role'],scope,row['csrf'],row['created']+SESSION_SECONDS,
                                min(row['created']+SESSION_SECONDS,now+IDLE_SECONDS))
        if scope_changed:raise UIError('scope_changed',403)
        if actor is None:raise UIError('authentication_required')
        return actor

    def logout(self,token):
        if not token or len(token)>128:return
        with self.transaction() as c:
            row=c.execute('SELECT username FROM sessions WHERE token_hash=?',(_key(token),)).fetchone()
            c.execute('DELETE FROM sessions WHERE token_hash=?',(_key(token),))
            if row:self._audit(c,row['username'],'logout','ok')


def configure_private_ui(state: Path, origin: str) -> dict:
    """Bootstrap/update under the SERVICE UID, never a privileged installer UID.

    Fixed paths, no default accounts, no predictable temporary path following.
    The caller must drop privileges before touching this service-owned namespace.
    """
    private = state / 'ui'
    settings = UISettings(private / 'auth.sqlite', origin)
    if state.is_symlink() or private.is_symlink():
        raise ValueError('ui_private_directory_required')
    private.mkdir(mode=0o700, exist_ok=True)
    if private.stat().st_uid != os.getuid() or private.stat().st_mode & 0o077:
        raise ValueError('ui_private_directory_required')
    AuthStore(settings.database)
    path = private / 'ui.json'
    data = (json.dumps(dict(database=str(settings.database), origin=origin), sort_keys=True)+'\n').encode()
    if path.exists() or path.is_symlink():
        private_file(path)
        if path.read_bytes() == data:
            return {'ok': True, 'changed': False}
    tmp = private / ('.ui-' + secrets.token_hex(16) + '.tmp')
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    return {'ok': True, 'changed': True}
