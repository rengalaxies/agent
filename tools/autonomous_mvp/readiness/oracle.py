"""Execution-grounded oracle for program 6-r1. Read by the scorer only.

Severity is not decided by the service, the static extractor or a model. Each
consumer's ``load_day`` is executed twice against a recording fake of the
``requests`` module: once with the providers as they are on ``main`` and once
as they are on the PR branch. The fake serves the fixture day's records with
the provider's page semantics (default page size per branch, explicit
``page_size``, cursor paging; a removed route answers 404). Then:

- the consumer never calls the changed operation: ``none``;
- it calls it and its result differs after the change (fewer records or an
  HTTP error): ``breaking``;
- it calls it and its result is the same: ``recheck``.

Consumers that read their base URL from deployment configuration run with that
configuration (world facts), which no readable repository holds.

Expected outcomes follow fixed rules (``expected_outcomes``), written down
before any run and recorded in ``program.json``.
"""
from __future__ import annotations

import os
import re
import sys
import threading
import types
from unittest import mock
from urllib.parse import urlsplit

_LOCK = threading.Lock()
ACCEPTABLE = {"answer": ["USEFUL"], "partial": ["PARTIAL", "USEFUL"], "abstain": ["ABSTAINED"],
              "no_impact": ["ABSTAINED"]}
STALE_AFTER_MINUTES = 24 * 60  # FreshnessConfig.runtime_max_age_seconds of the graph query


class HTTPError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.status = status


class _Response:
    def __init__(self, status, payload):
        self.status_code, self._payload = status, payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise HTTPError(self.status_code)

    def json(self):
        return self._payload


def provider_state(facts, branch):
    """{base_url: {route: default page size}} as the providers are on ``branch``."""
    state = {f"https://{facts['provider']}.test": dict(facts["defaults"][branch])}
    if facts["decoy"]:
        state[f"https://{facts['decoy']}.test"] = dict(facts["decoy_defaults"])
    return state


def execute(code, env, state, items, day):
    """Run one consumer. Returns (outcome, calls) where outcome is ("ok", n) or ("error", status)."""
    calls = []

    def get(url, params=None, timeout=None, **_):
        parts = urlsplit(url)
        base, route = f"{parts.scheme}://{parts.netloc}", parts.path
        params = dict(params or {})
        calls.append([base.removeprefix("https://").removesuffix(".test"), "GET", route])
        routes = state.get(base)
        if routes is None or route not in routes:
            return _Response(404, {"detail": "Not Found"})
        size = params.get("page_size") or routes[route]
        start = int(params.get("cursor") or 0)
        page = list(range(items))[start:start + size]
        following = start + size if start + size < items else None
        return _Response(200, {"items": page, "next_cursor": following})

    fake = types.ModuleType("requests")
    fake.get = get
    fake.HTTPError = HTTPError
    with _LOCK, mock.patch.dict(sys.modules, {"requests": fake}), mock.patch.dict(os.environ, env):
        namespace = {"__name__": "consumer_under_oracle"}
        exec(compile(code, "client.py", "exec"), namespace)  # generator-written fixture code only
        try:
            outcome = ["ok", len(namespace["load_day"](day))]
        except HTTPError as exc:
            outcome = ["error", exc.status]
    return outcome, calls


def owner_status(mapping, service):
    teams = mapping["services"].get(service)
    teams = [teams] if isinstance(teams, str) else list(teams or [])
    return "UNKNOWN" if not teams else "KNOWN" if len(teams) == 1 else "CONFLICT"


def runtime_basis(change, service):
    """'runtime' or 'stale_runtime' when an access-log window shows the service calling; else None."""
    runtime = change.get("runtime") or {}
    ages = [s["end_minutes_ago"] for s in runtime.get("segments", [])
            if any(r["client"] == service for r in s["records"])]
    if not ages:
        return None
    return "runtime" if min(ages) < STALE_AFTER_MINUTES else "stale_runtime"


def expected_outcomes(family, jira_intent, jira_consumers, pr_consumers, bases):
    """Fixed rules. ``bases``: {consumer: code | runtime | stale_runtime}."""
    def weak(names):
        return any(bases[n] in ("runtime", "stale_runtime") for n in names)

    if jira_intent in ("ambiguous", "vague"):
        jira = "abstain"  # the text does not identify the operation: naming consumers would be a guess
    elif not jira_consumers:
        jira = "no_impact"
    elif weak(jira_consumers):
        jira = "partial"
    else:
        jira = "answer"
    if not pr_consumers:
        pr = "no_impact"
    elif family == "F12_unclassified_change" or weak(pr_consumers):
        pr = "partial"
    else:
        pr = "answer"
    return jira, pr


