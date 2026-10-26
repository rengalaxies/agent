"""Jira before any diff: an AnalysisResult assembled from the batch 3 graph query.

``GraphQuery.impact()`` already returns contract-shaped affected services,
paths, relationships, evidence, unknowns and source freshness for the
caller's grants. This module only adds claims and checks and picks the
status, then validates the document with ``agent_graph.output_contracts``.

Claims: a code-backed call becomes a ``fact`` with the operation as its
``subject`` (contract 2.1), so a runtime edge without a route can never back
it; the possible effect of the task stays a ``hypothesis`` with
``jira_without_diff``. Owners come from ``query.owner()`` as they are:
UNKNOWN and CONFLICT are shown, never resolved by guessing.
"""

from __future__ import annotations

from datetime import datetime, timezone

from agent_graph import PROFILE
from agent_graph.output_contracts import SCHEMA_VERSION, parse_document

from .envelope import digest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _unknown(items, code, subject=None):
    item = {"code": code, "subject": subject}
    if item not in items:
        items.append(item)


def _model_use(investigation):
    """ModelUse and Costs of a constitution run; unknown token counts stay None, never zero."""
    if investigation is None:
        return None, {"model_calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "reserved_micro": None,
                      "currency": None}
    usage = [e.get("usage") or {} for e in investigation.get("events", [])]
    known = all(isinstance(u.get("prompt_tokens"), int) for u in usage)
    model = {"configuration_id": investigation["configuration_id"], "model": investigation["model"],
             "protocol": investigation["protocol"]}
    return model, {"model_calls": len(usage) + sum(d.get("layer") == "transport"
                                                   for d in investigation.get("diagnostics", [])),
                   "prompt_tokens": sum(u["prompt_tokens"] for u in usage) if known else None,
                   "completion_tokens": sum(u["completion_tokens"] for u in usage) if known else None,
                   "reserved_micro": investigation.get("budget", {}).get("reserved_micro"), "currency": None}


