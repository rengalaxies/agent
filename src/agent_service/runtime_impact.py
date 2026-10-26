"""PR results: consumers of a changed operation that only runtime sources show.

``agent_graph.results.change_result`` reads the static diff: a finding needs a
call site in a consumer repository. A consumer whose calls only an access log
records (its address lives in deployment configuration, say) is invisible
there, although the persistent graph of batch 3 knows the edge. This module
adds those edges of every changed operation to the PR result.

What is added, and what is not:

- the graph relationship and its runtime evidence as they are: scope, origin,
  window, freshness (STALE stays STALE) and visibility come from the
  grant-scoped ``GraphQuery``, so a revoked or foreign source adds nothing;
- one ``hypothesis`` per consumer, never a ``fact`` or a ``finding``: traffic
  in a window says the consumer called the operation, not how it reads the
  response. A removed operation with current traffic is MEDIUM (those calls
  fail); everything else is HIGH with the usage unknowns named;
- an edge that also has a code basis is left to the static analysis.

A PR whose only consumers are runtime ones becomes PARTIAL (``hypotheses_only``,
or ``source_stale`` when every such edge is stale) instead of ABSTAINED.
"""

from __future__ import annotations

from agent_graph import PROFILE
from agent_graph.output_contracts import dump_document, normalize_route, parse_document

from .envelope import digest

PAGE_CODES = ("PAGE_DEFAULT_CHANGED", "PAGE_DEFAULT_UNRESOLVED")


def _effect(delta, consumer) -> tuple[str, list[str]]:
    code = delta["code"]
    if code == "OPERATION_REMOVED":
        return "the PR removes this operation, so such calls would fail.", []
    if code == "PAGE_DEFAULT_CHANGED":
        return (f"the PR changes its default page size {delta['before']} -> {delta['after']}; whether {consumer} "
                "reads one page or follows the cursor is unknown.", ["result_set_size_unknown"])
    if code == "PAGE_DEFAULT_UNRESOLVED":
        return "the PR changes its default page size to a value the profile cannot resolve.", [
            "result_set_size_unknown"]
    return "the PR changes this operation in a way no classifier covers.", ["unclassified_change"]


def _claim(document, statement, refs, uncertainty, unknowns, applicability):
    cid = "claim:" + digest(["hypothesis", statement, sorted(set(refs))])[:40]
    if cid not in {c["id"] for c in document["claims"]}:
        document["claims"].append(dict(id=cid, kind="hypothesis", statement=statement[:4000],
                                       evidence_refs=sorted(set(refs))[:32], applicability=applicability,
                                       uncertainty=uncertainty, unknowns=sorted(set(unknowns))))
    return cid


def _unknown(document, code, subject=None):
    item = dict(code=code, subject=subject)
    if item not in document["unknowns"]:
        document["unknowns"].append(item)


def graph_operation_ids(query) -> dict[tuple[str, str, str], str]:
    """(service, method, normalized route) -> graph operation id, within the query's grants."""
    from .core_analyzer import GraphOperations

    return {(o["service"], o["method"], normalize_route(o["path"])): o["id"]
            for o in GraphOperations(query).operations()}


