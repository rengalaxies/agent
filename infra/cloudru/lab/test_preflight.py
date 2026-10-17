"""Scope guards are meaningful even without cloud credentials."""
import unittest
from preflight import PROJECT, select_state, live_zone_name


class ScopeTests(unittest.TestCase):
    def fixture(self):
        resources = []
        for kind, name, index, attrs in [
            ("cloudru_evolution_compute_vm", "ui_vm", None, {"id": "ui", "name": "dm-p1-ui"}),
            ("cloudru_evolution_compute_vm", "vm", "core", {"id": "97a6e631-1d80-4212-aa69-ef6454b029df", "name": "dm-p1-core"}),
            ("cloudru_evolution_compute_external_ip", "ui", None, {"id": "33a27f64-e474-49ed-a17b-15f67dd16400", "ip_address": "192.0.2.1", "network_interface": {"id": "nic"}}),
            ("cloudru_evolution_compute_interface", "nic", "ui", {"id": "nic"}),
        ]:
            attrs.update(project_id=PROJECT, zone={"name": "ru.AZ-2"})
            resources.append({"mode": "managed", "type": kind, "name": name,
                "instances": [{"index_key": index, "attributes": attrs}]})
        return {"lineage": "fixture", "serial": 1, "resources": resources}

    def test_live_zone_schema(self):
        self.assertEqual(live_zone_name({"availability_zone": {"name": "ru.AZ-2"}}), "ru.AZ-2")
        self.assertEqual(live_zone_name({"availability_zone": "ru.AZ-2"}), "ru.AZ-2")
        self.assertIsNone(live_zone_name({}))

    def test_exact_existing_scope(self):
        self.assertEqual(select_state(self.fixture())["core"]["name"], "dm-p1-core")

    def test_empty_or_foreign_scope_stops(self):
        with self.assertRaises(ValueError):
            select_state({})
        for field, bad in [("project_id", "other"), ("zone", {"name": "other"}), ("name", "other")]:
            state = self.fixture()
            state["resources"][0]["instances"][0]["attributes"][field] = bad
            with self.assertRaises(ValueError):
                select_state(state)

    def test_wrong_core_id_stops(self):
        state = self.fixture()
        state["resources"][1]["instances"][0]["attributes"]["id"] = "other"
        with self.assertRaises(ValueError):
            select_state(state)


if __name__ == "__main__":
    unittest.main()
