"""Build agent-graph-output 2.0 AnalysisResult documents from core outputs.

Every result is validated by output_contracts before it is returned, so core
output that the contract cannot express (an unknown code, a fact without
sufficient evidence, a dangling reference) fails here instead of reaching the
application. Static dependencies become `fact` claims; risks, Jira-before-diff
impact and model candidates stay `hypothesis` claims with explicit unknowns.
"""
from __future__ import annotations

from datetime import datetime, timezone

from . import PROFILE
from .contracts import digest
from .output_contracts import (SCHEMA_VERSION, AnalysisRequest, AnalysisResult, normalize_route,
                               parse_document)

RISKS = {"POSSIBLE_TRUNCATION", "OPERATION_REMOVED"}


def _now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class _Builder:
    def __init__(self, graph, request: AnalysisRequest, contexts, *, ownership=None):
        self.graph, self.request = graph, request
        self.sources = {}
        for context in contexts:
            self.sources.update(context["sources"])
        self.contexts = contexts
        self.ownership = ownership or {}
        self.evidence, self.relationships, self.claims = {}, {}, []
        self.checked_at = _now()

    def service(self, name):
        return dict(kind="service", installation_id=self.request.installation_id,
                    environment=self.request.environment, service=name)

    def operation(self, op):
        return dict(kind="operation", installation_id=self.request.installation_id,
                    environment=self.request.environment, service=op["service"], method=op["method"],
                    route=normalize_route(op["path"]))

    def owner(self, service):
        teams = self.ownership.get("services", {}).get(service)
        teams = [teams] if isinstance(teams, str) else list(teams or [])
        if not teams:
            return dict(status="UNKNOWN", teams=[], source=None)
        return dict(status="KNOWN" if len(teams) == 1 else "CONFLICT", source=self.ownership["source"],
                    source_version=self.ownership.get("version"), checked_at=self.checked_at,
                    teams=[dict(kind="team", installation_id=self.request.installation_id, team=t) for t in teams])

    def cite(self, citation):
        """Re-validate the exact quote, then describe it as pinned code evidence."""
        source = self.sources[citation["source_id"]]
        context = next(c for c in self.contexts if citation["source_id"] in c["sources"])
        self.graph._evidence(context, citation)
        id = "ev:" + digest([citation["source_id"], citation["start_line"], citation["end_line"]])[:40]
        pinned = source.get("snapshot") == "GIT_COMMIT"
        self.evidence[id] = dict(
            id=id, origin="code", provenance="AUTHENTIC", sufficiency="SUPPORTED_WITHIN_PROFILE",
            freshness=dict(status="CURRENT", checked_at=self.checked_at,
                           reasons=[] if pinned else ["worktree_not_reproducible"]),
            visibility=[source["repository"]], snapshot="GIT_COMMIT" if pinned else "WORKTREE",
            repository=source["repository"], commit=source.get("commit") if pinned else None,
            blob=source.get("blob") if pinned else None, content_sha256=source["sha256"], path=source["path"],
            start_line=citation["start_line"], end_line=citation["end_line"])
        return id

    def calls(self, consumer, repository, op, refs, current=True):
        id = "rel:" + digest(["calls", consumer, op["id"]])[:40]
        provider_repos = sorted({self.sources[s]["repository"] for s in
                                 {e["source_id"] for e in op["evidence"]} if s in self.sources})
        self.relationships[id] = dict(
            id=id, kind="calls", source=self.service(consumer), target=self.operation(op),
            status="ACTIVE" if current else "STALE", origins=["code"], evidence_refs=sorted(set(refs)),
            freshness=dict(status="CURRENT" if current else "STALE", checked_at=self.checked_at),
            change_origin="code_scan", visibility=sorted({repository, *provider_repos}))
        return id

    def claim(self, kind, statement, refs, *, uncertainty, unknowns=(), applicability=None):
        id = "claim:" + digest([kind, statement, sorted(refs)])[:40]
        if id not in {c["id"] for c in self.claims}:
            self.claims.append(dict(
                id=id, kind=kind, statement=statement[:4000], evidence_refs=sorted(set(refs)),
                applicability=applicability or f"Pinned snapshots only; static profile {PROFILE}.",
                uncertainty=uncertainty, unknowns=sorted(set(unknowns))))
        return id

    def gaps(self, gaps):
        result = []
        for gap in gaps:
            source = self.sources.get(gap.get("source_id") or gap.get("evidence", {}).get("source_id"), {})
            item = dict(code=gap["code"], repository=gap.get("repository") or source.get("repository"),
                        path=gap.get("path") or source.get("path"))
            if item not in result:
                result.append(item)
        return result[:512]

    def snapshots(self, base=None, head=None):
        result, pr = [], self.request.pr
        for role, snaps in (("base", base or []), ("head", head or [])):
            for snap in snaps:
                if role == "base" and (pr is None or snap["repository"] != pr.repository):
                    continue
                kind = role if pr is not None and snap["repository"] == pr.repository else "consumer"
                pinned = snap["mode"] == "GIT_COMMIT" and snap.get("tree") is not None
                result.append(dict(repository=snap["repository"], mode="GIT_COMMIT" if pinned else "WORKTREE",
                                   commit=snap["commit"] if pinned else None, tree=snap["tree"] if pinned else None,
                                   role=kind))
        return result

    def source_freshness(self, snaps, gaps):
        unavailable = {g.get("repository") for g in gaps if g["code"] == "commit_unavailable"}
        return [dict(source_kind="git", source_id=s["repository"], freshness=dict(
            status="UNKNOWN" if s["repository"] in unavailable else "CURRENT", checked_at=self.checked_at,
            reasons=["source_unavailable"] if s["repository"] in unavailable else
            ([] if s["mode"] == "GIT_COMMIT" else ["worktree_not_reproducible"])))
            for s in snaps]

    def affected(self):
        by_consumer = {}
        for rel in self.relationships.values():
            by_consumer.setdefault(rel["source"]["service"], []).append(rel["id"])
        return [dict(service=self.service(name), owner=self.owner(name), relationship_refs=sorted(refs))
                for name, refs in sorted(by_consumer.items())]

    def finish(self, *, status, reason, summary, deltas=(), findings=(), gaps=(), unknowns=(), checks=(),
               snapshots=(), freshness=(), timings, correlation_id, code_version, constitution_version,
               investigation=None, superseded_by=None):
        unknown_items = []
        for code, subject in unknowns:
            item = dict(code=code, subject=subject)
            if item not in unknown_items:
                unknown_items.append(item)
        model, costs = None, dict(model_calls=0, prompt_tokens=0, completion_tokens=0, reserved_micro=None,
                                  currency=None)
        if investigation is not None:
            model = dict(configuration_id=investigation["configuration_id"], model=investigation["model"],
                         protocol=investigation["protocol"])
            usage = [e.get("usage") or {} for e in investigation.get("events", [])]
            known = all(isinstance(u.get("prompt_tokens"), int) for u in usage)
            costs = dict(model_calls=len(investigation.get("events", [])) + len(
                [d for d in investigation.get("diagnostics", []) if d.get("layer") == "transport"]),
                prompt_tokens=sum(u["prompt_tokens"] for u in usage) if known else None,
                completion_tokens=sum(u["completion_tokens"] for u in usage) if known else None,
                reserved_micro=investigation.get("budget", {}).get("reserved_micro"), currency=None)
        document = dict(
            schema="agent-graph-output", schema_version=SCHEMA_VERSION, kind="analysis_result", profile=PROFILE,
            code_version=code_version, constitution_version=constitution_version,
            installation_id=self.request.installation_id, environment=self.request.environment,
            request_id=self.request.request_id, event_id=self.request.source_event.event_id,
            resource_version=self.request.source_event.resource_version, correlation_id=correlation_id,
            trigger_kind=self.request.trigger_kind, snapshots=list(snapshots), graph_version=self.request.graph_version,
            status=status, reason_code=reason, superseded_by=superseded_by, summary=summary,
            affected=self.affected() if status not in ("FAILED", "SUPERSEDED") else [],
            impact_paths=[dict(relationship_refs=[r["id"]], summary=(
                f"{r['source']['service']} -> {r['target']['service']} {r['target']['method']} {r['target']['route']}"))
                for r in self.relationships.values()] if status not in ("FAILED", "SUPERSEDED") else [],
            checks=list(checks), claims=self.claims if status not in ("FAILED", "SUPERSEDED") else [],
            deltas=list(deltas), findings=list(findings), gaps=list(gaps), unknowns=unknown_items,
            source_freshness=list(freshness), evidence=list(self.evidence.values()),
            relationships=list(self.relationships.values()), model=model, costs=costs, timings=timings)
        return parse_document(document)


