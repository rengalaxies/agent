"""Persistent graph of code, runtime and ownership bases with history.

Entities and relationships have stable identities scoped by installation and
environment. A relationship holds bases of separate origins. A sync opens,
transfers, reopens or closes bases; nothing is deleted, and every change is an
event with its version, reason and successor. Which bases a sync may close is
limited to the sources it actually read: an unavailable repository or runtime
source leaves its last bases in place (they turn stale on read), and a narrower
policy cannot retract what it no longer sees.

Reads, freshness and access filtering live in graph_query.
"""
from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path

from pydantic import Field

from .contracts import GraphError, Strict, canonical, digest, load_json
from .output_contracts import OperationEntity, ServiceEntity, TeamEntity, entity_id, normalize_route
from .store import Store, scope_id

UNAVAILABLE_GAPS = {"commit_unavailable", "source_unavailable", "directory_unreadable"}
OWNERSHIP_SOURCES = ("installation_mapping", "codeowners", "service_catalog")
# Fields that change on every read and are not part of a canonical fact.
VOLATILE = {"checked_at", "freshness"}


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def service_entity(installation, environment, service):
    return ServiceEntity(installation_id=installation, environment=environment, service=service).model_dump()


def operation_entity(installation, environment, service, method, route):
    return OperationEntity(installation_id=installation, environment=environment, service=service,
                           method=method.upper(), route=normalize_route(route)).model_dump()


def team_entity(installation, team):
    return TeamEntity(installation_id=installation, team=team).model_dump()


def callsite_id(installation, environment, consumer, repository, path, operation, symbol, ordinal):
    # No line number: an edit above the call keeps the identity (batch-3.md, "Стабильные ID").
    return digest([installation, environment, "callsite", consumer, repository, path, operation, symbol, ordinal])


def relationship_id(kind, source, target):
    return digest([kind, source, target])


def enclosing_symbols(text):
    """line -> qualified name of the innermost function or class, '<module>' at top level."""
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError, RecursionError):
        return lambda line: "<unparsed>"
    spans = []

    def visit(node, prefix):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                name = f"{prefix}.{child.name}" if prefix else child.name
                spans.append((child.lineno, child.end_lineno, name))
                visit(child, name)
            else:
                visit(child, prefix)
    visit(tree, "")

    def lookup(line):
        inner = [(start, name) for start, end, name in spans if start <= line <= end]
        return max(inner)[1] if inner else "<module>"
    return lookup


class OwnershipMapping(Strict):
    """One configured ownership origin. A list of teams for a service is a conflict."""
    source: str = Field(pattern=r"^(installation_mapping|codeowners|service_catalog)$")
    version: str = Field(min_length=1, max_length=200)
    services: dict[str, str | list[str]]


def load_ownership(path):
    """Read an ownership file; None (source unavailable) when it cannot be read."""
    try:
        return OwnershipMapping.model_validate(load_json(Path(path).read_text(encoding="utf-8")))
    except (OSError, UnicodeError, ValueError):
        return None