def build_oracle(change, facts):
    changed = facts["changed_operation"]
    services, bases = {}, {}
    for name, repo in change["repositories"].items():
        visibility = "revoked" if name in change["grants"]["revoked"] else "granted"
        role = ("provider" if name == facts["provider"] else "decoy_provider" if name == facts["decoy"]
                else "consumer")
        entry = dict(role=role, visibility=visibility, owner_status=owner_status(change["ownership"], name))
        if role == "consumer":
            code = repo["branches"]["main"]["files"]["client.py"]
            env = facts["deployment_env"].get(name, {})
            before, calls = execute(code, env, provider_state(facts, "main"), facts["items_on_fixture_day"],
                                    facts["fixture_day"])
            after, _ = execute(code, env, provider_state(facts, "change"), facts["items_on_fixture_day"],
                               facts["fixture_day"])
            uses = bool(changed) and [changed["service"], changed["method"], changed["route"]] in calls
            severity = "none" if not uses else "breaking" if before != after else "recheck"
            kind = facts["consumer_kinds"][name]
            basis = (runtime_basis(change, name) if kind == "runtime_env" else "code")
            bases[name] = basis
            entry.update(kind=kind, severity=severity, basis=basis,
                         execution=dict(before=before, after=after, calls=calls))
        services[name] = entry
    expected = {n: s["severity"] for n, s in services.items()
                if s["role"] == "consumer" and s["visibility"] == "granted" and s["severity"] != "none"}
    jira_consumers = sorted(expected) if facts["jira_intent"] not in ("ambiguous", "vague") else []
    # The Jira text names the changed operation (or only its service). Who may be affected is the
    # set of consumers that the change affects; a service-only mention of a no-op change affects nobody.
    jira_outcome, pr_outcome = expected_outcomes(facts["family"], facts["jira_intent"], jira_consumers,
                                                 sorted(expected), bases)
    op = facts["operation"] if changed is None else changed
    paths = {n: dict(provider=op["service"], method=op["method"], route=op["route"],
                     callsite=dict(repository=n, path="client.py") if bases[n] == "code" else None,
                     basis=bases[n])
             for n in expected}
    negatives = sorted(n for n, s in services.items()
                       if s["role"] != "provider" and s["visibility"] == "granted" and n not in expected)
    return dict(
        change_id=change["change_id"], family=facts["family"], provider=facts["provider"],
        changed_operation=changed, world=facts, services=services,
        jira=dict(expected_outcome=jira_outcome, acceptable_statuses=ACCEPTABLE[jira_outcome],
                  expected_consumers=jira_consumers),
        pr=dict(expected_outcome=pr_outcome, acceptable_statuses=ACCEPTABLE[pr_outcome],
                expected_consumers={n: expected[n] for n in sorted(expected)}),
        paths=paths, negatives=negatives,
        revoked=sorted(change["grants"]["revoked"]))


DEFAULT_RE = re.compile(r'@app\.get\("([^"]+)"\)\ndef \w+\(day: str, cursor: str \| None = None, '
                        r'page_size: int \| None = (\d+)\)')


def check(change, facts, oracle):
    """Problems between a stored oracle and a fresh execution of the fixture; [] when grounded."""
    problems = []
    fresh = build_oracle(change, facts)
    for key in ("jira", "pr", "paths", "negatives", "revoked", "changed_operation"):
        if fresh[key] != oracle.get(key):
            problems.append(f"{key}_not_grounded")
    for name, entry in fresh["services"].items():
        if oracle["services"].get(name) != entry:
            problems.append(f"service_not_grounded:{name}")
    # The world facts must describe the committed provider code, or the execution proves nothing.
    for branch in ("main", "change"):
        text = change["repositories"][facts["provider"]]["branches"][branch]["files"].get("api.py", "")
        declared = {route: int(default) for route, default in DEFAULT_RE.findall(text)}
        if declared != facts["defaults"][branch]:
            problems.append(f"provider_code_differs_from_facts:{branch}")
    return problems