def _timings(started_at, finished_at, seconds):
    return dict(started_at=started_at or _now(), finished_at=finished_at or _now(), seconds=dict(seconds or {}))


def _investigation_claims(b, graph, investigation, unknowns):
    if investigation is None:
        return
    records = {r["id"]: r for r in graph.store.proposals(graph.view)}
    for candidate in investigation.get("hypothesis_ids", []):
        record = records.get(candidate)
        if record is None:
            continue
        refs = [b.cite(c) for c in record["proposal"]["citations"]]
        id = "hyp:" + candidate[:40]
        b.evidence[id] = dict(
            id=id, origin="model_hypothesis", provenance="AUTHENTIC", sufficiency="NOT_ASSESSED",
            freshness=dict(status="CURRENT", checked_at=b.checked_at), visibility=sorted(
                {b.evidence[r]["repository"] for r in refs}), model_configuration_id=investigation["configuration_id"],
            supporting_refs=refs, unknowns=["model_hypothesis_unverified"])
        b.claim("hypothesis", record["proposal"]["statement"], [id], uncertainty="HIGH",
                unknowns=["model_hypothesis_unverified"], applicability="Model candidate; never promoted automatically.")
        unknowns.append(("model_hypothesis_unverified", None))


def change_result(graph, request: AnalysisRequest, analysis: dict, *, code_version, constitution_version,
                  correlation_id, ownership=None, investigation=None, started_at=None, finished_at=None,
                  seconds=None) -> AnalysisResult:
    """PR (or replay) result from Graph.analyze_change output."""
    base = graph.context(analysis["base_context_id"])
    head = graph.context(analysis["context_used_id"])
    b = _Builder(graph, request, [head, base], ownership=ownership)
    ops = {o["id"]: o for o in base["graph"]["operations"]}
    ops.update({o["id"]: o for o in head["graph"]["operations"]})
    deps = {d["id"]: d for d in base["graph"]["dependencies"]}
    deps.update({d["id"]: d for d in head["graph"]["dependencies"]})
    snaps = b.snapshots(analysis.get("base_snapshots"), analysis.get("head_snapshots"))
    gaps = b.gaps(analysis["gaps"])
    common = dict(snapshots=snaps, freshness=b.source_freshness(analysis.get("head_snapshots", []), analysis["gaps"]),
                  timings=_timings(started_at, finished_at, seconds), correlation_id=correlation_id,
                  code_version=code_version, constitution_version=constitution_version, investigation=investigation)
    if request.pr is not None and any(g["code"] == "commit_unavailable" and g.get("repository") == request.pr.repository
                                      for g in analysis["gaps"] + base["graph"]["gaps"]):
        return b.finish(status="FAILED", reason="commit_unavailable", gaps=gaps,
                        summary="The PR base or head commit is not available from an allowed ref; nothing was analyzed.",
                        **common)
    deltas, findings, checks, unknowns = [], [], [], []
    for delta in analysis["deltas"]:
        op = ops[delta["operation_id"]]
        refs = [b.cite(e) for e in delta["evidence"]]
        deltas.append(dict(operation=b.operation(op), code=delta["code"], before=delta["before"],
                           after=delta["after"], evidence_refs=sorted(set(refs))))
        if delta["code"] == "UNCLASSIFIED_OPERATION_CHANGE":
            unknowns += [("unclassified_change", None), ("helper_semantics_unknown", None)]
    for finding in analysis["findings"]:
        dep = deps[finding["dependency_id"]]
        op = ops[dep["operation_id"]]
        call_refs = [b.cite(e) for e in dep["evidence"]]
        provider_refs = [b.cite(e) for e in op["evidence"]]
        usage_refs = [b.cite(e) for e in dep["usage_evidence"]]
        current = finding["dependency_freshness"] == "CURRENT"
        b.calls(dep["consumer"], dep["repository"], op, call_refs + provider_refs, current)
        route = f"{op['method']} {normalize_route(op['path'])}"
        fact = b.claim("fact", f"{dep['consumer']} calls {route} of {op['service']} at "
                               f"{dep['path']}:{dep['call_line']}; observed usage {dep['usage']}.",
                       call_refs + provider_refs + usage_refs, uncertainty="LOW")
        risk_unknowns = ["helper_semantics_unknown"]
        if not finding["requirement_ids"]:
            risk_unknowns.append("requirement_unknown")
            unknowns.append(("requirement_unknown", dep["consumer"]))
        if finding["code"] == "POSSIBLE_TRUNCATION":
            risk_unknowns.append("result_set_size_unknown")
        if finding["code"] == "UNCLASSIFIED_CHANGE_RECHECK":
            risk_unknowns.append("unclassified_change")
        risk = b.claim("hypothesis", f"{finding['code']}: {finding['condition']}.",
                       [r for d in deltas if d["operation"]["route"] == normalize_route(op["path"])
                        and d["operation"]["service"] == op["service"] for r in d["evidence_refs"]] + call_refs,
                       uncertainty="MEDIUM" if finding["code"] in RISKS else "HIGH", unknowns=risk_unknowns)
        checks.append(dict(consumer=b.service(dep["consumer"]), text=finding["check"], claim_refs=[risk, fact]))
        findings.append(dict(
            code=finding["code"], consumer=b.service(dep["consumer"]), usage=finding["usage"],
            callsite=dict(kind="callsite", installation_id=request.installation_id, environment=request.environment,
                          service=dep["consumer"], repository=dep["repository"], path=dep["path"], line=dep["call_line"]),
            dependency_freshness=finding["dependency_freshness"], evidence_refs=sorted(set(call_refs)),
            requirement_ids=finding["requirement_ids"]))
        if not b.owner(dep["consumer"])["teams"]:
            unknowns.append(("owner_unknown", dep["consumer"]))
    _investigation_claims(b, graph, investigation, unknowns)
    classified = [f for f in findings if f["code"] != "UNCLASSIFIED_CHANGE_RECHECK"]
    if findings and classified:
        status, reason = "USEFUL", "impact_found_within_profile"
        summary = (f"{len({f['consumer']['service'] for f in findings})} consumer(s) of the changed operation(s); "
                   f"{sum(f['code'] in RISKS for f in findings)} with a classified risk. Static profile; tests not executed.")
    elif findings:
        status, reason = "PARTIAL", "unclassified_change"
        summary = "A tracked operation changed in a way no classifier covers; its consumers need a recheck."
    elif deltas:
        status, reason = "ABSTAINED", "no_consumer_found_within_profile"
        unknowns.append(("runtime_not_observed", None))
        summary = "The operation changed, but no consumer was found within the static profile. Absence is not proven."
    elif gaps:
        status, reason = "PARTIAL", "coverage_gaps"
        summary = "No supported change was found, but coverage has gaps."
    else:
        status, reason = "ABSTAINED", "no_supported_delta"
        summary = "No supported behavior change was found; arbitrary semantic changes are not classified."
    return b.finish(status=status, reason=reason, summary=summary, deltas=deltas, findings=findings, gaps=gaps,
                    unknowns=unknowns, checks=checks, **common)