def code_bases(context):
    """Expected code bases of one context: (relationship, entities, basis) triples."""
    inst, env = context["installation_id"], context["environment"]
    sources = context["sources"]
    operations = {o["id"]: o for o in context["graph"]["operations"]}
    result = []

    def located(source, ev):
        return dict(profile=context.get("profile"), repository=source["repository"], path=source["path"], commit=source.get("commit"),
                    blob=source.get("blob"), sha256=source["sha256"],
                    snapshot=source.get("snapshot") or "WORKTREE",
                    start_line=ev["start_line"], end_line=ev["end_line"], fragment=digest(ev["quote"]))

    for op in operations.values():
        provider = service_entity(inst, env, op["service"])
        target = operation_entity(inst, env, op["service"], op["method"], op["path"])
        rel = relationship_id("declares", entity_id(provider), entity_id(target))
        for ev in op["evidence"]:
            source = sources[ev["source_id"]]
            data = dict(origin="code", kind="declares", locator=[source["repository"], source["path"]],
                        **located(source, ev))
            result.append((dict(id=rel, kind="declares", source=provider, target=target),
                           digest(["code", context.get("profile"), rel, data["locator"], data["fragment"]]), data))
    symbols, ordinals = {}, {}
    for dep in sorted(context["graph"]["dependencies"], key=lambda d: (d["repository"], d["path"], d["call_line"])):
        op = operations.get(dep["operation_id"])
        if op is None:
            continue
        ev = dep["evidence"][0]
        source = sources[ev["source_id"]]
        if source["id"] not in symbols:
            symbols[source["id"]] = enclosing_symbols(source["text"])
        symbol = symbols[source["id"]](dep["call_line"])
        target = operation_entity(inst, env, op["service"], op["method"], op["path"])
        key = (dep["repository"], dep["path"], entity_id(target), symbol)
        ordinals[key] = ordinals.get(key, -1) + 1
        site = callsite_id(inst, env, dep["consumer"], dep["repository"], dep["path"], entity_id(target),
                           symbol, ordinals[key])
        consumer = service_entity(inst, env, dep["consumer"])
        rel = relationship_id("calls", entity_id(consumer), entity_id(target))
        data = dict(origin="code", kind="calls", locator=[site], usage=dep["usage"],
                    callsite=dict(id=site, kind="callsite", installation_id=inst, environment=env,
                                  service=dep["consumer"], repository=dep["repository"], path=dep["path"],
                                  line=dep["call_line"], symbol=symbol, ordinal=ordinals[key]),
                    provider_repositories=sorted({sources[e["source_id"]]["repository"] for e in op["evidence"]}),
                    **located(source, ev))
        result.append((dict(id=rel, kind="calls", source=consumer, target=target),
                       digest(["code", context.get("profile"), rel, data["locator"], data["fragment"]]), data))
    return result


