"""Thin adapter between the service and ``agent_graph.output_contracts`` (agent-graph-output 2.x).

The contracts are owned by batch 2A. This module builds a validated
``AnalysisRequest``, validates the returned ``AnalysisResult`` with the same
module and turns it into a ``ResultView``, the only shape the publisher
renders. Anything that does not validate, or that belongs to another
request, becomes an explicit incompatibility, never a finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
from typing import Callable, Protocol

from agent_graph.output_contracts import (SCHEMA_ID, SCHEMA_VERSION, AnalysisResult, ContractError, dump_document,
                                          parse_document)

from .envelope import digest

IDENTIFIER_RE = re.compile(r"^[a-zA-Z0-9_.:/-]{1,200}$")
TEXT_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,39}$")


class AnalysisUnavailable(Exception):
    """Transient: the analysis could not run now (model/source down). Retried with backoff."""

    def __init__(self, reason_code: str = "analysis_unavailable"):
        self.reason_code = reason_code
        super().__init__(reason_code)


class Analyzer(Protocol):
    def analyze(self, request: dict, *, attachments: dict, cancelled: Callable[[], bool]) -> dict:
        """Return an AnalysisResult document. Must stop early when ``cancelled()``."""


class NotWiredAnalyzer:
    """Default until batch 4 wave 2 wires ``agent_graph``: every job ends as a visible technical failure."""

    def analyze(self, request: dict, *, attachments: dict, cancelled) -> dict:
        raise AnalysisUnavailable("analysis_not_wired")


def identifier(value: str) -> str:
    """Contract identifiers allow a narrow alphabet; other ids are replaced by a stable digest."""
    return value if IDENTIFIER_RE.match(value) else "id:" + digest(value)[:40]


def jira_timestamp(value: str) -> str:
    """Jira returns ``2026-10-24T10:00:00.000+0000``; the contract needs ``+00:00``."""
    return re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)


def build_request(*, installation_id: str, environment: str, request_id: str, trigger_kind: str,
                  event_id: str, resource_version: str, subject: dict, repository_revisions: dict,
                  settings: dict, deadline: str) -> dict:
    """Validated AnalysisRequest. Raises ``ContractError`` with safe diagnostics."""
    repositories = sorted(set(repository_revisions) | set(settings.get("repositories", [])))
    runtime_sources = sorted(settings.get("runtime_sources", []))
    request = {
        "schema": SCHEMA_ID, "schema_version": SCHEMA_VERSION, "kind": "analysis_request",
        "installation_id": installation_id, "environment": environment, "request_id": identifier(request_id),
        "trigger_kind": trigger_kind,
        "source_event": {"event_id": identifier(event_id), "resource_version": resource_version},
        "repository_revisions": dict(sorted(repository_revisions.items())),
        "graph_version": settings.get("graph_version", "graph-not-wired"),
        "constitution_version": settings.get("constitution_version", "agent-service-v1"),
        "model_configuration_id": settings.get("model_configuration_id"),
        "deadline": deadline,
        "access_scope": {"view_id": digest({"repositories": repositories, "runtime_sources": runtime_sources}),
                         "repositories": repositories, "runtime_sources": runtime_sources},
    }
    if trigger_kind == "jira":
        text_fields = {name: value if isinstance(value, str) else ", ".join(map(str, value))
                       for name, value in subject["fields"].items() if TEXT_FIELD_RE.match(name)}
        request["jira"] = {"project": subject["project"], "key": subject["key"], "revision": subject["revision"],
                           "updated_at": jira_timestamp(subject["updated_at"]),
                           "text_fields": dict(sorted(text_fields.items())[:8])}
    else:
        request["pr"] = {"provider": "github", "repository": subject["repository_id"], "pr_id": subject["pr_id"],
                         "base_sha": subject["base_sha"], "head_sha": subject["head_sha"]}
    return dump_document(parse_document(request))


@dataclass(frozen=True)
class ResultView:
    """What a comment may show."""

    status: str
    reason_code: str
    summary: str
    affected: list[dict] = field(default_factory=list)
    claims: list[dict] = field(default_factory=list)
    paths: list[dict] = field(default_factory=list)
    checks: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)
    freshness: list[dict] = field(default_factory=list)
    versions: dict = field(default_factory=dict)
    compatible: bool = True


def incompatible(code: str, versions: dict | None = None) -> ResultView:
    return ResultView("FAILED", code, "", versions=versions or {}, compatible=False)


def _evidence_label(e) -> dict:
    if e.origin == "code":
        where = e.commit[:12] if e.commit else "WORKTREE"
        ref = f"{e.repository}@{where}:{e.path}#L{e.start_line}-{e.end_line}"
    elif e.origin == "runtime":
        route = f" {e.method} {e.route}" if e.method and e.route else ""
        ref = f"{e.source}: {e.consumer.service} -> {e.provider.service}{route}, {e.window_start}..{e.window_end}"
    elif e.origin == "model_hypothesis":
        ref = f"{e.model_configuration_id}, не проверено"
    elif e.origin == "correction":
        ref = f"{e.correction_id} ({e.actor})"
    else:
        ref = f"{e.reporter}, не проверено независимо"
    notes = []
    if e.sufficiency not in ("SUPPORTED_WITHIN_PROFILE", "OBSERVED_WITHIN_WINDOW"):
        notes.append(e.sufficiency)
    if e.freshness.status != "CURRENT":
        notes.append(f"{e.freshness.status}: {', '.join(e.freshness.reasons)}".rstrip(": "))
    return {"origin": e.origin, "ref": ref, "uncertainty": "; ".join(notes) or None}


def view_from_result(document, request: dict) -> ResultView:
    try:
        result = parse_document(document)
    except ContractError as exc:
        version = document.get("schema_version") if isinstance(document, dict) else None
        return incompatible(exc.code, {"schema_version": str(version)[:20]} if version is not None else None)
    if not isinstance(result, AnalysisResult):
        return incompatible("not_a_result")
    source_event = request["source_event"]
    if (result.request_id, result.event_id, result.resource_version, result.installation_id,
            result.environment, result.trigger_kind) != (
            request["request_id"], source_event["event_id"], source_event["resource_version"],
            request["installation_id"], request["environment"], request["trigger_kind"]):
        # A valid result for another request/version must never be shown as this one's.
        return incompatible("result_request_mismatch")
    evidence = {e.id: e for e in result.evidence}
    relationships = {r.id: r for r in result.relationships}
    affected = []
    for item in result.affected:
        owner = item.owner
        teams = [t.team for t in owner.teams]
        source = f"{owner.source}@{owner.source_version}" if owner.source and owner.source_version else owner.source
        affected.append({"service": item.service.service, "owner_status": owner.status, "teams": teams,
                         "owner_source": source})
    claim_views = [{"kind": c.kind, "statement": c.statement, "applicability": c.applicability,
                    "uncertainty": c.uncertainty,
                    "evidence": [_evidence_label(evidence[r]) for r in c.evidence_refs]} for c in result.claims]
    paths = []
    for path in result.impact_paths:
        refs = []
        for rel_id in path.relationship_refs:
            rel = relationships[rel_id]
            refs.extend(_evidence_label(evidence[r]) for r in rel.evidence_refs)
        paths.append({"description": path.summary, "evidence": refs[:10]})
    checks = [f"{check.consumer.service}: {check.text}" for check in result.checks]
    unknowns = [f"{u.code}" + (f" ({u.subject})" if u.subject else "") for u in result.unknowns]
    unknowns += [f"пробел {g.code}" + (f" {g.repository}" if g.repository else "") + (f":{g.path}" if g.path else "")
                 for g in result.gaps[:20]]
    freshness = [{"source": f"{s.source_kind}:{s.source_id}", "status": s.freshness.status,
                  "checked_at": s.freshness.checked_at} for s in result.source_freshness]
    versions = {"schema_version": result.schema_version, "profile": result.profile,
                "code_version": result.code_version, "constitution_version": result.constitution_version,
                "graph_version": result.graph_version, "correlation_id": result.correlation_id,
                "snapshots": {f"{s.repository} ({s.role})": s.commit or "WORKTREE" for s in result.snapshots}}
    if result.model:
        versions["model"] = f"{result.model.configuration_id} {result.model.model}"
    return ResultView(status=result.status, reason_code=result.reason_code, summary=result.summary,
                      affected=affected, claims=claim_views, paths=paths, checks=checks, unknowns=unknowns,
                      freshness=freshness, versions=versions)
