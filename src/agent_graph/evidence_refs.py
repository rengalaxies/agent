"""Opt-in reference protocol. Handles are receipts for reads, never capabilities.

Sessions are trusted, process-local objects. They cannot be resumed by presenting an
ID. The private Store/Policy remain the security boundary (not OS multi-tenancy).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
import hashlib
from typing import Literal
import uuid

from pydantic import Field

from .contracts import Citation, GraphError, Strict, digest


class DependencyClaim(Strict):
    consumer_repository: str = Field(min_length=1, max_length=64)
    consumer_service: str = Field(min_length=1, max_length=64)
    provider_service: str = Field(min_length=1, max_length=64)
    method: Literal["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"]
    path_template: str = Field(min_length=1, max_length=500)


class ReferenceProposal(Strict):
    # No free-form assertion/key can contradict the typed claim being assessed.
    claim: DependencyClaim
    evidence_refs: list[str] = Field(min_length=1, max_length=8)


class ReferenceReply(Strict):
    action: Literal["read_source", "propose", "finish"]
    source_id: str | None
    start_line: int | None
    end_line: int | None
    proposals: list[ReferenceProposal] = Field(max_length=8)


@dataclass(frozen=True)
class _Read:
    session: str
    scope: str
    subject: str
    context_id: str
    basis: str
    source_id: str
    repository: str
    path: str
    revision: str
    sha256: str
    start_line: int
    end_line: int
    quote_digest: str


def _covers(citations, source_id, start, end):
    # A union of individually authorized ranges is sufficient; no gaps permitted.
    covered = set()
    for c in citations:
        if c.source_id == source_id:
            covered.update(range(c.start_line, c.end_line + 1))
    return all(line in covered for line in range(start, end + 1))


def dependency_sufficiency(context, claim, citations):
    """Separate bounded static assessment, not a proof of runtime behavior.

    No extraction means UNKNOWN/insufficient, never a global absence assertion.
    Must cover BOTH a resolved callsite and its provider declaration in the same
    snapshot, including route decorators (or the complete OpenAPI document).
    """
    operations = {o["id"]: o for o in context["graph"]["operations"]}
    for dep in context["graph"]["dependencies"]:
        op = operations[dep["operation_id"]]
        if (dep["repository"], dep["consumer"], op["service"], op["method"], op["path"]) != (
            claim.consumer_repository, claim.consumer_service, claim.provider_service,
            claim.method, claim.path_template
        ):
            continue
        if not all(_covers(citations, e["source_id"], e["start_line"], e["end_line"])
                   for e in dep["evidence"]):
            continue
        for e in op["evidence"]:
            source = context["sources"][e["source_id"]]
            first, last = e["start_line"], e["end_line"]
            if source["path"].endswith(".json"):
                first, last = 1, len(source["text"].splitlines())
            else:
                tree = ast.parse(source["text"])
                fn = next((n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           and n.lineno == first), None)
                if fn is None:
                    continue
                first = min([first] + [d.lineno for d in fn.decorator_list])
            if _covers(citations, e["source_id"], first, last):
                return dict(status="SUPPORTED_WITHIN_PROFILE", dependency_id=dep["id"],
                            profile=context["profile"], runtime_verified=False, scope="STATIC_PROFILE_ONLY")
    return dict(status="INSUFFICIENT", reason="no_covered_directed_dependency_with_service_identity",
                profile=context["profile"], runtime_verified=False, scope="STATIC_PROFILE_ONLY",
                dependency_absence="NOT_ESTABLISHED")


class EvidenceSession:
    def __init__(self, graph, context_id):
        self._graph = graph
        self._context_id = context_id
        self._scope = graph.policy.view_id()
        self._subject = graph.policy.subject
        self._id = uuid.uuid4().hex
        self._reads: dict[str, _Read] = {}
        context = self._current()
        self._basis = context["basis"]

    @property
    def id(self):
        return self._id

    def _current(self):
        graph = self._graph
        graph.policy.require("read_context")
        if (graph.policy.view_id() != self._scope or graph.view != self._scope
                or graph.policy.subject != self._subject):
            raise GraphError("evidence_scope_changed")
        context = graph.context(self._context_id)
        graph._current(context)
        if hasattr(self, "_basis") and context["basis"] != self._basis:
            raise GraphError("evidence_snapshot_changed")
        return context

    def _citation(self, context, source_id, first, last):
        source = context["sources"].get(source_id)
        if source is None:
            raise GraphError("not_found")
        lines = source["text"].splitlines()
        if (type(first) is not int or type(last) is not int or first < 1
                or last < first or last > len(lines)):
            raise GraphError("invalid_evidence_range")
        if last - first + 1 > self._graph.policy.limits.max_tool_lines:
            raise GraphError("evidence_range_limit")
        if hashlib.sha256(source["text"].encode()).hexdigest() != source["sha256"]:
            raise GraphError("evidence_snapshot_changed")
        quote = "\n".join(lines[first - 1:last])
        if not quote or len(quote) > 6000:
            raise GraphError("evidence_range_limit")
        citation = Citation(source_id=source_id, start_line=first, end_line=last, quote=quote)
        # Reuse the original exact-text validator; never normalize model quotes.
        self._graph.get_evidence(self._context_id, citation)
        return citation

    def read(self, source_id, start_line, end_line):
        context = self._current()
        c = self._citation(context, source_id, start_line, end_line)
        source = context["sources"][source_id]
        reference = uuid.uuid4().hex
        self._reads[reference] = _Read(
            self._id, self._scope, self._subject, self._context_id, self._basis,
            source_id, source["repository"], source["path"], source["revision"], source["sha256"],
            start_line, end_line, digest(c.quote))
        return dict(evidence_ref=reference, session_id=self._id, context_id=self._context_id,
                    basis=self._basis, **self._graph.get_evidence(self._context_id, c))

    def resolve(self, reference):
        context = self._current()  # Knowing an ID does not bypass current authority.
        receipt = self._reads.get(reference) if isinstance(reference, str) else None
        if receipt is None:
            raise GraphError("invalid_evidence_reference")
        c = self._citation(context, receipt.source_id, receipt.start_line, receipt.end_line)
        source = context["sources"][c.source_id]
        expected = _Read(self._id, self._scope, self._subject, self._context_id, self._basis,
                         c.source_id, source["repository"], source["path"], source["revision"],
                         source["sha256"], c.start_line, c.end_line, digest(c.quote))
        if receipt != expected:
            raise GraphError("invalid_evidence_reference")
        return c

    def assess(self, proposal):
        """Return distinct provenance and sufficiency outcomes, without admission."""
        p = ReferenceProposal.model_validate(proposal)
        try:
            citations = [self.resolve(ref) for ref in p.evidence_refs]
        except GraphError as exc:
            return dict(provenance=dict(status="REJECTED", reason=exc.code),
                        sufficiency=dict(status="NOT_ASSESSED"))
        return dict(provenance=dict(status="AUTHENTIC_AUTHORIZED_CURRENT"),
                    sufficiency=dependency_sufficiency(self._current(), p.claim, citations))

    def propose(self, proposal, *, admission_check=None):
        self._graph.policy.require("propose")
        p = ReferenceProposal.model_validate(proposal)
        assessment = self.assess(p)
        if assessment["provenance"]["status"] == "REJECTED":
            raise GraphError(assessment["provenance"]["reason"])
        if assessment["sufficiency"]["status"] != "SUPPORTED_WITHIN_PROFILE":
            raise GraphError("insufficient_dependency_evidence")
        claim = p.claim
        # Only trusted code constructs the accepted statement, key and exact quotes.
        legacy = dict(key="dependency:" + digest(claim.model_dump()), kind="hypothesis",
                      statement=f"{claim.consumer_service} ({claim.consumer_repository}) -> "
                                f"{claim.provider_service} {claim.method} {claim.path_template}",
                      citations=[self.resolve(ref).model_dump() for ref in p.evidence_refs], supersedes=None)
        record = self._graph.propose(self._context_id, legacy, from_model=True, admission_check=admission_check)
        return dict(candidate=record, assessment=assessment)