class GraphStore:
    """Graph tables in the same SQLite file as Store (schema 2)."""

    def __init__(self, store: Store):
        self.store, self.db = store, store.db

    # ---- writing -------------------------------------------------------------------

    def _version(self, scope, trigger, source_kind, source_id):
        cursor = self.db.execute("INSERT INTO graph_versions(scope,created_at,trigger,source_kind,source_id,summary)"
                                 " VALUES(?,?,?,?,?,?)", (scope, now_iso(), trigger, source_kind, source_id, "{}"))
        return cursor.lastrowid

    def _entity(self, scope, entity):
        key = entity["id"] if entity.get("kind") == "callsite" else entity_id(entity)
        self.db.execute("INSERT OR REPLACE INTO graph_entities VALUES(?,?,?,?)",
                        (key, scope, entity["kind"], canonical(entity)))
        return key

    def _event(self, scope, version, basis, relationship, event, reason=None, successor=None):
        self.db.execute("INSERT INTO graph_events VALUES(?,?,?,?,?,?,?,?)",
                        (scope, version, basis, relationship, event, reason, successor, now_iso()))

    def _source(self, scope, kind, id, status, version, reasons=()):
        checked = now_iso()
        old = self.db.execute("SELECT last_success_at FROM graph_sources WHERE scope=? AND source_kind=? AND source_id=?",
                              (scope, kind, id)).fetchone()
        last = checked if status in ("OK", "PARTIAL") else (old[0] if old else None)
        self.db.execute("INSERT OR REPLACE INTO graph_sources VALUES(?,?,?,?,?,?,?,?)",
                        (scope, kind, id, status, checked, last, version, canonical(sorted(reasons))))

    def _apply(self, scope, version, source_kind, expected, responsible, close_reason):
        """expected: [(relationship, basis_id, data, source_id, visibility)]."""
        summary = dict(opened=0, transferred=0, reopened=0, closed=0)
        checked = now_iso()
        wanted = {}
        for rel, basis, data, source_id, visibility in expected:
            source = self._entity(scope, rel["source"])
            target = self._entity(scope, rel["target"])
            if data.get("callsite"):
                self._entity(scope, data["callsite"])
            self.db.execute("INSERT OR IGNORE INTO graph_relationships VALUES(?,?,?,?,?)",
                            (rel["id"], scope, rel["kind"], source, target))
            wanted[basis] = (rel["id"], data, source_id, visibility)
        rows = {r[0]: r for r in self.db.execute(
            "SELECT id,relationship,data,closed_version,source_id FROM graph_bases WHERE scope=? AND source_kind=?",
            (scope, source_kind))}
        for basis, (rel, data, source_id, visibility) in wanted.items():
            row = rows.get(basis)
            if row is None:
                self.db.execute("INSERT INTO graph_bases VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (basis, scope, rel, data["origin"], source_kind, source_id, canonical(visibility),
                                 canonical(data), version, None, None, None, checked))
                self._event(scope, version, basis, rel, "opened")
                summary["opened"] += 1
                continue
            event = "reopened" if row[3] is not None else "transferred"
            if event == "transferred" and load_json(row[2]) == data:
                self.db.execute("UPDATE graph_bases SET checked_at=? WHERE id=?", (checked, basis))
                continue
            self.db.execute("UPDATE graph_bases SET data=?,visibility=?,closed_version=NULL,closed_reason=NULL,"
                            "successor=NULL,checked_at=? WHERE id=?", (canonical(data), canonical(visibility),
                                                                      checked, basis))
            self._event(scope, version, basis, rel, event)
            summary[event] += 1
        for basis, row in rows.items():
            if basis in wanted or row[3] is not None or not responsible(row):
                continue
            reason, successor = close_reason(row, wanted)
            self.db.execute("UPDATE graph_bases SET closed_version=?,closed_reason=?,successor=?,checked_at=?"
                            " WHERE id=?", (version, reason, successor, checked, basis))
            self._event(scope, version, basis, row[1], "closed", reason, successor)
            summary["closed"] += 1
        self.db.execute("UPDATE graph_versions SET summary=? WHERE version=?", (canonical(summary), version))
        return summary

    def sync_code(self, context, trigger="event"):
        """Apply one prepared context. Returns (version, summary)."""
        scope = scope_id(context["installation_id"], context["environment"])
        failed = {g["repository"] for g in context["graph"]["gaps"]
                  if g.get("code") in UNAVAILABLE_GAPS and g.get("repository")}
        snapshots = context.get("snapshots") or [
            dict(repository=r, mode="WORKTREE", commit=None) for r in sorted({s["repository"] for s in
                                                                              context["sources"].values()})]
        read = {s["repository"] for s in snapshots} - failed
        expected = [(rel, basis, data, data["repository"], [data["repository"]])
                    for rel, basis, data in code_bases(context)]
        declared = {rel["id"] for rel, _, _, _, _ in expected if rel["kind"] == "declares"}

        def responsible(row):
            data = load_json(row[2])
            return row[4] in read and set(data.get("provider_repositories", [])) <= read

        def close_reason(row, wanted):
            data = load_json(row[2])
            same_rel = [(b, d) for b, (rel, d, _, _) in wanted.items() if rel == row[1]]
            if data.get("profile") != context.get("profile"):
                return "code_changed", next((b for b, _ in same_rel), None)
            moved = next((b for b, d in same_rel if d["fragment"] == data["fragment"]), None)
            if moved:
                return "code_moved", moved
            changed = next((b for b, d in same_rel if d["locator"] == data["locator"]), None)
            if changed:
                return "code_changed", changed
            if data["kind"] == "calls":
                target = self.db.execute("SELECT target FROM graph_relationships WHERE id=?", (row[1],)).fetchone()[0]
                provider = load_json(self.db.execute("SELECT data FROM graph_entities WHERE id=?",
                                                     (target,)).fetchone()[0])["service"]
                inst, env = context["installation_id"], context["environment"]
                rel = relationship_id("declares", entity_id(service_entity(inst, env, provider)), target)
                if rel not in declared:
                    return "target_not_declared", None
            return "code_removed", None

        with self.store.transaction():
            version = self._version(scope, trigger, "code", ",".join(sorted(read | failed)))
            summary = self._apply(scope, version, "code", expected, responsible, close_reason)
            for snap in snapshots:
                repo = snap["repository"]
                self._source(scope, "code", repo, "UNAVAILABLE" if repo in failed else "OK",
                             snap.get("commit") or "worktree",
                             ["source_unavailable"] if repo in failed else
                             ["worktree_not_reproducible"] if snap.get("mode") == "WORKTREE" else [])
        return version, summary

    def sync_runtime(self, result, trigger="event"):
        """Apply one runtime_observations result. Runtime bases are never closed by a
        later window: they age. An unavailable source only changes the source state."""
        from .runtime_observations import evidence
        scope = scope_id(result["installation_id"], result["environment"])
        inst, env = result["installation_id"], result["environment"]
        source = result["source"]
        expected = []
        for o in result["observations"]:
            consumer = service_entity(inst, env, o["caller"]["service"])
            target = (operation_entity(inst, env, o["callee"]["service"], o["method"], o["route"]) if o["operation"]
                      else service_entity(inst, env, o["callee"]["service"]))
            rel = dict(id=relationship_id("calls", entity_id(consumer), entity_id(target)), kind="calls",
                       source=consumer, target=target)
            data = dict(origin="runtime", kind="calls", semantic_level=o["semantic_level"],
                        evidence={k: v for k, v in evidence(o).items() if k != "freshness"},
                        window=o["window"], aggregates=o["aggregates"],
                        window_reasons=[r for r in o["freshness"]["reasons"] if r != "age_exceeded"])
            expected.append((rel, o["id"], data, source["id"], [source["id"]]))
        status = {"AVAILABLE": "OK", "PARTIAL": "PARTIAL"}.get(source["status"], "UNAVAILABLE")
        with self.store.transaction():
            version = self._version(scope, trigger, "runtime", source["id"])
            summary = self._apply(scope, version, "runtime", expected, lambda row: False, None)
            self._source(scope, "runtime", source["id"], status, result["window"]["end"],
                         sorted({g["code"] for g in result["gaps"]} | set(source["reasons"])))
        return version, summary

    def sync_ownership(self, installation_id, environment, mapping: OwnershipMapping | None,
                       source="installation_mapping", trigger="event"):
        """One configured origin. None means the source could not be read: the last
        known owners stay, the source turns stale; nothing is guessed."""
        scope = scope_id(installation_id, environment)
        source = mapping.source if mapping else source
        expected = []
        for service, teams in sorted((mapping.services if mapping else {}).items()):
            for team in sorted({teams} if isinstance(teams, str) else set(teams)):
                owner = team_entity(installation_id, team)
                target = service_entity(installation_id, environment, service)
                rel = dict(id=relationship_id("owns", entity_id(owner), entity_id(target)), kind="owns",
                           source=owner, target=target)
                data = dict(origin="ownership", kind="owns", team=team, service=service, source=source,
                            source_version=mapping.version)
                expected.append((rel, digest(["owns", rel["id"], source]), data, source, [source]))
        with self.store.transaction():
            version = self._version(scope, trigger, "ownership", source)
            summary = self._apply(scope, version, "ownership", expected,
                                  (lambda row: row[4] == source) if mapping else (lambda row: False),
                                  lambda row, wanted: ("ownership_changed", None))
            self._source(scope, "ownership", source, "OK" if mapping else "UNAVAILABLE",
                         mapping.version if mapping else None, [] if mapping else ["source_unavailable"])
        return version, summary

    def import_contexts(self):
        """Migration: replay every stored context (oldest first) as code syncs, once.

        Old contexts and proposals stay where they are; this only builds graph
        bases from them, with change_origin "migration".
        """
        if self.db.execute("SELECT value FROM meta WHERE key='graph_imported'").fetchone():
            return []
        rows = [load_json(r[0]) for r in self.db.execute("SELECT data FROM artifacts WHERE kind='context'")]
        versions = []
        for context in sorted(rows, key=lambda c: (c.get("created_epoch", 0), c["id"])):
            try:
                versions.append(self.sync_code(context, trigger="migration")[0])
            except (KeyError, TypeError, ValueError, GraphError):
                continue  # an unreadable legacy context stays readable as an artifact
        with self.store.transaction():
            self.db.execute("INSERT OR REPLACE INTO meta VALUES('graph_imported', ?)", (canonical(versions),))
        return versions

    # ---- raw reads (filtering happens in graph_query) -------------------------------

    def latest_version(self, scope):
        row = self.db.execute("SELECT max(version) FROM graph_versions WHERE scope=?", (scope,)).fetchone()
        return row[0] or 0

    def version_info(self, version):
        row = self.db.execute("SELECT version,created_at,trigger,source_kind,source_id,summary FROM graph_versions"
                              " WHERE version=?", (version,)).fetchone()
        return None if row is None else dict(version=row[0], created_at=row[1], trigger=row[2],
                                             source_kind=row[3], source_id=row[4], summary=load_json(row[5]))

    def entities(self, scope):
        return {r[0]: load_json(r[1]) for r in self.db.execute(
            "SELECT id,data FROM graph_entities WHERE scope=?", (scope,))}

    def relationships(self, scope):
        return {r[0]: dict(id=r[0], kind=r[1], source=r[2], target=r[3]) for r in self.db.execute(
            "SELECT id,kind,source,target FROM graph_relationships WHERE scope=?", (scope,))}

    def bases(self, scope):
        return [dict(id=r[0], relationship=r[1], origin=r[2], source_kind=r[3], source_id=r[4],
                     visibility=load_json(r[5]), data=load_json(r[6]), opened_version=r[7], closed_version=r[8],
                     closed_reason=r[9], successor=r[10], checked_at=r[11])
                for r in self.db.execute("SELECT id,relationship,origin,source_kind,source_id,visibility,data,"
                                         "opened_version,closed_version,closed_reason,successor,checked_at"
                                         " FROM graph_bases WHERE scope=? ORDER BY id", (scope,))]

    def events(self, scope, basis=None):
        query = "SELECT version,basis,relationship,event,reason,successor,at FROM graph_events WHERE scope=?"
        args = [scope]
        if basis:
            query += " AND basis=?"
            args.append(basis)
        return [dict(version=r[0], basis=r[1], relationship=r[2], event=r[3], reason=r[4], successor=r[5], at=r[6])
                for r in self.db.execute(query + " ORDER BY rowid", args)]

    def sources(self, scope):
        return [dict(source_kind=r[0], source_id=r[1], status=r[2], checked_at=r[3], last_success_at=r[4],
                     source_version=r[5], reasons=load_json(r[6]))
                for r in self.db.execute("SELECT source_kind,source_id,status,checked_at,last_success_at,"
                                         "source_version,reasons FROM graph_sources WHERE scope=?"
                                         " ORDER BY source_kind,source_id", (scope,))]

    def canonical_facts(self, scope, origins=("code", "runtime", "ownership")):
        """Active facts without timestamps or versions: equal for a full and an incremental build."""
        rels = self.relationships(scope)
        facts = {}
        for b in self.bases(scope):
            if b["closed_version"] is not None or b["origin"] not in origins:
                continue
            r = rels[b["relationship"]]
            data = {k: v for k, v in b["data"].items() if k not in VOLATILE}
            facts.setdefault((r["id"], r["kind"], r["source"], r["target"]), []).append(canonical([b["id"], data]))
        return sorted([*key, sorted(values)] for key, values in facts.items())
