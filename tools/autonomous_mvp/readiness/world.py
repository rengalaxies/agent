"""Deterministic scenario worlds for program 6-r1: one independent change per world.

A change is one Jira issue and the PR that implements it, on its own
multi-service Git stand in the Orders/Reporting pattern (provider repository
with a FastAPI declaration, consumer repositories with HTTP clients, a
same-named decoy provider where the family needs one). Every world is drawn
from ``random.Random("6-r1:<split>:<index>")``, so the same split and index
always give the same bytes.

Two outputs per change:

- the change file (``changes/<split>/<id>.json``): what the service and the
  baseline may see. Repositories with their branches, the Jira issue, the PR,
  addresses, the ownership mapping, runtime access-log records, read grants;
- the world facts (``world_facts``): what only the oracle builder reads.
  Deployment environment of consumers that take their URL from configuration,
  number of records on the fixture day, defaults per branch, the changed
  operation and how the Jira text names it.

Development and held-out splits draw provider, consumer and Jira names from
disjoint pools, so no repository content, task key or service name of the
held-out split appears in the development split.
"""
from __future__ import annotations

import random

PROGRAM = "6-r1"
SPLITS = ("development", "heldout")
SIZES = {"development": 20, "heldout": 60}
FIXTURE_DAY = "2026-10-01"
ORG = "acme"
INSTALLATION = "acme"
ENVIRONMENT = "prod"
RUNTIME_SOURCE = "access"

FAMILIES = (
    "F01_truncation",
    "F02_operation_removed",
    "F03_no_impact_noop",
    "F04_no_consumer_operation",
    "F05_runtime_only",
    "F06_code_only",
    "F07_stale_runtime",
    "F08_revoked_source",
    "F09_ownership_conflict",
    "F10_ambiguous_jira",
    "F11_vague_jira",
    "F12_unclassified_change",
)
# Development: every family once, then a second instance of the families with the most variation.
DEVELOPMENT_EXTRA = ("F01_truncation", "F02_operation_removed", "F03_no_impact_noop", "F05_runtime_only",
                     "F07_stale_runtime", "F08_revoked_source", "F09_ownership_conflict", "F10_ambiguous_jira")

POOLS = {
    "development": dict(
        providers=[("orders", "/orders", "list_orders", "ORD"), ("invoices", "/invoices", "list_invoices", "INV"),
                   ("shipments", "/shipments", "list_shipments", "SHP")],
        decoys=["billing", "warehouse"],
        consumers=["reporting", "archive", "ledger", "dashboard", "exporter", "analytics", "forecast", "audit",
                   "mailer", "registry"],
        first_issue=100),
    "heldout": dict(
        providers=[("tickets", "/tickets", "list_tickets", "TKT"), ("payments", "/payments", "list_payments", "PAY"),
                   ("bookings", "/bookings", "list_bookings", "BKG"), ("parcels", "/parcels", "list_parcels", "PCL")],
        decoys=["accounting", "depot", "treasury"],
        consumers=["insights", "vault", "statements", "cockpit", "extractor", "metrics", "planner", "inspector",
                   "courier", "catalog", "digest", "monitor", "tracker", "scheduler"],
        first_issue=500),
}

PROVIDER_OP = '''

@app.get("{route}")
def {function}(day: str, cursor: str | None = None, page_size: int | None = {default}):
    items, next_cursor = store.{reader}(day, cursor, page_size{extra})
    return {{"items": items, "next_cursor": next_cursor}}
'''
PROVIDER_HEAD = '''from fastapi import FastAPI

app = FastAPI()
'''
SINGLE = '''import requests

BASE_URL = "{base}"


def load_day(day):
    response = requests.get(BASE_URL + "{route}", params={{"day": day}}, timeout=10)
    response.raise_for_status()
    return response.json()["items"]
'''
EXPLICIT = '''import requests

BASE_URL = "{base}"


def load_day(day):
    response = requests.get(BASE_URL + "{route}", params={{"day": day, "page_size": 500}}, timeout=10)
    response.raise_for_status()
    return response.json()["items"]
'''
CURSOR = '''import requests

BASE_URL = "{base}"


def load_day(day):
    items, cursor = [], None
    while True:
        response = requests.get(BASE_URL + "{route}", params={{"day": day, "cursor": cursor}}, timeout=10)
        response.raise_for_status()
        page = response.json()
        items.extend(page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            return items
'''
# The URL comes from deployment configuration that is in no readable repository:
# the static profile cannot resolve it; only observed traffic links it.
RUNTIME_ENV = '''import os

import requests

BASE_URL = os.environ["{env}"]


def load_day(day):
    response = requests.get(BASE_URL + "{route}", params={{"day": day}}, timeout=10)
    response.raise_for_status()
    return response.json()["items"]
'''
TEMPLATES = {"single": SINGLE, "explicit": EXPLICIT, "cursor": CURSOR, "runtime_env": RUNTIME_ENV, "decoy": SINGLE,
             "bystander": SINGLE}


def base_url(service):
    return f"https://{service}.test"


def readme(service, extra=""):
    return f"# {service}\n\nService {service} of the 6-r1 stand.\n{extra}"