def add_runtime_candidates(document: dict, query) -> dict:
    """``document``: a dumped PR AnalysisResult from ``change_result``. Returns it validated."""
    if document["status"] in ("FAILED", "SUPERSEDED") or not document.get("deltas"):
        return document
    ops = graph_operation_ids(query)
    static = {f["consumer"]["service"] for f in document["findings"]}
    evidence_ids = {e["id"] for e in document["evidence"]}
    relationship_ids = {r["id"] for r in document["relationships"]}
    affected = {a["service"]["service"]: a for a in document["affected"]}
    added, sources = {}, {}
    for delta in document["deltas"]:
        target = delta["operation"]
        op_id = ops.get((target["service"], target["method"], target["route"]))
        if op_id is None:
            continue  # an operation the PR adds, or one this grant cannot see
        impact = query.impact(op_id, depth=1, limit=50)
        owners = {a["service"]["service"]: a["owner"] for a in impact["affected"]}
        records = {e["id"]: e for e in impact["evidence"]}
        route = f"{target['method']} {target['route']}"
        for path in impact["paths"]:
            consumer = path["consumer"]
            view = impact["relationships"][path["relationship_refs"][-1]]
            if consumer in static or consumer == target["service"] or any(
                    b["origin"] != "runtime" for b in view["bases"]):
                continue
            contract = view["contract"]
            if contract["id"] not in relationship_ids:
                document["relationships"].append(contract)
                relationship_ids.add(contract["id"])
            runtime_refs = [r for r in contract["evidence_refs"] if r in records]
            for ref in runtime_refs:
                if ref not in evidence_ids:
                    document["evidence"].append(records[ref])
                    evidence_ids.add(ref)
            fresh = contract["freshness"]["status"] == "CURRENT"
            effect, effect_unknowns = _effect(delta, consumer)
            where = "route not recorded" if path["service_level"] else route
            names = ", ".join(sorted({records[r]["source"] for r in runtime_refs})) or "runtime"
            statement = (f"{consumer} called {target['service']} ({where}) according to runtime source {names}"
                         f"{'' if fresh else ', in a window older than the freshness limit'}; {effect} "
                         f"No call site of {consumer} is visible, so this is not a static finding.")
            unknowns = ["helper_semantics_unknown", "requirement_unknown", *effect_unknowns]
            if path["service_level"]:
                unknowns.append("runtime_route_not_recorded")
                _unknown(document, "runtime_route_not_recorded", contract["id"])
            removed_now = delta["code"] == "OPERATION_REMOVED" and fresh and not path["service_level"]
            claim = _claim(document, statement, runtime_refs + delta["evidence_refs"],
                           "MEDIUM" if removed_now else "HIGH", unknowns,
                           f"Graph {impact['graph_version']}; runtime window as recorded; static profile {PROFILE}.")
            document["checks"].append(dict(
                consumer=dict(kind="service", installation_id=document["installation_id"],
                              environment=document["environment"], service=consumer),
                text=(f"Find how {consumer} calls {route}: only runtime calls show it"
                      f"{'' if fresh else ' and they are stale'}; ask its owner or locate its call site."),
                claim_refs=[claim]))
            entry = affected.setdefault(consumer, dict(service=dict(
                kind="service", installation_id=document["installation_id"], environment=document["environment"],
                service=consumer), owner=owners[consumer], relationship_refs=[]))
            if contract["id"] not in entry["relationship_refs"]:
                entry["relationship_refs"].append(contract["id"])
            document["impact_paths"].append(dict(relationship_refs=[contract["id"]], summary=path["summary"][:4000]))
            _unknown(document, "requirement_unknown", consumer)
            owner = owners[consumer]["status"]
            if owner != "KNOWN":
                _unknown(document, "owner_unknown" if owner == "UNKNOWN" else "owner_conflict", consumer)
            added[consumer] = added.get(consumer, False) or fresh
        for s in impact["sources"]:
            if s["source_kind"] == "runtime":
                sources[(s["source_kind"], s["source_id"])] = {k: s[k] for k in ("source_kind", "source_id",
                                                                                  "freshness")}
    if not added:
        return document
    document["affected"] = [affected[k] for k in sorted(affected)]
    known = {(s["source_kind"], s["source_id"]) for s in document["source_freshness"]}
    document["source_freshness"] += [v for k, v in sorted(sources.items()) if k not in known]
    count = len(added)
    if document["status"] == "ABSTAINED" and document["reason_code"] == "no_consumer_found_within_profile":
        document["unknowns"] = [u for u in document["unknowns"] if u["code"] != "runtime_not_observed"]
        document["status"] = "PARTIAL"
        document["reason_code"] = "hypotheses_only" if any(added.values()) else "source_stale"
        document["summary"] = (f"The operation changed. No consumer was found in code, but {count} service(s) "
                               "call it according to runtime sources; these are hypotheses, no call site is visible.")
    else:
        document["summary"] = (document["summary"] + f" {count} more service(s) call a changed operation according "
                               "to runtime sources only; these are hypotheses.")[:4000]
    return dump_document(parse_document(document))