def preliminary_result(graph, request: AnalysisRequest, context: dict, operation_ids, *, code_version,
                       constitution_version, correlation_id, ownership=None, investigation=None, started_at=None,
                       finished_at=None, seconds=None) -> AnalysisResult:
    """Jira before any diff: who may be affected through the graph, never a proven break."""
    b = _Builder(graph, request, [context], ownership=ownership)
    ops = {o["id"]: o for o in context["graph"]["operations"]}
    snaps = b.snapshots(None, context.get("snapshots", []))
    common = dict(snapshots=snaps, freshness=b.source_freshness(context.get("snapshots", []), context["graph"]["gaps"]),
                  timings=_timings(started_at, finished_at, seconds), correlation_id=correlation_id,
                  code_version=code_version, constitution_version=constitution_version, investigation=investigation)
    gaps = b.gaps(context["graph"]["gaps"])
    unknowns, checks = [("jira_without_diff", None)], []
    targets = [ops[i] for i in operation_ids if i in ops]
    if not targets:
        return b.finish(status="ABSTAINED", reason="intent_unclear", gaps=gaps, unknowns=unknowns,
                        summary="The task does not name an operation found in the graph.", **common)
    for op in targets:
        provider_refs = [b.cite(e) for e in op["evidence"]]
        for dep in [d for d in context["graph"]["dependencies"] if d["operation_id"] == op["id"]]:
            call_refs = [b.cite(e) for e in dep["evidence"]]
            usage_refs = [b.cite(e) for e in dep["usage_evidence"]]
            b.calls(dep["consumer"], dep["repository"], op, call_refs + provider_refs)
            route = f"{op['method']} {normalize_route(op['path'])}"
            fact = b.claim("fact", f"{dep['consumer']} calls {route} of {op['service']} at "
                                   f"{dep['path']}:{dep['call_line']}; observed usage {dep['usage']}.",
                           call_refs + provider_refs + usage_refs, uncertainty="LOW")
            rules = [r for r in context["graph"]["requirements"]
                     if r["operation_id"] == op["id"] and r["consumer"] == dep["consumer"]]
            risk_unknowns = ["jira_without_diff"] + ([] if rules else ["requirement_unknown"])
            if not rules:
                unknowns.append(("requirement_unknown", dep["consumer"]))
            risk = b.claim("hypothesis", f"The task may change {route} of {op['service']}, which {dep['consumer']} "
                                         "uses; the actual effect is unknown until a diff exists.",
                           call_refs + provider_refs, uncertainty="HIGH", unknowns=risk_unknowns)
            checks.append(dict(consumer=b.service(dep["consumer"]), claim_refs=[risk, fact], text=(
                f"Before the change lands, check how {dep['consumer']} uses {route} at {dep['path']}:{dep['call_line']}"
                + (f" against requirement {rules[0]['id']} ({rules[0]['predicate']})." if rules
                   else "; whether it needs the complete collection is not known."))))
            if not b.owner(dep["consumer"])["teams"]:
                unknowns.append(("owner_unknown", dep["consumer"]))
    _investigation_claims(b, graph, investigation, unknowns)
    if not b.relationships:
        return b.finish(status="ABSTAINED", reason="no_consumer_found_within_profile", gaps=gaps,
                        unknowns=unknowns + [("runtime_not_observed", None)],
                        summary="No consumer of the named operation was found within the static profile.", **common)
    return b.finish(status="USEFUL", reason="preliminary_impact_found", gaps=gaps, unknowns=unknowns, checks=checks,
                    summary=f"{len(b.affected())} service(s) use the operation named by the task. No diff yet: "
                            "this is a preliminary impact area, not a proven break.", **common)


def failed_result(request: AnalysisRequest, reason, *, code_version, constitution_version, correlation_id,
                  started_at=None, finished_at=None, seconds=None, superseded_by=None) -> AnalysisResult:
    status = "SUPERSEDED" if superseded_by else "FAILED"
    b = _Builder(None, request, [])
    return b.finish(status=status, reason=reason, superseded_by=superseded_by,
                    summary="Superseded by a newer version of the resource." if superseded_by
                    else "The analysis did not complete.", timings=_timings(started_at, finished_at, seconds),
                    correlation_id=correlation_id, code_version=code_version,
                    constitution_version=constitution_version)
