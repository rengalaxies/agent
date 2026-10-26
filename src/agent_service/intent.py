"""Deterministic Jira intent: which graph operations a task names, before any diff exists.

Only explicit mentions count: ``METHOD /route`` and service names from the
graph. A route declared by several services is ambiguous unless the task also
names one of them, so a same-named ``GET /orders`` of another service is never
taken for the intended one. No match means "intent unclear", not "no impact".
A qualified model may later add candidates through the constitution executor;
this matcher stays the fact base.

A service name alone does not say that the service's API changes. The text is
read clause by clause for contract wording (API, endpoint, response, field,
page size, removal and so on):

- a route, or a named service with a service-wide contract change ("all
  endpoints"): ``explicit``, the preliminary answer;
- a named service with a contract change but no operation: ``candidate``, its
  operations are possible targets only;
- a named service without contract wording, or with the contract stated as
  unchanged: ``none``, nothing is claimed about its consumers.

The word lists are a fixed profile, not language understanding: a contract
change described in other words stays ``service_only`` and the PR diff decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

ROUTE_RE = re.compile(r"(?<![A-Za-z])(GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(/[A-Za-z0-9_\-./{}]*)")

# Stems, matched at a word start, case-insensitive.
CONTRACT_WORDS = (
    "api", "endpoint", "эндпоинт", "ручк", "маршрут", "route", "контракт", "contract", "response", "ответ",
    "request", "запрос", "поле", "поля", "field", "параметр", "parameter", "query", "pagination", "пагинац",
    "страниц", "page", "page_size", "limit", "лимит", "курсор", "cursor", "фильтр", "filter", "формат",
    "format", "schema", "схем", "status code", "код ответа", "удал", "remove", "delete", "deprecat", "устарев",
    "rename", "переимен", "сортировк", "sort", "тип данных", "timeout", "таймаут")
UNCHANGED = re.compile(
    r"(не\s+(меня|изменя)\w*|без\s+изменени\w*|остаётся|остается|прежн\w*|unchanged|not\s+chang\w*|"
    r"(does|do|will)\s*n[o']t\s+change|no\s+(api\s+|contract\s+)?changes?)", re.I)
SERVICE_WIDE = re.compile(
    r"(все[хм]?|всего|весь|кажд\w*|целиком|all|every|entire|whole)\s+(\w+\s+)?"
    r"(эндпоинт\w*|ручк\w*|маршрут\w*|операци\w*|метод\w*|api|endpoints?|operations?|routes?)", re.I)
CLAUSE_SPLIT = re.compile(r"[.;!?\n]+|,\s*(?:но|а|однако|but|while)\s+|\s+(?:но|однако|but)\s+", re.I)


@dataclass
class Intent:
    operation_ids: list[str]
    reason: str
    confidence: str  # explicit | candidate | none
    services: list[str] = field(default_factory=list)


def _route(path: str) -> str:
    path = re.sub(r"/{2,}", "/", path).rstrip("/.")
    return path or "/"


def named_services(texts: list[str], services) -> set[str]:
    text = " ".join(texts).lower()
    return {s for s in services if re.search(rf"(?<![a-z0-9_]){re.escape(s.lower())}(?![a-z0-9_])", text)}


def _has_contract_word(clause: str) -> bool:
    return any(re.search(rf"(?<![\w]){re.escape(w)}", clause, re.I) for w in CONTRACT_WORDS)


def contract_wording(texts: list[str]) -> str:
    """``changed``, ``unchanged`` (only negated mentions) or ``absent``."""
    changed = unchanged = False
    for text in texts:
        for clause in CLAUSE_SPLIT.split(text):
            if not _has_contract_word(clause):
                continue
            if UNCHANGED.search(clause):
                unchanged = True
            else:
                changed = True
    return "changed" if changed else "unchanged" if unchanged else "absent"


def changed_routes(texts: list[str]) -> set[tuple[str, str]]:
    """Routes the text names, except those named only in clauses that say they do not change.

    If every mention is negated, the routes stay: the task still points at them.
    """
    named, negated = set(), set()
    for text in texts:
        found = []

        def placeholder(m):
            # Keeps the dots and slashes of a route out of the clause split.
            found.append((m.group(1), _route(m.group(2))))
            return f" @@{len(found) - 1}@@ "

        masked = ROUTE_RE.sub(placeholder, text)
        for clause in CLAUSE_SPLIT.split(masked):
            for i in re.findall(r"@@(\d+)@@", clause):
                (negated if UNCHANGED.search(clause) else named).add(found[int(i)])
    return named or negated


def match_intent(operations: list[dict], texts: list[str]) -> Intent:
    """``operations`` are graph operations: id, service, method, path."""
    # A route path ("/orders") must not count as naming the service "orders".
    prose = [ROUTE_RE.sub(" ", t) for t in texts]
    services = named_services(prose, {o["service"] for o in operations})
    routes = changed_routes(texts)
    if routes:
        matched = [o for o in operations if (o["method"], _route(o["path"])) in routes]
        if services:
            matched = [o for o in matched if o["service"] in services]
        elif len({o["service"] for o in matched}) > 1:
            return Intent([], "ambiguous_route", "none", sorted({o["service"] for o in matched}))
        return Intent(sorted(o["id"] for o in matched), "route" if matched else "route_not_in_graph",
                      "explicit" if matched else "none", sorted({o["service"] for o in matched}))
    if not services:
        return Intent([], "no_mention", "none")
    of_services = sorted(o["id"] for o in operations if o["service"] in services)
    wording = contract_wording(prose)
    if wording == "unchanged":
        return Intent([], "contract_unchanged_stated", "none", sorted(services))
    if wording == "absent":
        return Intent([], "service_only", "none", sorted(services))
    if any(SERVICE_WIDE.search(t) for t in prose):
        return Intent(of_services, "service_wide", "explicit", sorted(services))
    return Intent(of_services, "service_contract_unspecified", "candidate", sorted(services))


def match_operations(operations: list[dict], texts: list[str]) -> tuple[list[str], str]:
    """Return (operation ids, reason). Kept for callers that need only the ids."""
    intent = match_intent(operations, texts)
    return intent.operation_ids, intent.reason
