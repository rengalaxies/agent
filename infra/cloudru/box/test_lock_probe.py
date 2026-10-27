"""The lock test writes to the real state bucket; its cleanup must never reach production state."""

import unittest

import boxctl
import ownership as own


class LockProbeCleanup(unittest.TestCase):
    def test_cleanup_deletes_exactly_the_two_probe_objects(self):
        prefix = boxctl.probe_prefix("12", "1")
        listing = {  # list_object_versions(Prefix=prefix) also matches run 123 and is not exact
            "Versions": [
                {"Key": "terraform/box/lock-probe-12-1.tfstate", "VersionId": "v1"},
                {"Key": "terraform/box/lock-probe-12-1.tfstate", "VersionId": "v2"},
                {"Key": "terraform/box/lock-probe-12-1.tfstate.tflock", "VersionId": "v3"},
                {"Key": "terraform/box/lock-probe-12-10.tfstate", "VersionId": "other-run"},
            ],
            "DeleteMarkers": [{"Key": "terraform/box/lock-probe-12-1.tfstate.tflock", "VersionId": "m1"}],
        }
        self.assertEqual(boxctl.probe_versions_to_delete(listing, prefix), [
            ("terraform/box/lock-probe-12-1.tfstate", "v1"), ("terraform/box/lock-probe-12-1.tfstate", "v2"),
            ("terraform/box/lock-probe-12-1.tfstate.tflock", "m1"), ("terraform/box/lock-probe-12-1.tfstate.tflock", "v3")])

    def test_production_state_key_is_never_a_probe(self):
        for prefix in ("terraform/box/pilot1", "terraform/p1/daniil-smirnov", "terraform/box/lock-probe-", "terraform/box/lock-probe-1-x"):
            with self.assertRaises(own.ScopeError, msg=prefix):
                boxctl.probe_keys(prefix)
        with self.assertRaises(own.ScopeError):
            boxctl.probe_prefix("12;rm", "1")

    def test_backend_never_points_outside_terraform_box(self):
        flags = boxctl.backend_flags("test-bucket-ds", boxctl.state_key("pilot1"))
        self.assertIn("-backend-config=key=terraform/box/pilot1.tfstate", flags)
        self.assertIn("-backend-config=use_lockfile=true", flags)
        self.assertIn("-backend-config=encrypt=true", flags)
        with self.assertRaises(own.ScopeError):
            boxctl.backend_flags("test-bucket-ds", "terraform/p1/daniil-smirnov.tfstate")


if __name__ == "__main__":
    unittest.main()
