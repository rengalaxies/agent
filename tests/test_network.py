import tempfile
import unittest
from pathlib import Path

from datamesh_release_protocol.network import _sign, coordinate
from datamesh_release_protocol.loaders import load_scenario


class NetworkTests(unittest.TestCase):
    def test_hmac_covers_entire_event(self):
        original = {"domain_id": "retail", "decision": "ACCEPT"}
        changed = {**original, "decision": "REJECT"}
        self.assertNotEqual(_sign("a" * 32, original), _sign("a" * 32, changed))
        self.assertNotEqual(_sign("a" * 32, original), _sign("b" * 32, original))

    def test_rejects_incomplete_or_weak_config_before_network(self):
        scenario = load_scenario(Path("scenarios/development/T-03.yaml"))
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "three endpoints and keys"):
                coordinate(scenario, "test", {"retail": "http://127.0.0.1:1"},
                           {"retail": "weak"}, Path(temp) / "journal.sqlite", timeout_s=1)


if __name__ == "__main__":
    unittest.main()