def provider_files(service, ops, *, readme_extra="", extra_files=None):
    """ops: [(route, function, default, extra)]; an empty list declares nothing."""
    text = PROVIDER_HEAD + "".join(
        PROVIDER_OP.format(route=route, function=function, default=default, reader="read_" + function.split("_", 1)[1],
                           extra=extra) for route, function, default, extra in ops)
    files = {"api.py": text, "README.md": readme(service, readme_extra)}
    files.update(extra_files or {})
    return files


def consumer_files(service, kind, *, provider, route, env=None):
    code = TEMPLATES[kind].format(base=base_url(provider), route=route, env=env)
    return {"client.py": code, "README.md": readme(service)}


def _family(split, index):
    if split == "heldout":
        return FAMILIES[index % len(FAMILIES)]
    return FAMILIES[index] if index < len(FAMILIES) else DEVELOPMENT_EXTRA[index - len(FAMILIES)]


def change_id(split, index):
    return f"{'D' if split == 'development' else 'H'}{index + 1:02d}"


def build(split, index):
    """Return (change, facts) for one world. Deterministic in (split, index)."""
    rng = random.Random(f"{PROGRAM}:{split}:{index}")
    pool = POOLS[split]
    family = _family(split, index)
    provider, route, function, project = rng.choice(pool["providers"])
    decoy = rng.choice(pool["decoys"])
    names = list(pool["consumers"])
    rng.shuffle(names)
    old = rng.choice([50, 100, 200])
    new = rng.choice([n for n in (10, 20, 25) if n < old])
    items = rng.randint(new + 1, old)
    method = "GET"
    issue_number = pool["first_issue"] + index
    key = f"{project}-{issue_number}"

    consumers = []  # (service, kind, target provider)

    def take(kind, count, target=provider):
        for _ in range(count):
            consumers.append((names.pop(), kind, target))

    # Every provider also declares an unchanged count operation; its callers are bystanders.
    count_op = (route + "/count", function.replace("list_", "count_"), 100, "")
    provider_ops_main = [(route, function, old, "")]
    provider_ops_change = [(route, function, new, "")]
    provider_extra_change = {}
    readme_extra_change = ""
    changed = dict(service=provider, method=method, route=route)
    decoy_present = False
    runtime = None
    revoked = []
    intent = "explicit"
    jira_summary = f"Уменьшить стандартный размер страницы {provider} с {old} до {new}"
    jira_description = f"{method} {route}: default page_size {old} -> {new}."

    if family == "F01_truncation":
        take("single", rng.randint(1, 2))
        take("cursor", rng.randint(0, 1))
        take("explicit", rng.randint(0, 1))
        decoy_present = True
        take("decoy", 1, decoy)
    elif family == "F02_operation_removed":
        take("single", rng.randint(1, 2))
        take("cursor", rng.randint(0, 1))
        take("explicit", rng.randint(0, 1))
        decoy_present = rng.random() < 0.5
        if decoy_present:
            take("decoy", 1, decoy)
        provider_ops_change = []
        jira_summary = f"Удалить устаревший список {provider}"
        jira_description = f"Сервис {provider} больше не отдаёт {method} {route}; эндпоинт удаляется."
    elif family == "F03_no_impact_noop":
        take("single", 1)
        take("cursor", rng.randint(0, 1))
        provider_ops_change = provider_ops_main
        changed = None
        if rng.random() < 0.5:
            readme_extra_change = "\nLocal run: see docs/runbook.md.\n"
        else:
            provider_extra_change = {"docs/runbook.md": f"# Runbook\n\nRestart {provider} with the deploy tool.\n"}
        if rng.random() < 0.5:
            intent = "service_only"
            jira_summary = f"Обновить README сервиса {provider}"
            jira_description = "Описать локальный запуск и ссылку на runbook. Поведение API не меняется."
        else:
            intent = "vague"
            jira_summary = "Обновить документацию по запуску"
            jira_description = "Описать локальный запуск и ссылку на runbook. Поведение API не меняется."
    elif family == "F04_no_consumer_operation":
        take("single", rng.randint(1, 2))
        take("cursor", rng.randint(0, 1))
        export = route + "/export"
        export_fn = function.replace("list_", "export_")
        provider_ops_main = [(route, function, old, ""), (export, export_fn, 500, "")]
        provider_ops_change = [(route, function, old, ""), (export, export_fn, 100, "")]
        changed = dict(service=provider, method=method, route=export)
        jira_summary = f"Уменьшить размер страницы выгрузки {provider} с 500 до 100"
        jira_description = f"{method} {export}: default page_size 500 -> 100."
    elif family in ("F05_runtime_only", "F07_stale_runtime"):
        take("runtime_env", 1)
        take("single", rng.randint(0, 1))
        stale = family == "F07_stale_runtime"
        observed = [c for c, kind, _ in consumers if kind == "runtime_env"]
        observed += [c for c, kind, _ in consumers if kind == "single" and rng.random() < 0.5]
        runtime = dict(source_id=RUNTIME_SOURCE, instrumented=[provider], segments=[dict(
            name="w1", end_minutes_ago=2 * 24 * 60 if stale else 0, minutes=10,
            records=[dict(client=c, method=method, route=route, status=200) for c in sorted(observed) for _ in range(3)])])
    elif family == "F06_code_only":
        take("single", 1)
        take("cursor", 1)
        observed = [c for c, kind, _ in consumers if kind == "cursor"]
        runtime = dict(source_id=RUNTIME_SOURCE, instrumented=[provider], segments=[dict(
            name="w1", end_minutes_ago=0, minutes=10,
            records=[dict(client=c, method=method, route=route, status=200) for c in observed for _ in range(3)])])
    elif family == "F08_revoked_source":
        take("single", 1)
        take("cursor", rng.randint(0, 1))
        take("single", 1)
        revoked = [consumers[-1][0]]
    elif family == "F09_ownership_conflict":
        take("single", rng.randint(1, 2))
        take("cursor", 1)
    elif family == "F10_ambiguous_jira":
        take("single", 1)
        take("cursor", rng.randint(0, 1))
        decoy_present = True
        take("decoy", 1, decoy)
        intent = "ambiguous"
        jira_summary = f"Уменьшить стандартный размер страницы с {old} до {new}"
        jira_description = f"{method} {route}: default page_size {old} -> {new}."
    elif family == "F11_vague_jira":
        take("single", rng.randint(1, 2))
        take("cursor", rng.randint(0, 1))
        intent = "vague"
        jira_summary = "Ускорить выдачу списка за день"
        jira_description = f"Отвечать меньшими страницами: {new} записей вместо {old} по умолчанию."
    elif family == "F12_unclassified_change":
        take("single", 1)
        take("cursor", rng.randint(0, 1))
        provider_ops_change = [(route, function, old, ', status="active"')]
        jira_summary = f"Показывать в списке {provider} только активные записи"
        jira_description = f"{method} {route}: передавать фильтр status=active в хранилище."
    else:  # pragma: no cover - FAMILIES is closed
        raise ValueError(family)
    take("bystander", rng.randint(1, 2))
    provider_ops_main = provider_ops_main + [count_op]
    provider_ops_change = provider_ops_change + [count_op]

    deployment_env = {}
    repositories = {provider: dict(service=provider, branches={
        "main": dict(parent=None, files=provider_files(provider, provider_ops_main)),
        "change": dict(parent="main", files=provider_files(provider, provider_ops_change,
                                                         readme_extra=readme_extra_change,
                                                         extra_files=provider_extra_change))})}
    if decoy_present:
        repositories[decoy] = dict(service=decoy, branches={"main": dict(parent=None, files=provider_files(
            decoy, [(route, "list_" + decoy, 100, "")]))})
    for service, kind, target in consumers:
        env = f"{target.upper()}_URL" if kind == "runtime_env" else None
        if env:
            deployment_env[service] = {env: base_url(target)}
        repositories[service] = dict(service=service, branches={"main": dict(parent=None, files=consumer_files(
            service, kind, provider=target, route=count_op[0] if kind == "bystander" else route, env=env))})

    services = sorted(repositories)
    owners = {s: f"team-{s}" for s in services}
    if family == "F09_ownership_conflict":
        named = [c for c, kind, _ in consumers if kind != "bystander"]
        owners[named[0]] = sorted([f"team-{named[0]}", "team-platform"])
        owners.pop(named[-1])
    addresses = [dict(service=provider, base_url=base_url(provider))]
    if decoy_present:
        addresses.append(dict(service=decoy, base_url=base_url(decoy)))

    cid = change_id(split, index)
    change = dict(
        schema="readiness-change-1", program=PROGRAM, change_id=cid, split=split, family=family,
        installation_id=INSTALLATION, environment=ENVIRONMENT, org=ORG,
        jira=dict(project=project, key=key, issue_id=10000 + issue_number, summary=jira_summary,
                  description=jira_description),
        pr=dict(repository=provider, number=issue_number, base_branch="main", head_branch="change",
                title=f"{key} {jira_summary}"),
        repositories={name: repositories[name] for name in services},
        addresses=addresses,
        ownership=dict(source="installation_mapping", version="ownership-1",
                       services={s: owners[s] for s in sorted(owners)}),
        grants=dict(revoked=revoked),
        runtime=runtime,
    )
    facts = dict(
        change_id=cid, family=family, provider=provider, decoy=decoy if decoy_present else None,
        operation=dict(service=provider, method=method, route=route),
        changed_operation=changed, items_on_fixture_day=items, fixture_day=FIXTURE_DAY,
        defaults={"main": {r: d for r, _, d, _ in provider_ops_main},
                  "change": {r: d for r, _, d, _ in provider_ops_change}},
        decoy_defaults={route: 100} if decoy_present else {},
        jira_intent=intent, consumer_kinds={s: k for s, k, _ in consumers},
        consumer_targets={s: t for s, _, t in consumers}, deployment_env=deployment_env,
        unclassified=family == "F12_unclassified_change",
    )
    return change, facts


def changes(split):
    return [build(split, i) for i in range(SIZES[split])]
