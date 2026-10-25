"""Inventory diff and ownership: what the box may treat as its own before any plan."""

import unittest

import ownership as own
from fixtures import P1_LIVE, box_state, inventory, state, uid


def live_box(box="pilot1", ids=(5, 2, 4)):
    p = f"amvp-box-{box}"
    vm, disk, ip = ids
    return dict(vms=[(uid(vm), f"{p}-vm")], disks=[(uid(disk), f"{p}-boot")], ips=[(uid(ip), f"{p}-ip")])


def merge(*parts):
    out = {"vms": [], "disks": [], "ips": []}
    for part in parts:
        for k, v in part.items():
            out[k] = out[k] + list(v)
    return out


def classify(inv, st, box="pilot1"):
    live, _ = own.live_inventory(inv)
    return own.classify(live, own.state_records(st), box)


class InventoryDiff(unittest.TestCase):
    def test_rerun_after_success_owns_everything_and_leaves_p1_foreign(self):
        r = classify(inventory(**merge(live_box(), P1_LIVE)), box_state())
        self.assertEqual(r["problems"], [])
        self.assertEqual(sorted(x.name for x in r["owned"]), ["amvp-box-pilot1-boot", "amvp-box-pilot1-ip", "amvp-box-pilot1-vm"])
        self.assertEqual(r["foreign"], {"vm": 2, "disk": 2, "external_ip": 1})

    def test_vm_created_by_an_interrupted_apply_without_state_is_an_orphan_that_blocks(self):
        # The runner died after the VM create call returned and before state was written.
        st = box_state()
        st["resources"] = [res for res in st["resources"] if res["type"] != "cloudru_evolution_compute_vm"]
        r = classify(inventory(**live_box(ids=(77, 2, 4))), st)
        self.assertEqual([(x.kind, x.id) for x in r["orphans"]], [("vm", uid(77))])
        self.assertIn(f"orphan:vm:{uid(77)}", r["problems"])

    def test_two_live_vms_with_the_box_name_are_duplicates(self):
        inv = inventory(**merge(live_box(), {"vms": [(uid(78), "amvp-box-pilot1-vm")]}))
        r = classify(inv, box_state())
        self.assertEqual(r["duplicates"], {"amvp-box-pilot1-vm": sorted([uid(5), uid(78)])})
        self.assertIn("duplicate_name:amvp-box-pilot1-vm", r["problems"])

    def test_names_that_only_share_the_prefix_belong_to_someone_else(self):
        inv = inventory(vms=[(uid(90), "amvp-box-pilot1-vm-copy"), (uid(91), "amvp-box-pilot10-vm")],
                        disks=[(uid(92), "amvp-box-pilot1-vm")])  # a disk with the VM's name is not the VM
        r = classify(inv, state())
        self.assertEqual(r["orphans"], [])
        self.assertEqual(r["foreign"], {"vm": 2, "disk": 1})

    def test_resource_deleted_outside_terraform_is_reported_missing(self):
        inv = inventory(vms=[(uid(5), "amvp-box-pilot1-vm")], ips=[(uid(4), "amvp-box-pilot1-ip")])
        r = classify(inv, box_state())
        self.assertEqual([x.address for x in r["missing"]], ["cloudru_evolution_compute_disk.boot"])

    def test_state_with_a_resource_of_another_project_stops(self):
        st = box_state(project="00000000-0000-0000-0000-000000000000")
        r = classify(inventory(**live_box()), st)
        self.assertIn("state_out_of_project:cloudru_evolution_compute_vm.box", r["problems"])

    def test_inventory_of_another_project_is_refused(self):
        with self.assertRaises(own.ScopeError):
            own.live_inventory(inventory(project="00000000-0000-0000-0000-000000000000"))

    def test_state_with_an_unknown_resource_type_is_refused(self):
        st = state(("cloudru_evolution_compute_nat_gateway", "core_egress", None, {"id": uid(1)}, False))
        with self.assertRaises(own.ScopeError):
            own.state_records(st)

    def test_box_id_with_dash_or_uppercase_is_rejected(self):
        for bad in ("pilot-1", "Pilot1", "p1", "a" * 17):
            with self.assertRaises(own.ScopeError, msg=bad):
                own.expected_name(bad, "vm")


class Recovery(unittest.TestCase):
    def test_only_our_tainted_interface_is_untainted(self):
        st = box_state(tainted=("nic", "box"))
        self.assertEqual(own.untaint_candidates(own.state_records(st), "pilot1"),
                         ["cloudru_evolution_compute_interface.nic"])

    def test_tainted_interface_with_a_foreign_name_is_left_for_replacement(self):
        st = box_state(tainted=("nic",))
        st["resources"][2]["instances"][0]["attributes"]["name"] = "dm-p1-ui-nic"
        self.assertEqual(own.untaint_candidates(own.state_records(st), "pilot1"), [])

    def test_adopt_writes_an_import_only_for_a_real_orphan(self):
        st = box_state()
        st["resources"] = [res for res in st["resources"] if res["type"] != "cloudru_evolution_compute_vm"]
        r = classify(inventory(**merge(live_box(ids=(77, 2, 4)), P1_LIVE)), st)
        block = own.adopt_block(r, "vm", uid(77))
        self.assertIn("to = cloudru_evolution_compute_vm.box", block)
        self.assertIn(f'id = "{uid(77)}"', block)
        with self.assertRaises(own.ScopeError):  # a P1 VM is never adoptable
            own.adopt_block(r, "vm", "c9e589fc-a42a-4cc3-8038-fe7d73929713")
        with self.assertRaises(own.ScopeError):  # an owned disk is not an orphan
            own.adopt_block(r, "disk", uid(2))


class Quota(unittest.TestCase):
    def test_public_ip_quota_without_room_blocks_a_first_apply(self):
        quotas = {"organization": [{"resource_type_code": "network.ip.quantity", "individual_limit": 1,
                                    "individual_usage": 1, "aggregated_usage": 1}],
                  "project": [{"resource_type_code": "compute.vcpu", "individual_limit": None, "individual_usage": 4}]}
        self.assertEqual(own.quota_problems(quotas, {"network.ip.quantity": 1, "compute.vcpu": 2}),
                         ["quota:organization:network.ip.quantity:1+1>1"])


if __name__ == "__main__":
    unittest.main()