def jira_result(request, query, impacts: list[dict], *, context: dict, intent, code_version: str,
                constitution_version: str, started_at: str, seconds: float, investigation=None):
    """``impacts`` holds ``query.impact()`` for every operation of ``intent`` (``intent.Intent``).

    An ``explicit`` intent gives the preliminary answer; a ``candidate`` intent
    (a contract change of a named service, no operation named) shows the same
    consumers as candidates only, PARTIAL; an intent with confidence ``none``
    names no consumer at all. A model run (``investigation``) is recorded as
    model use and costs. Its hypotheses are not rendered here yet; they are
    flagged as unverified.
    """
    claims, checks, unknowns = [], [], [{"code": "jira_without_diff", "subject": None}]
    affected, paths, relationships, evidence = {}, [], {}, {}
    requirements = context["graph"].get("requirements", [])
    for impact in impacts:
        op = impact["target"]["entity"]
        route = f"{op['method']} {op['route']}"
        for item in impact["unknowns"]:
            _unknown(unknowns, item["code"], item["subject"])
        for record in impact["evidence"]:
            evidence.setdefault(record["id"], record)
        for rid, view in impact["relationships"].items():
            relationships.setdefault(rid, view["contract"])
        for path in impact["paths"]:
            if path not in paths:
                paths.append({"relationship_refs": path["relationship_refs"], "summary": path["summary"][:4000]})
        for entry in impact["affected"]:
            known = affected.setdefault(entry["service"]["service"], {
                "service": entry["service"], "owner": entry["owner"], "relationship_refs": []})
            known["relationship_refs"] = sorted(set(known["relationship_refs"]) | set(entry["relationship_refs"]))
        for path in impact["paths"]:
            if path["depth"] != 1:
                continue
            view = impact["relationships"][path["relationship_refs"][-1]]
            consumer = path["consumer"]
            code_refs = [b["id"] for b in view["bases"] if b["origin"] == "code"]
            runtime_refs = [b["id"] for b in view["bases"] if b["origin"] == "runtime"]
            # Graph operation ids use the core operation_id formula, so requirements match directly.
            rules = [r for r in requirements if r["consumer"] == consumer and r["operation_id"] == impact["target"]["id"]]
            facts = []
            if code_refs and not path["service_level"]:
                call = next((b for b in view["bases"] if b["origin"] == "code" and b.get("callsite")), None)
                where = f" at {call['repository']}:{call['path']}:{call['callsite']['line']}" if call else ""
                facts.append(_claim(claims, "fact", f"{consumer} calls {route} of {op['service']}{where}.",
                                    code_refs + runtime_refs, "LOW", [], subject=op,
                                    applicability=f"Graph {impact['graph_version']}; static profile {PROFILE}."))
            risk_unknowns = ["jira_without_diff"] + ([] if rules else ["requirement_unknown"])
            if path["service_level"]:
                risk_unknowns.append("runtime_route_not_recorded")
            if not rules:
                _unknown(unknowns, "requirement_unknown", consumer)
            risk = _claim(claims, "hypothesis",
                          f"The task may change {route} of {op['service']}, which {consumer} uses; "
                          "the actual effect is unknown until a diff exists.",
                          code_refs + runtime_refs, "HIGH", risk_unknowns,
                          applicability="Before any diff; graph query only.")
            text = (f"Before the change lands, check how {consumer} uses {route}"
                    + (f" against requirement {rules[0]['id']} ({rules[0]['predicate']})." if rules
                       else "; whether it needs the complete collection is not known."))
            checks.append({"consumer": {"kind": "service", "installation_id": request.installation_id,
                                        "environment": request.environment, "service": consumer},
                           "text": text, "claim_refs": [risk] + facts})
    snapshots = [{"repository": s["repository"], "mode": "GIT_COMMIT" if s.get("tree") else "WORKTREE",
                  "commit": s["commit"] if s.get("tree") else None, "tree": s.get("tree"), "role": "consumer"}
                 for s in context.get("snapshots", [])]
    sources = {(s["source_kind"], s["source_id"]): {k: s[k] for k in ("source_kind", "source_id", "freshness")}
               for impact in impacts for s in impact["sources"]}
    graph_version = impacts[0]["graph_version"] if impacts else request.graph_version
    model, costs = _model_use(investigation)
    if investigation and investigation.get("hypothesis_ids"):
        _unknown(unknowns, "model_hypothesis_unverified")
    named = ", ".join(intent.services)
    if not impacts and intent.reason == "contract_unchanged_stated":
        status, reason = "ABSTAINED", "out_of_scope"
        summary = (f"The task names {named} and states that its API does not change; no consumer impact is "
                   "claimed. The PR diff is analyzed when it exists.")
    elif not impacts and intent.reason == "service_only":
        status, reason = "ABSTAINED", "intent_unclear"
        summary = (f"The task names {named} but no change of its API or operations; no consumer impact is "
                   "claimed before a diff.")
    elif not impacts:
        status, reason = "ABSTAINED", "intent_unclear"
        summary = f"The task does not name an operation found in the graph ({intent.reason})."
    elif not affected:
        status, reason = "ABSTAINED", "no_consumer_found_within_profile"
        _unknown(unknowns, "runtime_not_observed")
        summary = "No consumer of the named operation was found in the graph. Absence is not proven."
    elif intent.confidence == "candidate":
        status, reason = "PARTIAL", "hypotheses_only"
        summary = (f"The task names a contract change of {named} without naming an operation; {len(affected)} "
                   f"service(s) use its {len(impacts)} operation(s) and are candidates only, not a "
                   "preliminary answer.")
    elif any(c["kind"] == "fact" for c in claims):
        status, reason = "USEFUL", "preliminary_impact_found"
        summary = (f"{len(affected)} service(s) use the operation named by the task. No diff yet: this is a "
                   "preliminary impact area, not a proven break.")
    else:
        status, reason = "PARTIAL", "coverage_gaps"
        summary = "Only runtime edges without a route link the named operation to consumers."
    document = {
        "schema": "agent-graph-output", "schema_version": SCHEMA_VERSION, "kind": "analysis_result",
        "profile": PROFILE, "code_version": code_version, "constitution_version": constitution_version,
        "installation_id": request.installation_id, "environment": request.environment,
        "request_id": request.request_id, "event_id": request.source_event.event_id,
        "resource_version": request.source_event.resource_version, "correlation_id": request.request_id,
        "trigger_kind": "jira", "snapshots": snapshots, "graph_version": graph_version,
        "status": status, "reason_code": reason, "summary": summary,
        "affected": [affected[k] for k in sorted(affected)] if status not in ("ABSTAINED",) else [],
        "impact_paths": paths if status not in ("ABSTAINED",) else [],
        "checks": checks if status not in ("ABSTAINED",) else [],
        "claims": claims if status not in ("ABSTAINED",) else [],
        "unknowns": unknowns, "source_freshness": [sources[k] for k in sorted(sources)],
        "evidence": list(evidence.values()) if status not in ("ABSTAINED",) else [],
        "relationships": list(relationships.values()) if status not in ("ABSTAINED",) else [],
        "model": model, "costs": costs,
        "timings": {"started_at": started_at, "finished_at": _now(), "seconds": {"analysis": seconds}},
    }
    return parse_document(document)


def _claim(claims, kind, statement, refs, uncertainty, unknowns, *, applicability, subject=None) -> str:
    cid = "claim:" + digest([kind, statement, sorted(set(refs))])[:40]
    if cid not in {c["id"] for c in claims}:
        claim = {"id": cid, "kind": kind, "statement": statement[:4000], "evidence_refs": sorted(set(refs)),
                 "applicability": applicability, "uncertainty": uncertainty, "unknowns": sorted(set(unknowns))}
        if subject is not None:
            claim["subject"] = subject
        claims.append(claim)
    return cid
