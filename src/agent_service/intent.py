"""Deterministic Jira intent: which graph operations a task names, before any diff exists.

Only explicit mentions count: ``METHOD /route`` and service names from the
graph. A route declared by several services is ambiguous unless the task also
names one of them, so a same-named ``GET /orders`` of another service is never
taken for the intended one. No match means "intent unclear", not "no impact".
A qualified model may later add candidates through the constitution executor;
this matcher stays the fact base.
"""

from __future__ import annotations

import re

ROUTE_RE = re.compile(r"(?<![A-Za-z])(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[A-Za-z0-9_\-./{}]*)")


def _route(path: str) -> str:
    path = re.sub(r"/{2,}", "/", path).rstrip("/.")
    return path or "/"


def named_services(texts: list[str], services) -> set[str]:
    text = " ".join(texts).lower()
    return {s for s in services if re.search(rf"(?<![a-z0-9_]){re.escape(s.lower())}(?![a-z0-9_])", text)}


def match_operations(operations: list[dict], texts: list[str]) -> tuple[list[str], str]:
    """Return (operation ids, reason). ``operations`` are core graph operations."""
    # A route path ("/orders") must not count as naming the service "orders".
    prose = [ROUTE_RE.sub(" ", t) for t in texts]
    services = named_services(prose, {o["service"] for o in operations})
    routes = {(m.group(1), _route(m.group(2))) for t in texts for m in ROUTE_RE.finditer(t)}
    if routes:
        matched = [o for o in operations if (o["method"], _route(o["path"])) in routes]
        if services:
            matched = [o for o in matched if o["service"] in services]
        elif len({o["service"] for o in matched}) > 1:
            return [], "ambiguous_route"
        return sorted(o["id"] for o in matched), "route" if matched else "route_not_in_graph"
    if services:
        return sorted(o["id"] for o in operations if o["service"] in services), "service"
    return [], "no_mention"
