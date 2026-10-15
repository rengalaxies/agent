import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from datamesh_release_protocol.evidence_pilot import SyntheticPilot
from services.evidence_pilot import create_server


class PilotTests(unittest.TestCase):
    def test_real_unit_migration_lifecycle_and_restart(self):
        with TemporaryDirectory() as directory:
            pilot = SyntheticPilot(directory)
            self.assertEqual(pilot.state()['current_evidence_decision'], 'NEEDS_REVIEW')
            state = pilot.action('authorize')
            self.assertEqual(state['last_decision']['terminal_state'], 'ESCALATED')
            pilot.action('approve')
            state = pilot.action('authorize')
            self.assertEqual(state['last_decision']['terminal_state'], 'COMMITTED')
            release_id = state['last_decision']['release_id']
            state = SyntheticPilot(directory).state()
            self.assertEqual(state['historical_authorizations'], 1)
            self.assertEqual(state['last_decision']['release_id'], release_id)
            restarted = SyntheticPilot(directory)
            restarted.action('revoke')
            restarted.action('restart')
            state = restarted.action('authorize')
            self.assertEqual(state['last_decision']['terminal_state'], 'ESCALATED')
            self.assertIsNone(state['last_decision']['release_id'])
            self.assertEqual(state['historical_authorizations'], 1)
            self.assertFalse(state['publication_executed'])

    def test_invalid_action_does_not_write(self):
        with TemporaryDirectory() as directory:
            pilot = SyntheticPilot(directory)
            before = pilot.path.read_bytes()
            with self.assertRaises(ValueError): pilot.action('publish-real-data')
            self.assertEqual(before, pilot.path.read_bytes())

    def test_loopback_interface_and_http_restart_flow(self):
        with TemporaryDirectory() as directory:
            server = create_server(directory)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = 'http://127.0.0.1:' + str(server.server_port)
            def action(name, origin=None):
                headers = {'Content-Type': 'application/json'}
                if origin: headers['Origin'] = origin
                request = Request(base + '/action', data=json.dumps({'action': name}).encode(), headers=headers)
                return json.loads(urlopen(request, timeout=5).read())
            try:
                html = urlopen(base, timeout=5).read().decode()
                self.assertIn('data-action="authorize"', html)
                self.assertEqual(json.loads(urlopen(base + '/state', timeout=5).read())['dataset'], 'SYNTHETIC ONLY')
                action('approve')
                self.assertEqual(action('authorize')['last_decision']['terminal_state'], 'COMMITTED')
                self.assertEqual(action('restart')['historical_authorizations'], 1)
                with self.assertRaises(HTTPError) as error:
                    action('revoke', 'https://untrusted.invalid')
                self.assertEqual(error.exception.code, 403)
                action('revoke')
                self.assertEqual(action('authorize')['last_decision']['terminal_state'], 'ESCALATED')
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)
