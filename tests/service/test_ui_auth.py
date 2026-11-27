"""Real KDF and durable local session security, no network or live credentials."""
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from agent_service.ui_auth import AuthStore, UIError, hash_password, verify_password

PASSWORD = 'author-test-password-2026'
SCOPE = 'a' * 64


class AuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.encoded = hash_password(PASSWORD)

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'auth.sqlite'
        self.now = 1000.0
        self.auth = AuthStore(self.path, clock=lambda: self.now)
        # Reuse a real hash, not a cheap production KDF configuration.
        with self.auth.transaction() as c:
            c.execute('INSERT INTO users VALUES(?,?,?,?,?,?)', ('reader', self.encoded, 'reviewer', SCOPE, 1, 0))

    def login(self, **kw):
        return self.auth.login('reader', PASSWORD, SCOPE, 'local-peer', **kw)

    def error(self, code, fn, *args, **kwargs):
        with self.assertRaises(UIError) as caught: fn(*args, **kwargs)
        self.assertEqual(caught.exception.code, code)

    def test_real_scrypt_uses_random_salts_and_verifies_without_plaintext(self):
        second = hash_password(PASSWORD)
        self.assertNotEqual(self.encoded, second)
        self.assertTrue(verify_password(PASSWORD, self.encoded))
        self.assertFalse(verify_password('wrong', self.encoded))
        self.assertNotIn(PASSWORD, self.encoded)
        for value in ('bad', 'scrypt-v1$999999999$broken'):
            self.assertFalse(verify_password(PASSWORD, value))

    def test_challenge_is_single_use_and_expires(self):
        cookie, csrf = self.auth.challenge()
        self.error('csrf_rejected', self.auth.consume_challenge, cookie, 'wrong')
        self.auth.consume_challenge(cookie, csrf)
        self.error('csrf_rejected', self.auth.consume_challenge, cookie, csrf)
        cookie, csrf = self.auth.challenge(); self.now += 301
        self.error('csrf_rejected', self.auth.consume_challenge, cookie, csrf)

    def test_opaque_session_hashed_at_rest_and_restored_after_restart(self):
        token, actor = self.login()
        self.assertGreaterEqual(len(token), 40); self.assertEqual(actor.role, 'reviewer')
        with self.auth.transaction() as c:
            dump = '\n'.join(c.iterdump())
        self.assertNotIn(token, dump); self.assertNotIn(PASSWORD, dump)
        other = AuthStore(self.path, clock=lambda: self.now)
        self.assertEqual(other.session(token, SCOPE).username, 'reader')
        self.error('authentication_required', other.session, 'invented', SCOPE)
        self.error('scope_changed', other.session, token, 'b'*64)

    def test_idle_and_absolute_expiry(self):
        token, _ = self.login(); self.now += 1201
        self.error('authentication_required', self.auth.session, token, SCOPE)
        token, _ = self.login()
        for _ in range(29):
            self.now += 1000
            if _ < 28: self.auth.session(token, SCOPE)
        self.error('authentication_required', self.auth.session, token, SCOPE)

    def test_login_rotates_and_logout_revokes(self):
        old, _ = self.login(); new, _ = self.login(old_token=old)
        self.assertNotEqual(old, new)
        self.error('authentication_required', self.auth.session, old, SCOPE)
        self.auth.logout(new)
        self.error('authentication_required', self.auth.session, new, SCOPE)

    def test_password_role_disable_and_explicit_revoke_end_existing_sessions(self):
        for change in ({'role':'operator'}, {'password':PASSWORD+'-changed'}, {'scope':'b'*64}, {'disabled':True}):
            token, _ = self.login()
            self.auth.change_user('reader', **change)
            self.error('authentication_required', self.auth.session, token, SCOPE)
            self.auth.change_user('reader', password=PASSWORD, role='reviewer', scope=SCOPE, disabled=False)
        token, _ = self.login(); self.auth.revoke_user('reader')
        self.error('authentication_required', self.auth.session, token, SCOPE)

    def test_unknown_disabled_and_wrong_password_share_generic_error(self):
        for username,password in [('nobody',PASSWORD),('reader','wrong')]:
            self.error('invalid_credentials', self.auth.login, username, password, SCOPE, 'peer')
        self.auth.change_user('reader', disabled=True)
        self.error('invalid_credentials', self.auth.login, 'reader', PASSWORD, SCOPE, 'peer')

    def test_throttle_is_durable_and_window_is_bounded(self):
        for _ in range(5):
            self.error('invalid_credentials', self.auth.login, 'reader', 'wrong', SCOPE, 'peer')
        other = AuthStore(self.path, clock=lambda: self.now)
        self.error('login_throttled', other.login, 'reader', PASSWORD, SCOPE, 'peer')
        self.now += 901
        self.assertEqual(other.login('reader', PASSWORD, SCOPE, 'peer')[1].username, 'reader')

    def test_concurrent_login_budget_and_audit_redaction(self):
        def attempt(_):
            try: self.auth.login('reader','wrong',SCOPE,'parallel')
            except UIError as e: return e.code
        with ThreadPoolExecutor(max_workers=4) as pool: results=list(pool.map(attempt,range(8)))
        self.assertIn('login_throttled', results)
        with self.auth.transaction() as c:
            rows=c.execute('SELECT * FROM audit').fetchall()
        self.assertNotIn(PASSWORD,str(rows));self.assertNotIn('wrong',str(rows))

    def test_private_database_and_invalid_user_inputs(self):
        self.assertEqual(self.path.stat().st_mode & 0o777,0o600)
        link=self.path.parent/'linked.sqlite';link.symlink_to(self.path)
        with self.assertRaises(ValueError): AuthStore(link)
        self.path.chmod(0o644)
        with self.assertRaises(ValueError): AuthStore(self.path)
        self.path.chmod(0o600)
        for name,pw,role in [('bad name',PASSWORD,'reviewer'),('valid','short','reviewer'),('valid',PASSWORD,'admin')]:
            with self.assertRaises(ValueError):self.auth.create_user(name,pw,role,SCOPE)
