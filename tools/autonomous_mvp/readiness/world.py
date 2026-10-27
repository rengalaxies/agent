"""Deterministic scenario worlds for the readiness programs: one independent change per world.

A change is one Jira issue and the PR that implements it, on its own
multi-service Git stand in the Orders/Reporting pattern (provider repository
with a FastAPI declaration, consumer repositories with HTTP clients, a
same-named decoy provider where the family needs one). Every world is drawn
from ``random.Random("<revision>:<split>:<index>")``, so the same revision,
split and index always give the same bytes.

Two outputs per change:

- the change file (``changes/<split>/<id>.json``): what the service and the
  baseline may see. Repositories with their branches, the Jira issue, the PR,
  addresses, the ownership mapping, runtime access-log records, read grants;
- the world facts (``world_facts``): what only the oracle builder reads.
  Deployment environment of consumers that take their URL from configuration,
  number of records on the fixture day, defaults per branch, the changed
  operation and how the Jira text names it.

Within a revision, development and held-out splits draw provider, consumer and
Jira names from disjoint pools. Revision 6-r2 also uses names that appear in
neither split of 6-r1, and 6-r3 names appear in neither split of 6-r1 or 6-r2.
6-r1 and 6-r2 are historical: their configurations here regenerate their
committed files byte for byte, and nothing about them changes.
"""
from __future__ import annotations

import random

FIXTURE_DAY = "2026-10-01"
ORG = "acme"
INSTALLATION = "acme"
ENVIRONMENT = "prod"
RUNTIME_SOURCE = "access"
SPLITS = ("development", "heldout")
CURRENT = "6-r3"

