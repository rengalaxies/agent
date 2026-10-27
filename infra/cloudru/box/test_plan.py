"""Plan guard, reviewed-plan digest, TTL and cleanup selection."""

import contextlib
import copy
import datetime as dt
import io
import json
from pathlib import Path
import tempfile
import unittest

import boxctl
import ownership as own
from fixtures import P1_LIVE, box_state, destroy_plan, fresh_plan, inventory, rc, uid
from test_ownership import DISCOVERED, quota_row

KEY = bytes(range(32))
SHA = "a" * 40


def records(st):
    return own.state_records(st)


def projection(plan, key=KEY, mode="apply"):
    return own.plan_projection(plan, key=key, commit=SHA, box_id="pilot1", mode=mode)


class ApplyGuard(unittest.TestCase):
    def test_first_apply_of_the_box_passes(self):
        self.assertEqual(own.guard_plan(fresh_plan(), "apply", "pilot1", []), [])

    def test_resource_in_another_project_is_refused(self):
        plan = fresh_plan()
        plan["resource_changes"][1]["change"]["after"]["project_id"] = "00000000-0000-0000-0000-000000000000"
        self.assertIn("project_mismatch:cloudru_evolution_compute_disk.boot",
                      own.guard_plan(plan, "apply", "pilot1", []))

    def test_resource_type_outside_the_box_is_refused(self):
        plan = fresh_plan()
        plan["resource_changes"].append(rc("cloudru_evolution_compute_nat_gateway.egress",
                                           "cloudru_evolution_compute_nat_gateway", ["create"], after={}))
        self.assertIn("type_not_allowed:cloudru_evolution_compute_nat_gateway.egress",
                      own.guard_plan(plan, "apply", "pilot1", []))

    def test_replacing_a_healthy_vm_or_disk_is_refused(self):
        st = box_state()
        for address, type_ in [("cloudru_evolution_compute_vm.box", "cloudru_evolution_compute_vm"),
                               ("cloudru_evolution_compute_disk.boot", "cloudru_evolution_compute_disk")]:
            name = "amvp-box-pilot1-" + ("vm" if "vm" in type_ else "boot")
            plan = {"resource_changes": [rc(address, type_, ["delete", "create"], before={"id": uid(5), "name": name},
                                            after={"name": name})]}
            self.assertEqual(own.guard_plan(plan, "apply", "pilot1", records(st)),
                             [f"replace_or_delete_forbidden:{address}"])

    def test_replacing_a_tainted_vm_left_by_a_failed_create_is_allowed(self):
        plan = {"resource_changes": [rc("cloudru_evolution_compute_vm.box", "cloudru_evolution_compute_vm",
                                        ["delete", "create"], before={"id": uid(5), "name": "amvp-box-pilot1-vm"},
                                        after={"name": "amvp-box-pilot1-vm"})]}
        # box_state(tainted=("box",)) taints both resources named "box": the SG and the VM.
        self.assertEqual(own.guard_plan(plan, "apply", "pilot1", records(box_state(tainted=("box",)))), [])

    def test_closing_ssh_deletes_only_the_rule(self):
        st = box_state()
        st["resources"].append({"mode": "managed", "type": "cloudru_evolution_compute_security_group_rule",
                                "name": "ssh", "instances": [{"index_key": 0, "attributes": {"id": uid(20)}}]})
        plan = {"resource_changes": [rc("cloudru_evolution_compute_security_group_rule.ssh[0]",
                                        "cloudru_evolution_compute_security_group_rule", ["delete"],
                                        before={"id": uid(20)})]}
        self.assertEqual(own.guard_plan(plan, "apply", "pilot1", records(st)), [])

    def test_import_needs_the_owner_adopt_list(self):
        plan = fresh_plan()
        plan["resource_changes"][4]["change"].update(actions=["no-op"], importing={"id": uid(77)})
        self.assertIn("import_not_adopted:cloudru_evolution_compute_vm.box", own.guard_plan(plan, "apply", "pilot1", []))
        self.assertEqual(own.guard_plan(plan, "apply", "pilot1", [], adopt_ids=[uid(77)]), [])

    def test_a_plan_that_renames_into_a_p1_resource_is_refused(self):
        plan = fresh_plan()
        plan["resource_changes"][4]["change"]["after"]["name"] = "dm-p1-ui"
        self.assertIn("name_not_owned:cloudru_evolution_compute_vm.box", own.guard_plan(plan, "apply", "pilot1", []))


