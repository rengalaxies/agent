"""Ownership, inventory diff, plan guard and cleanup selection for the Cloud.ru service box.

Pure functions only: no network, no Terraform, no clock. ``boxctl.py`` feeds them
the JSON that ``terraform state pull``, ``terraform show -json <plan>`` and the
read-only inventory root (``inventory/main.tf``) produce.

A resource belongs to box ``<id>`` only when both hold:

* its name is exactly one of the names this tooling gives (``amvp-box-<id>-vm`` ...);
  a prefix match is not enough, ``amvp-box-pilot-1-vm`` is not box ``pilot``'s;
* its id is recorded in the box's Terraform state (and, for cleanup, in the
  ownership ledger written next to the state).

A live resource with an exact box name but an id the state does not know is an
orphan: an interrupted apply created it and lost the record. Orphans block
planning (a plan would create a duplicate) and are never deleted automatically.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import re
from dataclasses import dataclass

PROJECT_ID = "20853297-65b7-42a8-af40-25c8d2df4e11"
BOX_ID = re.compile(r"^[a-z][a-z0-9]{2,15}$")
MAX_TTL_DAYS = 120

TYPES = {
    "cloudru_evolution_compute_security_group": "security_group",
    "cloudru_evolution_compute_security_group_rule": "security_group_rule",
    "cloudru_evolution_compute_disk": "disk",
    "cloudru_evolution_compute_interface": "interface",
    "cloudru_evolution_compute_external_ip": "external_ip",
    "cloudru_evolution_compute_vm": "vm",
}
SUFFIX = {"security_group": "sg", "disk": "boot", "interface": "nic", "external_ip": "ip", "vm": "vm"}
# Terraform address of each named kind in main.tf; adopt writes import blocks to these.
ADDRESS = {
    "security_group": "cloudru_evolution_compute_security_group.box",
    "disk": "cloudru_evolution_compute_disk.boot",
    "interface": "cloudru_evolution_compute_interface.nic",
    "external_ip": "cloudru_evolution_compute_external_ip.public",
    "vm": "cloudru_evolution_compute_vm.box",
}
# Collections of the read-only inventory root. They cover every billed kind; security
# groups, rules and interfaces have no collection among the data sources verified in
# this project, so orphans of those free kinds are not detected.
INVENTORY_KINDS = {"vms": "vm", "disks": "disk", "ips": "external_ip"}
# sg + 5 egress rules + optional ssh rule + disk + nic + ip + vm
MAX_CREATES = 11
REDACTED_KEYS = {"remote_ip_prefix", "ip_address"}
OPEN_CIDR = "0.0.0.0/0"


class ScopeError(ValueError):
    """Input does not belong to the approved project or is malformed."""


def check_box_id(box_id: str) -> str:
    if not isinstance(box_id, str) or not BOX_ID.fullmatch(box_id):
        raise ScopeError("box_id must match " + BOX_ID.pattern)
    return box_id


def expected_name(box_id: str, kind: str) -> str:
    return f"amvp-box-{check_box_id(box_id)}-{SUFFIX[kind]}"


def expected_names(box_id: str) -> dict[str, str]:
    return {expected_name(box_id, kind): kind for kind in SUFFIX}


@dataclass(frozen=True)
class Live:
    kind: str
    id: str
    name: str
    status: str = ""


@dataclass(frozen=True)
class Recorded:
    address: str
    kind: str
    id: str
    name: str
    project_id: str
    tainted: bool = False


# -- parsing ---------------------------------------------------------------------------


def live_inventory(show_json: dict, project: str = PROJECT_ID) -> tuple[list[Live], dict]:
    """Resources and quota rows from ``terraform show -json`` of the inventory plan."""
    try:
        value = show_json["planned_values"]["outputs"]["scoped_inventory"]["value"]
    except (KeyError, TypeError):
        raise ScopeError("inventory_unresolved") from None
    if value.get("project_id") != project:
        raise ScopeError("inventory_project_mismatch")
    items = []
    for category, kind in INVENTORY_KINDS.items():
        for row in value.get(category) or []:
            if not row.get("id") or not isinstance(row.get("name"), str):
                raise ScopeError(f"inventory_row_malformed:{category}")
            items.append(Live(kind, row["id"], row["name"], row.get("status") or ""))
    meta = {"subnet_ids": sorted(s.get("id") for s in value.get("subnets") or [] if s.get("id")),
            "quotas": value.get("quotas") or {}}
    return items, meta


def _address(resource: dict, instance: dict) -> str:
    base = f"{resource['type']}.{resource['name']}"
    if resource.get("module"):
        base = f"{resource['module']}.{base}"
    key = instance.get("index_key")
    if key is None:
        return base
    if isinstance(key, int):
        return f"{base}[{key}]"
    return f'{base}["{key}"]'


def state_records(state: dict | None) -> list[Recorded]:
    """Managed resources from raw state (``terraform state pull``); None or {} means no state yet."""
    out = []
    for resource in (state or {}).get("resources", []):
        if resource.get("mode") != "managed":
            continue
        kind = TYPES.get(resource.get("type"))
        if kind is None:
            raise ScopeError(f"state_unexpected_type:{resource.get('type')}")
        for instance in resource.get("instances", []):
            attrs = instance.get("attributes") or {}
            out.append(Recorded(address=_address(resource, instance), kind=kind, id=attrs.get("id") or "",
                                name=attrs.get("name") or "", project_id=attrs.get("project_id") or "",
                                tainted=instance.get("status") == "tainted"))
    return out


# -- inventory diff --------------------------------------------------------------------


def classify(live: list[Live], state: list[Recorded], box_id: str, project: str = PROJECT_ID) -> dict:
    """Compare the live project with the box's state.

    Returns owned/orphans/duplicates/missing/foreign plus ``problems`` that must stop a plan.
    """
    names = expected_names(box_id)
    by_id = {r.id: r for r in state if r.id}
    problems = []
    for r in state:
        if r.kind != "security_group_rule":
            if r.project_id != project:
                problems.append(f"state_out_of_project:{r.address}")
            if r.name not in names or names[r.name] != r.kind:
                problems.append(f"state_name_not_owned:{r.address}")
    ours = [x for x in live if names.get(x.name) == x.kind]
    owned = [x for x in ours if x.id in by_id]
    orphans = [x for x in ours if x.id not in by_id]
    counts: dict[str, list[Live]] = {}
    for x in ours:
        counts.setdefault(x.name, []).append(x)
    duplicates = {name: sorted(x.id for x in xs) for name, xs in counts.items() if len(xs) > 1}
    live_ids = {x.id for x in live}
    inventoried = set(INVENTORY_KINDS.values())
    missing = [r for r in state if r.kind in inventoried and r.id and r.id not in live_ids]
    foreign: dict[str, int] = {}
    for x in live:
        if x not in ours:
            foreign[x.kind] = foreign.get(x.kind, 0) + 1
    for x in orphans:
        problems.append(f"orphan:{x.kind}:{x.id}")
    for name in duplicates:
        problems.append(f"duplicate_name:{name}")
    return {"box_id": box_id, "owned": owned, "orphans": orphans, "duplicates": duplicates,
            "missing": missing, "foreign": foreign, "problems": problems}


def untaint_candidates(state: list[Recorded], box_id: str, project: str = PROJECT_ID) -> list[str]:
    """Tainted interfaces that exist with our name and project.

    The provider marked P1 interfaces tainted after a VM attachment inconsistency although
    they were created (cloudru-apply-protected.yml). Replacing a NIC also drops its public IP
    binding, so recovery untaints them instead. Other tainted kinds are replaced by the plan.
    """
    nic = expected_name(box_id, "interface")
    return [r.address for r in state
            if r.tainted and r.kind == "interface" and r.id and r.name == nic and r.project_id == project]


def adopt_block(classification: dict, kind: str, resource_id: str) -> str:
    """An import block for one orphan; refuses anything that is not an orphan of this box."""
    match = [x for x in classification["orphans"] if x.kind == kind and x.id == resource_id]
    if not match:
        raise ScopeError(f"not_an_orphan_of_this_box:{kind}:{resource_id}")
    if classification["duplicates"].get(match[0].name):
        raise ScopeError(f"duplicate_name_needs_owner_decision:{match[0].name}")
    if not re.fullmatch(r"[0-9a-f-]{36}", resource_id):
        raise ScopeError("resource_id_not_uuid")
    return f'import {{\n  to = {ADDRESS[kind]}\n  id = "{resource_id}"\n}}\n'


# -- plan guard ------------------------------------------------------------------------


def _deleting(actions: list[str]) -> bool:
    return "delete" in actions


def guard_plan(plan: dict, mode: str, box_id: str, state: list[Recorded], *, adopt_ids=(),
               project: str = PROJECT_ID) -> list[str]:
    """Problems that forbid applying ``plan``. Empty list means the plan stays inside the box.

    apply: create/update/no-op of box resources; delete only of tainted resources and of
    security group rules (closing SSH); import only of the orphans the owner adopted.
    destroy: only deletes, only of resources recorded in state, and all of them.
    """
    if mode not in ("apply", "destroy"):
        raise ScopeError("mode must be apply or destroy")
    names = expected_names(box_id)
    recorded = {r.address: r for r in state}
    problems = []
    creates = 0
    deleted = set()
    for rc in plan.get("resource_changes") or []:
        address = rc.get("address", "?")
        if rc.get("mode") == "data":
            continue
        kind = TYPES.get(rc.get("type"))
        if kind is None:
            problems.append(f"type_not_allowed:{address}")
            continue
        change = rc.get("change") or {}
        actions = change.get("actions") or []
        before, after = change.get("before") or {}, change.get("after") or {}
        for side in (before, after):
            if "project_id" in side and side["project_id"] not in (None, project):
                problems.append(f"project_mismatch:{address}")
            name = side.get("name")
            if kind != "security_group_rule" and name is not None and names.get(name) != kind:
                problems.append(f"name_not_owned:{address}")
        if change.get("importing"):
            if mode != "apply" or (change["importing"].get("id") not in set(adopt_ids)):
                problems.append(f"import_not_adopted:{address}")
        if mode == "destroy":
            if actions != ["delete"]:
                problems.append(f"destroy_plan_has_{'-'.join(actions) or 'nothing'}:{address}")
                continue
            r = recorded.get(address)
            if r is None or before.get("id") != r.id:
                problems.append(f"delete_not_recorded:{address}")
                continue
            deleted.add(address)
            continue
        if "create" in actions:
            creates += 1
        if _deleting(actions):
            r = recorded.get(address)
            if r is None:
                problems.append(f"delete_not_recorded:{address}")
            elif not (r.tainted or kind == "security_group_rule"):
                problems.append(f"replace_or_delete_forbidden:{address}")
    if mode == "destroy":
        left = sorted(set(recorded) - deleted)
        if left:
            problems.append("destroy_incomplete:" + ",".join(left))
    elif creates > MAX_CREATES:
        problems.append(f"too_many_creates:{creates}>{MAX_CREATES}")
    return problems


# -- plan digest -----------------------------------------------------------------------


def _tag(key: bytes, value) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return "hmac:" + hmac.new(key, raw, hashlib.sha256).hexdigest()[:16]


def _redact(value, sensitive, unknown, key: bytes, field: str | None = None):
    if unknown is True:
        return "(known after apply)"
    if sensitive is True:
        return _tag(key, value)
    if field in REDACTED_KEYS and isinstance(value, str) and value and value != OPEN_CIDR:
        return _tag(key, value)
    if field == "cloud_init_userdata" and isinstance(value, str):
        return "sha256:" + hashlib.sha256(value.encode()).hexdigest()
    if isinstance(value, dict):
        sens = sensitive if isinstance(sensitive, dict) else {}
        unk = unknown if isinstance(unknown, dict) else {}
        keys = set(value) | {k for k, v in unk.items() if v is True}
        return {k: _redact(value.get(k), sens.get(k), unk.get(k), key, k) for k in sorted(keys)}
    if isinstance(value, list):
        sens = sensitive if isinstance(sensitive, list) else []
        unk = unknown if isinstance(unknown, list) else []
        return [_redact(v, sens[i] if i < len(sens) else None, unk[i] if i < len(unk) else None, key, field)
                for i, v in enumerate(value)]
    return value


def plan_projection(plan: dict, *, key: bytes, commit: str, box_id: str, mode: str, recovery=()) -> dict:
    """What the reviewer approves: every change with secrets and addresses replaced by keyed tags.

    ``recovery`` lists the state addresses the approved apply untaints before planning
    (``untaint_candidates``). The review plan is computed on a local copy with that recovery
    already applied, so the digest covers both the state repair and the resulting changes.

    The tags are HMAC-SHA256 with a key only the workflow has, so a published projection
    does not let anyone brute-force the owner's /32, while a different CIDR, image or secret
    still changes the digest.
    """
    if len(key) < 32:
        raise ScopeError("digest key must be at least 32 bytes")
    if not re.fullmatch(r"[0-9a-f]{40}", commit or ""):
        raise ScopeError("commit must be a full git sha")
    changes = []
    for rc in sorted(plan.get("resource_changes") or [], key=lambda x: x.get("address", "")):
        change = rc.get("change") or {}
        item = {"address": rc.get("address"), "actions": change.get("actions") or [],
                "importing": (change.get("importing") or {}).get("id")}
        if item["actions"] != ["no-op"]:
            item["before"] = _redact(change.get("before"), change.get("before_sensitive"), None, key)
            item["after"] = _redact(change.get("after"), change.get("after_sensitive"), change.get("after_unknown"), key)
        changes.append(item)
    return {"format": "amvp-box-plan-2", "commit": commit, "box_id": check_box_id(box_id), "mode": mode,
            "recovery": sorted(recovery), "changes": changes}


def digest(projection: dict) -> str:
    raw = json.dumps(projection, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hashlib.sha256(raw).hexdigest()


# -- ttl, ledger, cleanup --------------------------------------------------------------


def check_ttl(expires_on: str, today: dt.date, max_days: int = MAX_TTL_DAYS) -> list[str]:
    try:
        end = dt.date.fromisoformat(expires_on)
    except (TypeError, ValueError):
        return ["expires_on_not_a_date"]
    if end <= today:
        return ["expires_on_not_in_future"]
    if (end - today).days > max_days:
        return [f"expires_on_beyond_{max_days}_days"]
    return []


def ttl_state(expires_on: str, today: dt.date) -> dict:
    end = dt.date.fromisoformat(expires_on)
    left = (end - today).days
    return {"expires_on": expires_on, "days_left": left, "expired": left <= 0}


def ledger_from_state(state: list[Recorded], *, box_id: str, expires_on: str, commit: str, plan_digest: str,
                      project: str = PROJECT_ID) -> dict:
    return {"format": "amvp-box-ownership-1", "box_id": check_box_id(box_id), "project_id": project,
            "expires_on": expires_on, "commit": commit, "plan_digest": plan_digest,
            "resources": {r.address: r.id for r in sorted(state, key=lambda r: r.address) if r.id}}


def cleanup_selection(plan: dict, state: list[Recorded], ledger: dict | None, live: list[Live], box_id: str,
                      project: str = PROJECT_ID) -> dict:
    """Check a destroy plan against state, ledger and live inventory.

    Deletes only what both records name; orphans and foreign resources stay and are listed.
    """
    problems = guard_plan(plan, "destroy", box_id, state, project=project)
    recorded = {r.address: r.id for r in state if r.id}
    if not ledger:
        problems.append("ledger_missing")
    else:
        if ledger.get("box_id") != box_id or ledger.get("project_id") != project:
            problems.append("ledger_scope_mismatch")
        if ledger.get("resources") != recorded:
            problems.append("ledger_differs_from_state")
    report = classify(live, state, box_id, project)
    selected = sorted(recorded.items())
    return {"delete": [{"address": a, "id": i} for a, i in selected],
            "left_in_place": {"orphans": [x.__dict__ for x in report["orphans"]], "foreign": report["foreign"]},
            "problems": problems}


def quota_problems(quotas: dict, need: dict) -> list[str]:
    """``need`` like {"network.ip.quantity": 1, "compute.vcpu": 2}; unknown limits are not blockers."""
    problems = []
    rows = {}
    for scope in ("organization", "project"):
        for row in quotas.get(scope) or []:
            rows.setdefault(row.get("resource_type_code", "").lower(), []).append((scope, row))
    for code, amount in need.items():
        for scope, row in rows.get(code, []):
            limit = row.get("individual_limit")
            used = max(row.get("individual_usage") or 0, row.get("aggregated_usage") or 0)
            if isinstance(limit, (int, float)) and limit >= 0 and used + amount > limit:
                problems.append(f"quota:{scope}:{code}:{used}+{amount}>{limit}")
    return problems
