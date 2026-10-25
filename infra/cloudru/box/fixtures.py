"""Builders of Terraform JSON shapes for the box tests (state pull, show -json plan, inventory)."""

from ownership import PROJECT_ID

UUID = "{:08x}-0000-4000-8000-000000000000"


def uid(n: int) -> str:
    return UUID.format(n)


def state(*instances, outputs=None) -> dict:
    """instances: (type, name, index_key, attributes, tainted)"""
    resources = {}
    for type_, name, key, attrs, tainted in instances:
        res = resources.setdefault((type_, name), {"mode": "managed", "type": type_, "name": name, "instances": []})
        inst = {"attributes": attrs}
        if key is not None:
            inst["index_key"] = key
        if tainted:
            inst["status"] = "tainted"
        res["instances"].append(inst)
    return {"version": 4, "serial": 3, "lineage": "test", "outputs": outputs or {}, "resources": list(resources.values())}


def box_state(box="pilot1", *, tainted=(), project=PROJECT_ID, expires_on="2026-12-31") -> dict:
    """A complete box after a successful apply; ids 1..5 for named kinds, 10.. for rules."""
    p = f"amvp-box-{box}"
    named = [
        ("cloudru_evolution_compute_security_group", "box", f"{p}-sg", 1),
        ("cloudru_evolution_compute_disk", "boot", f"{p}-boot", 2),
        ("cloudru_evolution_compute_interface", "nic", f"{p}-nic", 3),
        ("cloudru_evolution_compute_external_ip", "public", f"{p}-ip", 4),
        ("cloudru_evolution_compute_vm", "box", f"{p}-vm", 5),
    ]
    inst = [(t, n, None, {"id": uid(i), "name": name, "project_id": project}, n in tainted) for t, n, name, i in named]
    for i, rule in enumerate(["dns_tcp", "dns_udp", "http", "https", "ntp"]):
        inst.append(("cloudru_evolution_compute_security_group_rule", "egress", rule,
                     {"id": uid(10 + i), "security_group_id": uid(1)}, False))
    return state(*inst, outputs={"ownership": {"value": {"box_id": box, "expires_on": expires_on}}})


def inventory(vms=(), disks=(), ips=(), subnets=("d58e80ef-fff1-43eb-b601-96fb358224b7",), project=PROJECT_ID,
              quotas=None) -> dict:
    row = lambda x: {"id": x[0], "name": x[1], "status": x[2] if len(x) > 2 else "RUNNING"}  # noqa: E731
    return {"planned_values": {"outputs": {"scoped_inventory": {"value": {
        "project_id": project, "vms": [row(x) for x in vms], "disks": [row(x) for x in disks],
        "ips": [row(x) for x in ips], "subnets": [{"id": s, "name": "default"} for s in subnets],
        "quotas": quotas or {}}}}}}


# The P1 resources that really exist in the project (lab/reports/access-2026-10-18/REPORT.md).
P1_LIVE = dict(
    vms=[("c9e589fc-a42a-4cc3-8038-fe7d73929713", "dm-p1-ui"), ("97a6e631-1d80-4212-aa69-ef6454b029df", "dm-p1-core", "STOPPED")],
    disks=[("9af43326-a6e1-45f1-8235-b82937a1f664", "dm-p1-ui-boot"), ("c5ef8c65-ad6c-45f4-bdaa-71a132a3dafe", "dm-p1-core-boot")],
    ips=[("33a27f64-e474-49ed-a17b-15f67dd16400", "dm-p1-ui-public-ip")],
)


def rc(address, type_, actions, before=None, after=None, **change):
    name = address.split(".")[1].split("[")[0]
    return {"address": address, "mode": "managed", "type": type_, "name": name,
            "change": {"actions": actions, "before": before, "after": after, **change}}


def fresh_plan(box="pilot1", *, admin_cidr="203.0.113.7/32", project=PROJECT_ID) -> dict:
    """Plan of a first apply: everything created, ids unknown."""
    p = f"amvp-box-{box}"
    unknown = {"id": True}
    changes = [
        rc("cloudru_evolution_compute_security_group.box", "cloudru_evolution_compute_security_group", ["create"],
           after={"name": f"{p}-sg", "project_id": project, "description": f"amvp-box:{box} managed"}, after_unknown=unknown),
        rc("cloudru_evolution_compute_disk.boot", "cloudru_evolution_compute_disk", ["create"],
           after={"name": f"{p}-boot", "project_id": project, "size": 20}, after_unknown=unknown),
        rc("cloudru_evolution_compute_interface.nic", "cloudru_evolution_compute_interface", ["create"],
           after={"name": f"{p}-nic", "project_id": project}, after_unknown={"id": True, "ip_address": True}),
        rc("cloudru_evolution_compute_external_ip.public", "cloudru_evolution_compute_external_ip", ["create"],
           after={"name": f"{p}-ip", "project_id": project}, after_unknown={"id": True, "ip_address": True}),
        rc("cloudru_evolution_compute_vm.box", "cloudru_evolution_compute_vm", ["create"],
           after={"name": f"{p}-vm", "project_id": project, "flavor": {"name": "gen-2-4"},
                  "cloud_init_userdata": "I2Nsb3VkLWNvbmZpZw=="},
           after_unknown=unknown),
    ]
    for rule in ["dns_tcp", "dns_udp", "http", "https", "ntp"]:
        changes.append(rc(f'cloudru_evolution_compute_security_group_rule.egress["{rule}"]',
                          "cloudru_evolution_compute_security_group_rule", ["create"],
                          after={"direction": "TRAFFIC_DIRECTION_EGRESS", "remote_ip_prefix": "0.0.0.0/0"},
                          after_unknown={"id": True, "security_group_id": True}))
    if admin_cidr:
        changes.append(rc("cloudru_evolution_compute_security_group_rule.ssh[0]",
                          "cloudru_evolution_compute_security_group_rule", ["create"],
                          after={"direction": "TRAFFIC_DIRECTION_INGRESS", "port_range": "22:22",
                                 "remote_ip_prefix": admin_cidr},
                          after_unknown={"id": True, "security_group_id": True}))
    return {"format_version": "1.2", "resource_changes": changes}


def destroy_plan(st: dict) -> dict:
    """Destroy plan for every instance of a raw state."""
    changes = []
    for res in st["resources"]:
        for inst in res["instances"]:
            key = inst.get("index_key")
            addr = f"{res['type']}.{res['name']}" + ("" if key is None else (f"[{key}]" if isinstance(key, int) else f'["{key}"]'))
            changes.append(rc(addr, res["type"], ["delete"], before=dict(inst["attributes"])))
    return {"format_version": "1.2", "resource_changes": changes}
