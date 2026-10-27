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


def quota_row(code, limit, individual, aggregated):
    return {"resource_type_code": code, "individual_limit": limit, "individual_usage": individual,
            "aggregated_usage": aggregated}


# Rows as discovery run 40266720846 (26.10.2026) printed them: every number is a string, -1 is unlimited.
DISCOVERED = {"organization": [quota_row("network.ip.quantity", "5", "0", "3"), quota_row("compute.vcpu", "16", "0", "7"),
                               quota_row("compute.ram", "68", "0", "18")],
              "project": [quota_row("compute.ram", "-1", "12", "12"), quota_row("network.ip.quantity", "3", "2", "2"),
                          quota_row("compute.vcpu", "16", "4", "4")]}
FIRST_APPLY = {"network.ip.quantity": 1, "compute.vcpu": 2}


class Quota(unittest.TestCase):
    def test_public_ip_quota_without_room_blocks_a_first_apply(self):
        quotas = {"organization": [quota_row("network.ip.quantity", 1, 1, 1)],
                  "project": [quota_row("compute.vcpu", 16, 4, 4)]}
        self.assertEqual(own.quota_problems(quotas, FIRST_APPLY), ["quota:organization:network.ip.quantity:1+1>1"])

    def test_saturated_quota_given_as_strings_blocks_like_the_same_numbers(self):
        # Before the fix string rows were never compared and a full IP quota passed.
        row = quota_row("network.ip.quantity", "3", "3", "3")
        self.assertEqual(own.quota_problems({"project": [row]}, {"network.ip.quantity": 1}),
                         ["quota:project:network.ip.quantity:3+1>3"])
        mixed = quota_row("network.ip.quantity", 3, "3", 2)
        self.assertEqual(own.quota_problems({"project": [mixed]}, {"network.ip.quantity": 1}),
                         ["quota:project:network.ip.quantity:3+1>3"])

    def test_usage_is_the_numeric_maximum_of_the_two_usage_fields(self):
        # As strings "9" > "12"; the larger number is 12.
        row = quota_row("compute.vcpu", "13", "9", "12")
        self.assertEqual(own.quota_problems({"organization": [row]}, {"compute.vcpu": 2}),
                         ["quota:organization:compute.vcpu:12+2>13"])

    def test_discovered_rows_with_room_and_an_exactly_sufficient_quota_pass(self):
        self.assertEqual(own.quota_problems(DISCOVERED, FIRST_APPLY), [])
        exact = {"project": [quota_row("network.ip.quantity", "3", "2", "2"), quota_row("compute.vcpu", 6.0, "4", "4")]}
        self.assertEqual(own.quota_problems(exact, FIRST_APPLY), [])

    def test_unlimited_quota_is_not_a_blocker_but_another_negative_limit_is_unknown(self):
        self.assertEqual(own.quota_problems({"project": [quota_row("compute.ram", "-1", "500", "500")]},
                                            {"compute.ram": 4}), [])
        self.assertEqual(own.quota_problems({"project": [quota_row("compute.ram", "-2", "0", "0")]},
                                            {"compute.ram": 4}), ["quota_unknown:project:compute.ram:individual_limit"])

    def test_every_scope_is_checked_and_each_full_scope_is_reported(self):
        quotas = {"organization": [quota_row("network.ip.quantity", "5", "0", "5")],
                  "project": [quota_row("network.ip.quantity", "3", "3", "3")]}
        self.assertEqual(own.quota_problems(quotas, {"network.ip.quantity": 1}),
                         ["quota:organization:network.ip.quantity:5+1>5", "quota:project:network.ip.quantity:3+1>3"])

    def test_unreadable_values_make_the_quota_unknown_instead_of_sufficient(self):
        for field, value in (("individual_limit", None), ("individual_limit", True), ("individual_limit", "NaN"),
                             ("individual_limit", float("inf")), ("individual_limit", "много"),
                             ("individual_usage", None), ("aggregated_usage", "Infinity"),
                             ("aggregated_usage", False), ("individual_usage", "")):
            row = quota_row("network.ip.quantity", "3", "0", "0")
            row[field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(own.quota_problems({"project": [row]}, {"network.ip.quantity": 1}),
                                 [f"quota_unknown:project:network.ip.quantity:{field}"])
        row = quota_row("network.ip.quantity", "3", "0", "0")
        del row["aggregated_usage"]
        self.assertEqual(own.quota_problems({"project": [row]}, {"network.ip.quantity": 1}),
                         ["quota_unknown:project:network.ip.quantity:aggregated_usage"])

    def test_required_quota_without_any_row_is_unknown(self):
        self.assertEqual(own.quota_problems({"project": [quota_row("compute.vcpu", "16", "4", "4")]}, FIRST_APPLY),
                         ["quota_unknown:network.ip.quantity:no_row"])
        self.assertEqual(own.quota_problems({}, {}), [])  # nothing needed, nothing to check


if __name__ == "__main__":
    unittest.main()
