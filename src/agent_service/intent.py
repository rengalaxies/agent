"""Deterministic Jira intent: which graph operations a task names, before any diff exists.

Only explicit non-documentation mentions count: ``METHOD /route`` and service names from the
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
- a route named only in clauses that say it does not change: no target; the
  rest of the text is read as if the route were not there, and with nothing
  else stated the intent is ``none`` (``routes_stated_unchanged``);
- a named service with a contract change but no operation: ``candidate``, its
  operations are possible targets only;
- a named service without contract wording, or with the contract stated as
  unchanged: ``none``, nothing is claimed about its consumers.

A service label before a colon or a route-free summary can scope a route; a
service mentioned for another operation cannot disambiguate it. Documentation
clauses do not establish a change. The fixed grammar recognizes an explicit
"unchanged and change ..." contrast, not arbitrary coordination or negation.

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
    r"(не\s+(меня|изменя|измени)\w*|без\s+изменени\w*|остаётся|остается|прежн\w*|unchanged|not\s+chang\w*|"
    r"(does|do|will)\s*n[o']t\s+change|no\s+(api\s+|contract\s+)?changes?)", re.I)
SERVICE_WIDE = re.compile(
    r"(все[хм]?|всего|весь|кажд\w*|целиком|all|every|entire|whole)\s+(\w+\s+)?"
    r"(эндпоинт\w*|ручк\w*|маршрут\w*|операци\w*|метод\w*|api|endpoints?|operations?|routes?)", re.I)
CLAUSE_SPLIT = re.compile(
    r"[.;!?\n]+|,\s*(?:но|а|однако|but|while)\s+|\s+(?:но|однако|but)\s+|"
    r"(?<=unchanged)\s+and\s+(?=(?:change|remove|delete|rename|reduce|increase|update)\b)", re.I)
DOCUMENTATION = re.compile(r"\b(readme|docs?|documentation|document(?:ing)?|describe|описать|описани\w*|документац\w*)\b", re.I)
CHANGE_ACTION = re.compile(
    r"\b(chang\w*|remov\w*|delet\w*|renam\w*|reduc\w*|increas\w*|"
    r"измен\w*|поменя\w*|удал\w*|переимен\w*|уменьш\w*|увелич\w*)\b|(?:->|→)", re.I)


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


def _documentation_only(clause: str) -> bool:
    return bool(DOCUMENTATION.search(clause)) and not CHANGE_ACTION.search(clause)


def contract_wording(texts: list[str]) -> str:
    """``changed``, ``unchanged`` (only negated mentions) or ``absent``."""
    changed = unchanged = False
    for text in texts:
        for clause in CLAUSE_SPLIT.split(text):
            if not _has_contract_word(clause) or _documentation_only(clause):
                continue
            if UNCHANGED.search(clause):
                unchanged = True
            else:
                changed = True
    return "changed" if changed else "unchanged" if unchanged else "absent"


def _route_clauses(texts: list[str]):
    """Mask route punctuation before splitting, preserving each mention's local prose."""
    for text in texts:
        found = []

        def placeholder(m):
            found.append((m.group(1), _route(m.group(2))))
            return f" @@{len(found) - 1}@@ "

        # Literal marker-like prose must not index the private route table.
        masked = ROUTE_RE.sub(placeholder, text.replace("@@", " "))
        # A field label ("depot: ...") may scope that field. A service named
        # inside another operation's clause may not disambiguate this one.
        prefix = masked.partition(":")[0] if ":" in masked else ""
        for clause in CLAUSE_SPLIT.split(masked):
            yield clause, [found[int(i)] for i in re.findall(r"@@(\d+)@@", clause)], prefix


def _documentation_context(texts):
    return any(_documentation_only(text) for text in texts)


def _route_is_documentation(clause, docs):
    return _documentation_only(clause) or (docs and not CHANGE_ACTION.search(clause)
                                          and not UNCHANGED.search(clause))


def route_mentions(texts: list[str]) -> tuple[set[tuple[str, str]], set[tuple[str, str]]]:
    """Changed/unchanged route mentions; documentation is neither."""
    named, negated = set(), set()
    docs = _documentation_context(texts)
    for clause, routes, _ in _route_clauses(texts):
        if _route_is_documentation(clause, docs):
            continue
        (negated if UNCHANGED.search(clause) else named).update(routes)
    return named, negated - named


def changed_routes(texts: list[str]) -> set[tuple[str, str]]:
    """Routes the text names, except those named only in clauses that say they do not change."""
    return route_mentions(texts)[0]


def match_intent(operations: list[dict], texts: list[str]) -> Intent:
    """``operations`` are graph operations: id, service, method, path."""
    # A route path ("/orders") must not count as naming the service "orders".
    prose = [ROUTE_RE.sub(" ", t) for t in texts]
    services = named_services(prose, {o["service"] for o in operations})
    routes, unchanged = route_mentions(texts)
    docs = _documentation_context(texts)
    if routes:
        matched = {}
        names = {o["service"] for o in operations}
        # Only route-free fields can provide shared context (e.g. a Jira summary).
        context_services = named_services([t for t in texts if not ROUTE_RE.search(t)], names)
        context_services |= named_services([prefix for _, _, prefix in _route_clauses(texts)
                                            if "@@" not in prefix], names)
        for clause, mentions, prefix in _route_clauses(texts):
            if UNCHANGED.search(clause) or _route_is_documentation(clause, docs):
                continue
            local = named_services([clause], names) or named_services([prefix], names)
            if not local and len(context_services) == 1:
                local = context_services
            for route in mentions:
                candidates = [o for o in operations if (o["method"], _route(o["path"])) == route
                              and (not local or o["service"] in local)]
                if not local and len({o["service"] for o in candidates}) > 1:
                    return Intent([], "ambiguous_route", "none", sorted({o["service"] for o in candidates}))
                matched.update({o["id"]: o for o in candidates})
        return Intent(sorted(matched), "route" if matched else "route_not_in_graph",
                      "explicit" if matched else "none", sorted({o["service"] for o in matched.values()}))
    if docs and any(ROUTE_RE.search(t) for t in texts) and not unchanged:
        return Intent([], "documentation_only", "none", sorted(services))
    stated_unchanged = Intent([], "routes_stated_unchanged", "none", sorted(
        services or {o["service"] for o in operations if (o["method"], _route(o["path"])) in unchanged}))
    if not services:
        return stated_unchanged if unchanged else Intent([], "no_mention", "none")
    of_services = sorted(o["id"] for o in operations if o["service"] in services
                         and (o["method"], _route(o["path"])) not in unchanged)
    wording = contract_wording(prose)
    if unchanged and (wording != "changed" or not of_services):
        return stated_unchanged
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