class DestroyGuard(unittest.TestCase):
    def test_full_destroy_of_recorded_resources_passes(self):
        st = box_state()
        self.assertEqual(own.guard_plan(destroy_plan(st), "destroy", "pilot1", records(st)), [])

    def test_destroy_of_an_id_the_state_does_not_hold_is_refused(self):
        st = box_state()
        plan = destroy_plan(st)
        plan["resource_changes"][4]["change"]["before"]["id"] = "c9e589fc-a42a-4cc3-8038-fe7d73929713"
        self.assertIn("delete_not_recorded:cloudru_evolution_compute_vm.box",
                      own.guard_plan(plan, "destroy", "pilot1", records(st)))

    def test_destroy_plan_that_creates_anything_is_refused(self):
        st = box_state()
        plan = destroy_plan(st)
        plan["resource_changes"][0]["change"]["actions"] = ["delete", "create"]
        problems = own.guard_plan(plan, "destroy", "pilot1", records(st))
        self.assertIn("destroy_plan_has_delete-create:cloudru_evolution_compute_security_group.box", problems)
        self.assertTrue(any(p.startswith("destroy_incomplete:") for p in problems))


class Digest(unittest.TestCase):
    def test_digest_does_not_depend_on_change_order(self):
        plan = fresh_plan()
        shuffled = copy.deepcopy(plan)
        shuffled["resource_changes"].reverse()
        self.assertEqual(own.digest(projection(plan)), own.digest(projection(shuffled)))

    def test_owner_cidr_changes_the_digest_but_never_appears_in_the_projection(self):
        a, b = projection(fresh_plan(admin_cidr="203.0.113.7/32")), projection(fresh_plan(admin_cidr="203.0.113.8/32"))
        self.assertNotEqual(own.digest(a), own.digest(b))
        text = json.dumps(a)
        self.assertNotIn("203.0.113.7", text)
        self.assertIn("0.0.0.0/0", text)  # open egress stays readable for the reviewer

    def test_sensitive_values_are_tagged_not_published(self):
        plan = fresh_plan()
        vm = plan["resource_changes"][4]["change"]
        vm["after"]["image_metadata"] = {"public_key": {"string_value": "ssh-ed25519 AAAA owner"},
                                         "secret": {"string_value": "s3cr3t-value"}}
        vm["after_sensitive"] = {"image_metadata": {"secret": True}}
        text = json.dumps(projection(plan))
        self.assertNotIn("s3cr3t-value", text)
        self.assertIn("ssh-ed25519 AAAA owner", text)

    def test_any_change_in_a_create_changes_the_digest(self):
        plan = fresh_plan()
        bigger = copy.deepcopy(plan)
        bigger["resource_changes"][1]["change"]["after"]["size"] = 40
        self.assertNotEqual(own.digest(projection(plan)), own.digest(projection(bigger)))

    def test_digest_binds_commit_and_mode(self):
        plan = fresh_plan()
        other = own.plan_projection(plan, key=KEY, commit="b" * 40, box_id="pilot1", mode="apply")
        self.assertNotEqual(own.digest(projection(plan)), own.digest(other))
        self.assertNotEqual(own.digest(projection(plan)), own.digest(projection(plan, mode="destroy")))

    def test_short_key_or_abbreviated_commit_is_refused(self):
        with self.assertRaises(own.ScopeError):
            own.plan_projection(fresh_plan(), key=b"short", commit=SHA, box_id="pilot1", mode="apply")
        with self.assertRaises(own.ScopeError):
            own.plan_projection(fresh_plan(), key=KEY, commit="abc1234", box_id="pilot1", mode="apply")


