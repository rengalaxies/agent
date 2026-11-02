"""App token exchange through real authenticated HTTPS Git clone and fetch."""
import base64
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import os
import ssl
import subprocess
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from agent_service.http import Response
from tools.agent_service.box import mirrors
from tools.agent_service.box.config import BoxConfig
from tools.agent_service.box.tests import test_mirrors as fixture
from tools.agent_service.box.tests.test_mirrors import git


class AppGit(unittest.TestCase):
    def setUp(self):
        fixture.Sync.setUp(self)

    def test_app_clone_and_fetch_use_the_raw_installation_token(self):
        token = 'synthetic-installation-token'
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = self.tmp / 'app.pem'
        pem.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                          serialization.NoEncryption()))
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, '127.0.0.1')])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=1))
            .not_valid_after(now+timedelta(days=1)).add_extension(x509.SubjectAlternativeName([
                x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False).sign(key, hashes.SHA256()))
        ca = self.tmp / 'ca.pem'
        ca.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        depot = self.tmp / 'depot'
        (depot / 'acme').mkdir(parents=True)
        bare = depot / 'acme/orders.git'
        git('clone', '-q', '--bare', str(self.source), str(bare))
        accepted = []
        expected = 'Basic ' + base64.b64encode(f'x-access-token:{token}'.encode()).decode()
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass
            def handle_git(self):
                if self.headers.get('Authorization') != expected:
                    self.send_response(401)
                    self.send_header('WWW-Authenticate', 'Basic realm="fixture"')
                    self.send_header('Content-Length', '0')
                    self.end_headers()
                    return
                accepted.append(self.command)
                parts = urlsplit(self.path)
                body = self.rfile.read(int(self.headers.get('Content-Length', '0')))
                result = subprocess.run(['git', 'http-backend'], input=body, capture_output=True, env={
                    **os.environ, 'GIT_PROJECT_ROOT': str(depot), 'GIT_HTTP_EXPORT_ALL': '1',
                    'PATH_INFO': parts.path, 'QUERY_STRING': parts.query, 'REQUEST_METHOD': self.command,
                    'CONTENT_TYPE': self.headers.get('Content-Type', ''), 'CONTENT_LENGTH': str(len(body)),
                    'REMOTE_USER': 'fixture'})
                headers, data = result.stdout.split(b'\r\n\r\n', 1)
                self.send_response(200)
                for line in headers.decode().splitlines():
                    name, value = line.split(':', 1)
                    if name.lower() != 'status':
                        self.send_header(name, value.strip())
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            do_GET = do_POST = handle_git
        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(ca, pem)
        server.socket = tls.wrap_socket(server.socket, server_side=True)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = f'https://127.0.0.1:{server.server_port}'
        cfg = BoxConfig.model_validate(dict(installation_id='fixture', environment='test', github=dict(
            web_base=url, bot_login='fixture[bot]', auth=dict(kind='app', app_id='1', installation_id=2),
            repositories=[dict(name='acme/orders', service='orders', watch_prs=True)])))
        original_env = mirrors.git_env
        commands = []
        original_git = mirrors._git
        def env(*args, **kwargs):
            return {**original_env(*args, **kwargs), 'GIT_SSL_CAINFO':str(ca)}
        def command(environment, *args):
            self.assertFalse(any(token in a or 'Bearer ' in a for a in args))
            commands.append(args)
            return original_git(environment, *args)
        response = Response(201, {}, ('{"token":"'+token+'","expires_at":"2099-01-01T00:00:00Z"}').encode())
        with patch('agent_service.http.HttpClient.request', return_value=response) as exchange, \
                patch.object(mirrors, 'git_env', side_effect=env), patch.object(mirrors, '_git', side_effect=command):
            result = mirrors.sync(cfg, self.tmp/'mirrors', {'GITHUB_APP_PRIVATE_KEY_PATH':str(pem)})
            self.assertEqual(result[0]['status'], 'OK', result)
            self.assertEqual(result[0]['action'], 'cloned')
            self.assertEqual(result[0]['tip'], self.first)
            (self.source/'api.py').write_text('PAGE_SIZE = 20\n')
            git('commit', '-qam', 'two', cwd=self.source)
            git('--git-dir', str(bare), 'fetch', '-q', str(self.source), 'main:main')
            result = mirrors.sync(cfg, self.tmp/'mirrors', {'GITHUB_APP_PRIVATE_KEY_PATH':str(pem)})
            self.assertEqual(result[0]['action'], 'fetched')
            self.assertEqual(result[0]['tip'], git('rev-parse', 'HEAD', cwd=self.source))
            self.assertEqual(exchange.call_count, 2)
            for call in exchange.call_args_list:
                self.assertEqual(call.args[:2], ('POST', '/app/installations/2/access_tokens'))
                self.assertTrue(call.kwargs['headers']['Authorization'].startswith('Bearer '))
        self.assertIn('GET', accepted)
        self.assertIn('POST', accepted)
        self.assertTrue(any('clone' in c for c in commands))
        self.assertTrue(any('fetch' in c for c in commands))
        self.assertNotIn(token, (self.tmp/'mirrors/orders.git/config').read_text())
        self.assertNotIn(token, (self.tmp/'run/git-home/gitconfig').read_text())