FAMILIES_6R1 = (
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

REVISIONS = {
    "6-r1": dict(
        families=FAMILIES_6R1, sizes={"development": 20, "heldout": 60}, development_extra=DEVELOPMENT_EXTRA,
        jira_variants=False,
        pools={
            "development": dict(
                providers=[("orders", "/orders", "list_orders", "ORD"),
                           ("invoices", "/invoices", "list_invoices", "INV"),
                           ("shipments", "/shipments", "list_shipments", "SHP")],
                decoys=["billing", "warehouse"],
                consumers=["reporting", "archive", "ledger", "dashboard", "exporter", "analytics", "forecast",
                           "audit", "mailer", "registry"],
                first_issue=100),
            "heldout": dict(
                providers=[("tickets", "/tickets", "list_tickets", "TKT"),
                           ("payments", "/payments", "list_payments", "PAY"),
                           ("bookings", "/bookings", "list_bookings", "BKG"),
                           ("parcels", "/parcels", "list_parcels", "PCL")],
                decoys=["accounting", "depot", "treasury"],
                consumers=["insights", "vault", "statements", "cockpit", "extractor", "metrics", "planner",
                           "inspector", "courier", "catalog", "digest", "monitor", "tracker", "scheduler"],
                first_issue=500)}),
    # 6-r2: the 6-r1 families plus F13 (a contract change of a named service without the operation),
    # varied Jira wording for F03 and F13, and names disjoint from both 6-r1 splits.
    "6-r2": dict(
        families=FAMILIES_6R1 + ("F13_service_contract_unspecified",), sizes={"development": 21, "heldout": 65},
        development_extra=DEVELOPMENT_EXTRA, jira_variants=True,
        pools={
            "development": dict(
                providers=[("quotes", "/quotes", "list_quotes", "QTE"),
                           ("returns", "/returns", "list_returns", "RTN"),
                           ("leases", "/leases", "list_leases", "LSE")],
                decoys=["fleet", "pricing"],
                consumers=["gateway", "notifier", "syncer", "console", "feeder", "auditor", "reviewer", "pipeline",
                           "importer", "balancer"],
                first_issue=300),
            "heldout": dict(
                providers=[("claims", "/claims", "list_claims", "CLM"),
                           ("rentals", "/rentals", "list_rentals", "RNT"),
                           ("permits", "/permits", "list_permits", "PMT"),
                           ("voyages", "/voyages", "list_voyages", "VOY")],
                decoys=["registrar", "clearing", "harbor"],
                consumers=["atlas", "beacon", "compass", "harvest", "lantern", "mosaic", "nimbus", "orbit", "prism",
                           "quartz", "relay", "summit", "tundra", "vector"],
                first_issue=700)}),
    # 6-r3: the 6-r2 families plus F14 (a route named only as unchanged), Jira wording with negated
    # routes, paraphrases and English for F01, F03, F13 and F14, and names disjoint from 6-r1 and 6-r2.
    "6-r3": dict(
        families=FAMILIES_6R1 + ("F13_service_contract_unspecified", "F14_route_stated_unchanged"),
        sizes={"development": 22, "heldout": 70}, development_extra=DEVELOPMENT_EXTRA, jira_variants=True,
        wording="6-r3",
        pools={
            "development": dict(
                providers=[("refunds", "/refunds", "list_refunds", "RFD"),
                           ("tariffs", "/tariffs", "list_tariffs", "TRF"),
                           ("visits", "/visits", "list_visits", "VIS")],
                decoys=["customs", "postal"],
                consumers=["abacus", "bridge", "cipher", "delta", "ember", "falcon", "glacier", "harbinger", "iris",
                           "juniper"],
                first_issue=900),
            "heldout": dict(
                providers=[("loans", "/loans", "list_loans", "LON"),
                           ("tenders", "/tenders", "list_tenders", "TND"),
                           ("cargo", "/cargo", "list_cargo", "CRG"),
                           ("licenses", "/licenses", "list_licenses", "LIC")],
                decoys=["notary", "mint", "exchange"],
                consumers=["kestrel", "lotus", "meridian", "nebula", "onyx", "pulsar", "quill", "raven", "sierra",
                           "topaz", "umbra", "willow", "xenon", "zephyr"],
                first_issue=1100)}),
}
# The current revision, for callers that only ever mean it.
PROGRAM = CURRENT
FAMILIES = REVISIONS[CURRENT]["families"]
SIZES = REVISIONS[CURRENT]["sizes"]
POOLS = REVISIONS[CURRENT]["pools"]

# 6-r2 Jira wording, (summary, description); {p} provider, {o}/{n} old/new page size. Written after
# the intent fix by the same executor: they check these phrasings, not language coverage.
NOOP_SERVICE_TEXTS = (
    ("Обновить README сервиса {p}", "Описать локальный запуск и ссылку на runbook. Поведение API не меняется."),
    ("{p}: дописать runbook", "Только документация, контракт и ответы остаются прежними."),
    ("Исправить опечатки в документации {p}", "Код сервиса не трогаем."),
)
CANDIDATE_TEXTS = (
    ("{p}: уменьшить размер страницы по умолчанию", "Отдавать по {n} записей вместо {o}."),
    ("Сократить ответ {p} для дневной выгрузки", "Стандартный лимит {o} -> {n}."),
    ("{p}: отдавать данные меньшими порциями", "Вместо {o} записей за раз отдавать {n}."),
)
# 6-r3 wording: {m} {r} method and route of the changed operation. Written by the executor after the
# route-negation fix of 26.10.2026, like the 6-r2 texts: a check of these phrasings, including one
# (a route named positively with no change) that the deterministic matcher is known to misread.
NOOP_SERVICE_TEXTS_6R3 = NOOP_SERVICE_TEXTS + (
    ("{p}: refresh the README", "Describe the local run. No API changes."),
)
CANDIDATE_TEXTS_6R3 = CANDIDATE_TEXTS + (
    ("{p}: return smaller pages by default", "Default limit {o} -> {n} records."),
)
TRUNCATION_TEXTS_6R3 = (
    ("Уменьшить стандартный размер страницы {p} с {o} до {n}", "{m} {r}: default page_size {o} -> {n}."),
    ("{p}: page size {o} -> {n}", "{m} {r}: default page_size {o} -> {n}. {m} {r}/count is unchanged."),
    ("Уменьшить страницу {p}", "{m} {r}/count не меняется; {m} {r}: размер страницы по умолчанию {o} -> {n}."),
    ("{p}: отдавать {n} записей на страницу", "Для {m} {r} по умолчанию теперь {n} вместо {o}."),
)
ROUTE_UNCHANGED_TEXTS = (
    ("{p}: обновить README", "{m} {r} не меняется. Описать локальный запуск."),
    ("{p}: refresh the runbook", "{m} {r} does not change; only the docs are updated."),
    ("Документация {p}", "Контракт {m} {r} остаётся прежним, правим только описание."),
    ("Описать {m} {r} в README", "Поведение {m} {r} без изменений."),
)

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


def readme(service, extra="", revision=CURRENT):
    return f"# {service}\n\nService {service} of the {revision} stand.\n{extra}"


def provider_files(service, ops, *, readme_extra="", extra_files=None, revision=CURRENT):
    """ops: [(route, function, default, extra)]; an empty list declares nothing."""
    text = PROVIDER_HEAD + "".join(
        PROVIDER_OP.format(route=route, function=function, default=default, reader="read_" + function.split("_", 1)[1],
                           extra=extra) for route, function, default, extra in ops)
    files = {"api.py": text, "README.md": readme(service, readme_extra, revision)}
    files.update(extra_files or {})
    return files


def consumer_files(service, kind, *, provider, route, env=None, revision=CURRENT):
    code = TEMPLATES[kind].format(base=base_url(provider), route=route, env=env)
    return {"client.py": code, "README.md": readme(service, revision=revision)}


def _family(split, index, revision=CURRENT):
    config = REVISIONS[revision]
    families = config["families"]
    if split == "heldout":
        return families[index % len(families)]
    return families[index] if index < len(families) else config["development_extra"][index - len(families)]


def change_id(split, index):
    return f"{'D' if split == 'development' else 'H'}{index + 1:02d}"


def build(split, index, revision=CURRENT):
    """Return (change, facts) for one world. Deterministic in (revision, split, index)."""
    config = REVISIONS[revision]
    rng = random.Random(f"{revision}:{split}:{index}")
    pool = config["pools"][split]
    family = _family(split, index, revision)
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
        if config.get("wording") == "6-r3":
            summary, description = rng.choice(TRUNCATION_TEXTS_6R3)
            jira_summary = summary.format(p=provider, o=old, n=new, m=method, r=route)
            jira_description = description.format(p=provider, o=old, n=new, m=method, r=route)
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
            if config["jira_variants"]:
                summary, description = rng.choice(NOOP_SERVICE_TEXTS_6R3 if config.get("wording") == "6-r3"
                                                  else NOOP_SERVICE_TEXTS)
                jira_summary, jira_description = summary.format(p=provider), description
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
    elif family == "F13_service_contract_unspecified":
        # As F01, but the Jira text names the provider and a contract change, not the operation.
        take("single", rng.randint(1, 2))
        take("cursor", rng.randint(0, 1))
        intent = "candidate"
        summary, description = rng.choice(CANDIDATE_TEXTS_6R3 if config.get("wording") == "6-r3"
                                          else CANDIDATE_TEXTS)
        jira_summary = summary.format(p=provider, o=old, n=new)
        jira_description = description.format(p=provider, o=old, n=new)
    elif family == "F14_route_stated_unchanged":
        # As F03, but the Jira text names the operation only to say that it does not change.
        take("single", 1)
        take("cursor", rng.randint(0, 1))
        provider_ops_change = provider_ops_main
        changed = None
        provider_extra_change = {"docs/runbook.md": f"# Runbook\n\nRestart {provider} with the deploy tool.\n"}
        intent = "route_unchanged"
        summary, description = rng.choice(ROUTE_UNCHANGED_TEXTS)
        jira_summary = summary.format(p=provider, m=method, r=route)
        jira_description = description.format(p=provider, m=method, r=route)
    else:  # pragma: no cover - the families of a revision are closed
        raise ValueError(family)
    take("bystander", rng.randint(1, 2))
    provider_ops_main = provider_ops_main + [count_op]
    provider_ops_change = provider_ops_change + [count_op]

    deployment_env = {}
    repositories = {provider: dict(service=provider, branches={
        "main": dict(parent=None, files=provider_files(provider, provider_ops_main, revision=revision)),
        "change": dict(parent="main", files=provider_files(provider, provider_ops_change,
                                                         readme_extra=readme_extra_change,
                                                         extra_files=provider_extra_change, revision=revision))})}
    if decoy_present:
        repositories[decoy] = dict(service=decoy, branches={"main": dict(parent=None, files=provider_files(
            decoy, [(route, "list_" + decoy, 100, "")], revision=revision))})
    for service, kind, target in consumers:
        env = f"{target.upper()}_URL" if kind == "runtime_env" else None
        if env:
            deployment_env[service] = {env: base_url(target)}
        repositories[service] = dict(service=service, branches={"main": dict(parent=None, files=consumer_files(
            service, kind, provider=target, route=count_op[0] if kind == "bystander" else route, env=env,
            revision=revision))})

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
        schema="readiness-change-1", program=revision, change_id=cid, split=split, family=family,
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


def changes(split, revision=CURRENT):
    return [build(split, i, revision) for i in range(REVISIONS[revision]["sizes"][split])]