class TtlAndCleanup(unittest.TestCase):
    TODAY = dt.date(2026, 10, 25)

    def test_ttl_must_be_in_future_and_within_limit(self):
        self.assertEqual(own.check_ttl("2026-10-25", self.TODAY), ["expires_on_not_in_future"])
        self.assertEqual(own.check_ttl("2027-03-01", self.TODAY), ["expires_on_beyond_120_days"])
        self.assertEqual(own.check_ttl("2026-12-31", self.TODAY), [])
        self.assertTrue(own.ttl_state("2026-10-24", self.TODAY)["expired"])

    def test_cleanup_deletes_recorded_resources_and_leaves_orphans_and_p1(self):
        st = box_state()
        rs = records(st)
        ledger = own.ledger_from_state(rs, box_id="pilot1", expires_on="2026-12-31", commit=SHA, plan_digest="d" * 64)
        inv = inventory(vms=P1_LIVE["vms"] + [(uid(5), "amvp-box-pilot1-vm"), (uid(77), "amvp-box-pilot1-vm")])
        live, _ = own.live_inventory(inv)
        result = own.cleanup_selection(destroy_plan(st), rs, ledger, live, "pilot1")
        self.assertEqual(result["problems"], [])
        self.assertEqual({d["id"] for d in result["delete"]}, {r.id for r in rs})
        self.assertEqual([o["id"] for o in result["left_in_place"]["orphans"]], [uid(77)])
        self.assertEqual(result["left_in_place"]["foreign"], {"vm": 2})

    def test_cleanup_refuses_when_ledger_and_state_disagree_or_ledger_is_missing(self):
        st = box_state()
        rs = records(st)
        ledger = own.ledger_from_state(rs, box_id="pilot1", expires_on="2026-12-31", commit=SHA, plan_digest="d" * 64)
        ledger["resources"]["cloudru_evolution_compute_vm.box"] = uid(99)
        live, _ = own.live_inventory(inventory())
        self.assertIn("ledger_differs_from_state", own.cleanup_selection(destroy_plan(st), rs, ledger, live, "pilot1")["problems"])
        self.assertIn("ledger_missing", own.cleanup_selection(destroy_plan(st), rs, None, live, "pilot1")["problems"])


class ClassifyQuota(unittest.TestCase):
    """``boxctl classify`` runs before plan and apply; a non-zero exit stops the workflow there."""

    SUBNET = "d58e80ef-fff1-43eb-b601-96fb358224b7"
    FULL_IP = {"project": [quota_row("network.ip.quantity", "3", "3", "3"), quota_row("compute.vcpu", "16", "4", "4")]}

    def classify(self, quotas, *, state=None, adopt="", **live):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "inventory.json").write_text(json.dumps(inventory(**{**P1_LIVE, **live}, quotas=quotas)))
            args = ["classify", "--box-id", "pilot1", "--inventory", str(tmp / "inventory.json"),
                    "--state", str(tmp / "state.json"), "--subnet", self.SUBNET, "--out", str(tmp / "out.json")]
            if state is not None:
                (tmp / "state.json").write_text(json.dumps(state))
            if adopt:
                args += ["--adopt", adopt]
            err = io.StringIO()
            with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
                code = boxctl.main(args)
            return code, json.loads((tmp / "out.json").read_text())["problems"], err.getvalue()

    def test_first_apply_is_blocked_by_a_full_ip_quota_reported_as_strings(self):
        code, problems, err = self.classify(self.FULL_IP)
        self.assertEqual((code, problems), (1, ["quota:project:network.ip.quantity:3+1>3"]))
        self.assertIn("problem: quota:project:network.ip.quantity:3+1>3", err)

    def test_first_apply_is_blocked_when_a_required_quota_cannot_be_read(self):
        code, problems, _ = self.classify({"project": [quota_row("compute.vcpu", "16", "4", "4")]})
        self.assertEqual((code, problems), (1, ["quota_unknown:network.ip.quantity:no_row"]))

    def test_first_apply_with_room_in_the_discovered_quotas_passes(self):
        self.assertEqual(self.classify(DISCOVERED)[:2], (0, []))

    def test_adopting_an_orphan_ip_needs_no_new_ip(self):
        orphan = (uid(4), "amvp-box-pilot1-ip")
        code, problems, _ = self.classify(self.FULL_IP, adopt=f"external_ip={uid(4)}",
                                          ips=P1_LIVE["ips"] + [orphan])
        self.assertEqual((code, problems), (0, []))

    def test_a_box_already_in_state_needs_no_new_quota(self):
        live = box_state()
        names = {r["type"]: r["instances"][0]["attributes"] for r in live["resources"]}
        code, problems, _ = self.classify(
            self.FULL_IP, state=live,
            vms=P1_LIVE["vms"] + [(names["cloudru_evolution_compute_vm"]["id"], "amvp-box-pilot1-vm")],
            disks=P1_LIVE["disks"] + [(names["cloudru_evolution_compute_disk"]["id"], "amvp-box-pilot1-boot")],
            ips=P1_LIVE["ips"] + [(names["cloudru_evolution_compute_external_ip"]["id"], "amvp-box-pilot1-ip")])
        self.assertEqual((code, problems), (0, []))


if __name__ == "__main__":
    unittest.main()
