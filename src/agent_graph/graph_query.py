"""Bounded graph reads for the agent, the service and the viewer.

Every read is filtered by the caller's current grants (repository ids, runtime
source ids, ownership sources). A basis is visible only when all of its
visibility tokens are granted; relationships, entities, counters, history and
search results are derived from visible bases only, so a revoked source leaks
neither content nor existence. An old basis or relationship id gives nothing
beyond what the current grants allow. A GraphQuery object is a snapshot for one
grant set; it is the only cache and it is never shared between grant sets.

Freshness is computed on read, per source type. No traffic, sampling, a window
gap and an unavailable source are different reasons; none of them retracts a
code relationship.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import Field

from .contracts import GraphError, Strict
from .graph_store import GraphStore, service_entity
from .output_contracts import (
    CodeEvidence, Freshness, GraphRelationship, Owner, RuntimeEvidence, SourceFreshness, entity_id)
from .store import scope_id

MAX_LIMIT = 100
MAX_DEPTH = 3
CHANGE_ORIGIN = {"code": "code_scan", "runtime": "runtime_sync", "ownership": "ownership_sync"}
SOURCE_KIND = {"code": "git", "runtime": "runtime", "ownership": "ownership"}


class FreshnessConfig(Strict):
    """Per source type. Pinned Git commits do not age; a worktree does."""
    runtime_max_age_seconds: int = Field(default=86400, ge=1, le=90 * 86400)
    ownership_max_age_seconds: int = Field(default=7 * 86400, ge=1, le=365 * 86400)
    worktree_max_age_seconds: int = Field(default=3600, ge=1, le=86400)


def parse(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def iso(value):
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def bounded(limit, maximum=MAX_LIMIT):
    if type(limit) is not int or not 1 <= limit <= maximum:
        raise GraphError("invalid_query_limit")
    return limit


class GraphQuery:
    def __init__(self, graph_store: GraphStore, installation_id, environment, grants, *,
                 freshness: FreshnessConfig | None = None, now: datetime | None = None):
        self.gs = graph_store
        self.installation_id, self.environment = installation_id, environment
        self.scope = scope_id(installation_id, environment)
        self.grants = frozenset(grants)
        self.config = freshness or FreshnessConfig()
        self.now = now or datetime.now(timezone.utc)
        self.version = graph_store.latest_version(self.scope)
        entities = graph_store.entities(self.scope)
        relationships = graph_store.relationships(self.scope)
        self._bases = [b for b in graph_store.bases(self.scope) if set(b["visibility"]) <= self.grants]
        self._by_rel = {}
        for b in self._bases:
            self._by_rel.setdefault(b["relationship"], []).append(b)
        self._rels = {k: v for k, v in relationships.items() if k in self._by_rel}
        visible = {x for r in self._rels.values() for x in (r["source"], r["target"])}
        visible |= {b["data"]["callsite"]["id"] for b in self._bases if b["data"].get("callsite")}
        self._entities = {k: v for k, v in entities.items() if k in visible}
        self._sources = {(s["source_kind"], s["source_id"]): s for s in graph_store.sources(self.scope)
                         if s["source_id"] in self.grants}
        self._closing = {}
        for b in self._bases:
            if b["closed_version"] is not None and b["closed_version"] not in self._closing:
                self._closing[b["closed_version"]] = graph_store.version_info(b["closed_version"])
        self._openers = {}
        for b in self._bases:
            if b["opened_version"] not in self._openers:
                self._openers[b["opened_version"]] = graph_store.version_info(b["opened_version"])

    @classmethod
    def for_policy(cls, graph_store, policy, *, runtime_sources=(), ownership_sources=("installation_mapping",),
                   **kwargs):
        grants = {r.id for r in policy.repositories} | set(runtime_sources) | set(ownership_sources)
        return cls(graph_store, policy.installation_id, policy.environment, grants, **kwargs)

    # ---- freshness -----------------------------------------------------------------

    def basis_freshness(self, b):
        data = b["data"]
        state = self._sources.get((b["source_kind"], b["source_id"]))
        reasons, stale, extra = [], False, {}
        if b["closed_version"] is not None:
            return Freshness(status="STALE", checked_at=b["checked_at"], reasons=["basis_changed"]).model_dump()
        if state and state["status"] == "UNAVAILABLE":
            reasons.append("source_unavailable")
            stale = True
        if b["origin"] == "code" and data.get("snapshot") == "WORKTREE":
            reasons.append("worktree_not_reproducible")
            if (self.now - parse(b["checked_at"])).total_seconds() > self.config.worktree_max_age_seconds:
                reasons.append("age_exceeded")
                stale = True
        if b["origin"] == "runtime":
            end = parse(data["window"]["end"])
            if (self.now - end).total_seconds() > self.config.runtime_max_age_seconds:
                reasons.append("age_exceeded")
                stale = True
            reasons += data.get("window_reasons", [])
            extra = dict(valid_from=data["window"]["start"],
                         valid_until=iso(end + timedelta(seconds=self.config.runtime_max_age_seconds)))
        if b["origin"] == "ownership" and state and state["last_success_at"] and (
                self.now - parse(state["last_success_at"])).total_seconds() > self.config.ownership_max_age_seconds:
            reasons.append("age_exceeded")
            stale = True
        return Freshness(status="STALE" if stale else "CURRENT", checked_at=b["checked_at"],
                         reasons=sorted(set(reasons)), **extra).model_dump()

    def source_freshness(self):
        result = []
        for (kind, id), s in sorted(self._sources.items()):
            reasons = list(s["reasons"])
            status = "CURRENT"
            if s["status"] == "UNAVAILABLE":
                status = "STALE" if s["last_success_at"] else "UNKNOWN"
            elif s["status"] == "PARTIAL":
                reasons.append("partial_coverage")
            limit = dict(runtime=self.config.runtime_max_age_seconds,
                         ownership=self.config.ownership_max_age_seconds).get(kind)
            if limit and s["last_success_at"] and (self.now - parse(s["last_success_at"])).total_seconds() > limit:
                status, reasons = ("STALE" if status == "CURRENT" else status), reasons + ["age_exceeded"]
            known = {"basis_changed", "age_exceeded", "partial_coverage", "source_unavailable", "window_gap",
                     "sampled_source", "worktree_not_reproducible", "no_traffic_in_window"}
            mapped = sorted({"window_gap" if r in ("not_covered", "corrupt_records", "segment_digest_mismatch")
                             else r for r in reasons} & known)
            result.append(dict(SourceFreshness(source_kind=SOURCE_KIND[kind], source_id=id, freshness=Freshness(
                status=status, checked_at=s["checked_at"], reasons=mapped)).model_dump(),
                status=s["status"], source_version=s["source_version"], last_success_at=s["last_success_at"]))
        return result

    # ---- relationships -------------------------------------------------------------

    def _conflicts(self, rid, active):
        rel = self._rels[rid]
        target = self._entities.get(rel["target"])
        if rel["kind"] != "calls" or not target or target["kind"] != "operation":
            return []
        found = []
        has_code = any(b["origin"] == "code" for b in active)
        has_runtime = any(b["origin"] == "runtime" for b in active)
        if has_code and not has_runtime:
            others = [r for r in self._rels.values() if r["kind"] == "calls" and r["source"] == rel["source"]
                      and r["id"] != rid and self._entities.get(r["target"], {}).get("kind") == "operation"
                      and self._entities[r["target"]]["service"] == target["service"]
                      and any(b["origin"] == "runtime" and b["closed_version"] is None
                              for b in self._by_rel[r["id"]])]
            if others:
                found.append(dict(code="route_conflict", relationship_refs=sorted(r["id"] for r in others)))
        closed_code = [b for b in self._by_rel[rid] if b["origin"] == "code" and b["closed_version"] is not None]
        if has_runtime and not has_code and closed_code:
            closed_at = max(parse(self._closing[b["closed_version"]]["created_at"]) for b in closed_code)
            if any(b["origin"] == "runtime" and parse(b["data"]["window"]["end"]) > closed_at for b in active):
                found.append(dict(code="runtime_after_removal", relationship_refs=[rid]))
        return found

    def basis_view(self, b):
        data = b["data"]
        view = dict(id=b["id"], origin=b["origin"], status="CLOSED" if b["closed_version"] is not None else "ACTIVE",
                    opened_version=b["opened_version"], closed_version=b["closed_version"],
                    closed_reason=b["closed_reason"], successor=b["successor"],
                    freshness=self.basis_freshness(b))
        if b["origin"] == "code":
            view.update({k: data.get(k) for k in ("kind", "repository", "path", "commit", "snapshot", "start_line",
                                                  "end_line", "usage")})
            if data.get("callsite"):
                view["callsite"] = {k: data["callsite"][k] for k in ("id", "symbol", "ordinal", "line")}
        elif b["origin"] == "runtime":
            view.update(source=b["source_id"], window=data["window"], semantic_level=data["semantic_level"],
                        method=data["evidence"]["method"], route=data["evidence"]["route"],
                        aggregates=data["aggregates"])
        else:
            view.update(team=data["team"], source=data["source"], source_version=data["source_version"])
        return view

    def relationship(self, rid, *, history=True):
        if rid not in self._rels:
            raise GraphError("not_found")
        rel = self._rels[rid]
        bases = self._by_rel[rid]
        active = [b for b in bases if b["closed_version"] is None]
        fresh = [self.basis_freshness(b) for b in active]
        conflicts = self._conflicts(rid, active)
        if not active:
            status = "RETRACTED"
        elif conflicts:
            status = "CONFLICT"
        elif any(f["status"] == "CURRENT" for f in fresh):
            status = "ACTIVE"
        else:
            status = "STALE"
        shown = active or bases
        reasons = sorted({r for f in fresh for r in f["reasons"]}) if active else ["basis_changed"]
        freshness = Freshness(status="CURRENT" if status in ("ACTIVE", "CONFLICT") and any(
            f["status"] == "CURRENT" for f in fresh) else "STALE",
            checked_at=max(b["checked_at"] for b in shown), reasons=reasons).model_dump()
        latest = max(shown, key=lambda b: b["opened_version"])
        opener = self._openers.get(latest["opened_version"]) or {}
        view = dict(id=rid, kind=rel["kind"], status=status, freshness=freshness,
                    source=self._entities[rel["source"]], target=self._entities[rel["target"]],
                    source_id=rel["source"], target_id=rel["target"],
                    origins=sorted({b["origin"] for b in shown}), evidence_refs=[b["id"] for b in shown],
                    conflicts=conflicts, bases=[self.basis_view(b) for b in active],
                    history=[self.basis_view(b) for b in bases if b["closed_version"] is not None] if history else None,
                    visibility=sorted({v for b in shown for v in b["visibility"]}),
                    change_origin="migration" if opener.get("trigger") == "migration"
                    else CHANGE_ORIGIN[latest["origin"]])
        if rel["kind"] in ("calls", "declares"):
            view["contract"] = GraphRelationship(
                id=rid, kind=rel["kind"], source=view["source"], target=view["target"], status=status,
                origins=view["origins"], evidence_refs=view["evidence_refs"], freshness=freshness,
                change_origin=view["change_origin"], visibility=view["visibility"]).model_dump(mode="json")
        return view

    def evidence_records(self, rid):
        """agent-graph-output Evidence documents for the bases a relationship view cites."""
        view = self.relationship(rid, history=False)
        result = []
        for b in self._by_rel[rid]:
            if b["id"] not in view["evidence_refs"]:
                continue
            d, fresh = b["data"], self.basis_freshness(b)
            if b["origin"] == "code":
                pinned = d["snapshot"] == "GIT_COMMIT" and d["commit"] and d["blob"]
                result.append(CodeEvidence(
                    id=b["id"], provenance="AUTHENTIC",
                    sufficiency="SUPPORTED_WITHIN_PROFILE" if b["closed_version"] is None else "INSUFFICIENT",
                    freshness=Freshness(**fresh), visibility=b["visibility"],
                    snapshot="GIT_COMMIT" if pinned else "WORKTREE", repository=d["repository"],
                    commit=d["commit"] if pinned else None, blob=d["blob"] if pinned else None,
                    content_sha256=d["sha256"], path=d["path"], start_line=d["start_line"],
                    end_line=d["end_line"]).model_dump(mode="json"))
            elif b["origin"] == "runtime":
                result.append(RuntimeEvidence(**d["evidence"], freshness=Freshness(**fresh)).model_dump(mode="json"))
        return result

    # ---- ownership -----------------------------------------------------------------

    def owner(self, service):
        sid = entity_id(service_entity(self.installation_id, self.environment, service))
        bases = [b for r in self._rels.values() if r["kind"] == "owns" and r["target"] == sid
                 for b in self._by_rel[r["id"]] if b["closed_version"] is None]
        teams = sorted({b["data"]["team"] for b in bases})
        if not teams:
            return Owner(status="UNKNOWN", teams=[], source=None).model_dump(mode="json")
        source = sorted({b["data"]["source"] for b in bases})[0]
        state = self._sources.get(("ownership", source)) or {}
        return Owner(status="KNOWN" if len(teams) == 1 else "CONFLICT",
                     teams=[dict(kind="team", installation_id=self.installation_id, team=t) for t in teams],
                     source=source, source_version=bases[0]["data"]["source_version"],
                     checked_at=state.get("last_success_at")).model_dump(mode="json")

    def owner_history(self, service):
        sid = entity_id(service_entity(self.installation_id, self.environment, service))
        rows = [b for r in self._rels.values() if r["kind"] == "owns" and r["target"] == sid
                for b in self._by_rel[r["id"]]]
        return [dict(team=b["data"]["team"], source=b["data"]["source"], source_version=b["data"]["source_version"],
                     opened_version=b["opened_version"], closed_version=b["closed_version"],
                     closed_reason=b["closed_reason"])
                for b in sorted(rows, key=lambda b: (b["opened_version"], b["id"]))]

    # ---- bounded queries -----------------------------------------------------------

    def find(self, text, kind=None, limit=20):
        if not isinstance(text, str) or not 1 <= len(text) <= 200 or kind not in (None, "service", "operation"):
            raise GraphError("invalid_query")
        needle = text.strip().lower()
        hits = []
        for id, e in sorted(self._entities.items(), key=lambda kv: (kv[1]["kind"], kv[1].get("service", ""),
                                                                    kv[1].get("route", ""), kv[0])):
            if e["kind"] not in ("service", "operation") or (kind and e["kind"] != kind):
                continue
            label = e["service"] if e["kind"] == "service" else f'{e["service"]} {e["method"]} {e["route"]}'
            if needle in label.lower():
                hits.append(dict(id=id, entity=e, label=label))
        return hits[:bounded(limit)]

    def neighbors(self, entity, direction="both", limit=50):
        if entity not in self._entities or direction not in ("in", "out", "both"):
            raise GraphError("not_found" if entity not in self._entities else "invalid_query")
        rels = [r for r in self._rels.values()
                if (direction in ("out", "both") and r["source"] == entity)
                or (direction in ("in", "both") and r["target"] == entity)]
        return [self.relationship(r["id"], history=False) for r in sorted(rels, key=lambda r: r["id"])][:bounded(limit)]

    def operations_of(self, service):
        return sorted(id for id, e in self._entities.items() if e["kind"] == "operation" and e["service"] == service)

    def impact(self, entity, depth=2, limit=50):
        """Who may be affected by a change of an operation or a service, with paths,
        owners, freshness and unknowns. Shaped for AnalysisResult.affected/impact_paths."""
        if entity not in self._entities or self._entities[entity]["kind"] not in ("operation", "service"):
            raise GraphError("not_found")
        bounded(depth, MAX_DEPTH)
        limit = bounded(limit)
        root = self._entities[entity]
        paths, seen_rels, unknowns = [], {}, []

        def incoming(service, operations):
            sid = entity_id(service_entity(self.installation_id, self.environment, service))
            targets = set(operations) | {sid}
            views = []
            for r in sorted(self._rels.values(), key=lambda r: r["id"]):
                if r["kind"] == "calls" and r["target"] in targets:
                    view = seen_rels.get(r["id"]) or self.relationship(r["id"], history=False)
                    if view["status"] != "RETRACTED":
                        views.append(view)
            # A service-level runtime edge adds nothing for a consumer already linked to
            # an operation; it stays only where no route is known.
            precise = {v["source"]["service"] for v in views if v["target"]["kind"] == "operation"}
            for view in views:
                if view["target"]["kind"] == "service" and view["source"]["service"] in precise:
                    continue
                seen_rels[view["id"]] = view
                yield view

        def walk(service, operations, trail, visited, level):
            for view in incoming(service, operations):
                consumer = view["source"]["service"]
                if consumer in visited:
                    continue
                path = trail + [view["id"]]
                paths.append(dict(relationship_refs=path, depth=level, consumer=consumer,
                                  service_level=view["target"]["kind"] == "service", status=view["status"]))
                if level < depth:
                    walk(consumer, self.operations_of(consumer), path, visited | {consumer}, level + 1)

        operations = [entity] if root["kind"] == "operation" else self.operations_of(root["service"])
        walk(root["service"], operations, [], {root["service"]}, 1)
        paths = paths[:limit]
        for p in paths:
            labels = []
            for rid in reversed(p["relationship_refs"]):
                v = seen_rels[rid]
                t = v["target"]
                labels.append(f'{v["source"]["service"]} -> {t["service"]}'
                              + (f' {t["method"]} {t["route"]}' if t["kind"] == "operation" else " (service level)"))
            p["summary"] = "; ".join(labels)
            if p["service_level"]:
                unknowns.append(dict(code="runtime_route_not_recorded", subject=p["relationship_refs"][-1]))
        affected = {}
        for p in paths:
            entry = affected.setdefault(p["consumer"], dict(
                service=service_entity(self.installation_id, self.environment, p["consumer"]),
                owner=self.owner(p["consumer"]), relationship_refs=[]))
            for rid in p["relationship_refs"]:
                if rid not in entry["relationship_refs"]:
                    entry["relationship_refs"].append(rid)
        for name, entry in affected.items():
            status = entry["owner"]["status"]
            if status != "KNOWN":
                unknowns.append(dict(code="owner_unknown" if status == "UNKNOWN" else "owner_conflict", subject=name))
        used = sorted({rid for p in paths for rid in p["relationship_refs"]})
        return dict(graph_version=f"graph-{self.version}", target=dict(id=entity, entity=root), paths=paths,
                    affected=[affected[k] for k in sorted(affected)],
                    relationships={rid: seen_rels[rid] for rid in used},
                    evidence=[e for rid in used for e in self.evidence_records(rid)],
                    unknowns=unknowns, sources=self.source_freshness())

    def summary(self):
        """Counters over visible data only."""
        active = [b for b in self._bases if b["closed_version"] is None]
        return dict(graph_version=f"graph-{self.version}", relationships=len(self._rels),
                    active_bases=len(active), closed_bases=len(self._bases) - len(active),
                    by_origin={o: sum(b["origin"] == o for b in active) for o in ("code", "runtime", "ownership")},
                    services=sorted(e["service"] for e in self._entities.values() if e["kind"] == "service"))


class GraphQueryRequest(Strict):
    """The agent's graph tool call. Strict: no free-form query language."""
    tool: Literal["graph_find", "graph_neighbors", "graph_impact", "graph_relationship", "graph_owner"]
    text: str | None = Field(default=None, max_length=200)
    kind: Literal["service", "operation"] | None = None
    entity_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    relationship_id: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    service: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_.-]{1,64}$")
    direction: Literal["in", "out", "both"] = "both"
    depth: int = Field(default=2, ge=1, le=MAX_DEPTH)
    limit: int = Field(default=20, ge=1, le=MAX_LIMIT)


def dispatch(query: GraphQuery, request):
    """Run one validated tool call against a grant-scoped query."""
    r = GraphQueryRequest.model_validate(request) if isinstance(request, dict) else request
    required = dict(graph_find="text", graph_neighbors="entity_id", graph_impact="entity_id",
                    graph_relationship="relationship_id", graph_owner="service")[r.tool]
    if getattr(r, required) is None:
        raise GraphError("invalid_query")
    if r.tool == "graph_find":
        return query.find(r.text, r.kind, r.limit)
    if r.tool == "graph_neighbors":
        return query.neighbors(r.entity_id, r.direction, r.limit)
    if r.tool == "graph_impact":
        return query.impact(r.entity_id, r.depth, r.limit)
    if r.tool == "graph_relationship":
        return query.relationship(r.relationship_id)
    return dict(owner=query.owner(r.service), history=query.owner_history(r.service))
