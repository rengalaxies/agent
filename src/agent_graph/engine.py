"""Advisory operations. No code execution, release decisions or message delivery."""
from __future__ import annotations

from datetime import datetime, timezone
import time
import uuid

from . import PROFILE, SCHEMA
from .contracts import Citation, ExternalCheck, GraphError, Policy, Proposal, digest
from .discovery import extract
from .sources import collect
from .store import Store


def now():
    return datetime.now(timezone.utc).isoformat()


class Graph:
    def __init__(self, policy: Policy, store: Store):
        self.policy, self.store = policy, store
        self.view = policy.view_id()

    def prepare_context(self, task="", operation_id=None):
        self.policy.require("maintain")
        self.policy.require("read_context")
        if not isinstance(task, str) or len(task) > 2000:
            raise GraphError("invalid_task")
        generation, previous = self.store.head(self.view)
        started = time.monotonic()
        c = collect(self.policy)
        graph = extract(self.policy, c)
        checked = collect(self.policy)
        if checked["basis"] != c["basis"]:
            raise GraphError("sources_changed_during_scan")
        context = dict(schema=SCHEMA, profile=PROFILE, run_id=uuid.uuid4().hex,
                       installation_id=self.policy.installation_id, environment=self.policy.environment,
                       task=task, operation_id=operation_id, created_at=now(), created_epoch=time.time(),
                       basis=c["basis"], previous_context_id=previous, sources=c["sources"],
                       inventory=c["inventory"], graph=graph,
                       coverage="PARTIAL" if graph["gaps"] else "COMPLETE_WITHIN_PROFILE",
                       scope="authorized offline corpus; static grammar only; no global absence claim",
                       metrics=dict(bytes_read=c["bytes_read"] + checked["bytes_read"], scan_passes=2,
                                    prepare_seconds=time.monotonic() - started))
        return self.store.save(self.view, "context", context, generation)

    def context(self, id):
        self.policy.require("read_context")
        return self.store.get(self.view, id)

    def freshness(self, context):
        self.policy.require("read_context")
        expired = time.time() - context["created_epoch"] > self.policy.limits.freshness_seconds
        try:
            c = collect(self.policy)
        except GraphError:
            return dict(status="UNKNOWN", assessed_at=now(), comparison_basis="CURRENT_CORPUS",
                        reasons=["current_corpus_unavailable"])
        changed = c["basis"] != context["basis"]
        return dict(status="STALE" if changed or expired else "CURRENT", assessed_at=now(),
                    comparison_basis="CURRENT_CORPUS", reasons=(["basis_changed"] if changed else [])
                    + (["age_exceeded"] if expired else [])
                    + (["partial_coverage"] if context["coverage"] == "PARTIAL" else []))

    def _current(self, context):
        if self.freshness(context)["status"] != "CURRENT":
            raise GraphError("stale_context")
        if self.store.head(self.view)[1] != context["id"]:
            raise GraphError("superseded_context")

    def dependencies(self, context_id, operation_id=None):
        c = self.context(context_id)
        graph = c["graph"]
        result = dict(schema=SCHEMA, context_id=c["id"], basis=c["basis"], profile=PROFILE,
                      installation_id=c["installation_id"], environment=c["environment"],
                      coverage=c["coverage"], freshness=self.freshness(c),
                      operations=[o for o in graph["operations"] if operation_id is None or o["id"] == operation_id],
                      dependencies=[d for d in graph["dependencies"] if operation_id is None or d["operation_id"] == operation_id],
                      requirements=[r for r in graph["requirements"] if operation_id is None or r["operation_id"] == operation_id],
                      candidates=graph["candidates"], conflicts=graph["conflicts"], gaps=graph["gaps"],
                      proposals=self.proposals(c), scope=c["scope"])
        return result

    def get_evidence(self, context_id, citation):
        context = self.context(context_id)
        citation = Citation.model_validate(citation) if isinstance(citation, dict) else citation
        source = context["sources"].get(citation.source_id)
        if not source:
            raise GraphError("not_found")
        if (citation.end_line < citation.start_line
                or citation.end_line - citation.start_line + 1 > self.policy.limits.max_tool_lines):
            raise GraphError("evidence_range_limit")
        lines = source["text"].splitlines()
        if citation.end_line > len(lines):
            raise GraphError("invalid_evidence_range")
        quote = "\n".join(lines[citation.start_line - 1:citation.end_line])
        if quote != citation.quote:
            raise GraphError("evidence_mismatch")
        return dict(source_id=source["id"], repository=source["repository"], path=source["path"],
                    revision=source["revision"], sha256=source["sha256"], **citation.model_dump(exclude={"source_id"}))

    def propose(self, context_id, proposal, *, from_model=False):
        self.policy.require("propose")
        context = self.context(context_id)
        self._current(context)
        p = Proposal.model_validate(proposal) if isinstance(proposal, dict) else proposal
        if p.kind == "human_correction":
            self.policy.require("correct")
            if from_model:
                raise GraphError("model_cannot_correct")
        for citation in p.citations:
            self.get_evidence(context_id, citation)
        existing = self.store.proposals(self.view)
        old = next((x for x in existing if x["id"] == p.supersedes), None)
        if p.supersedes and (not old or old["proposal"]["key"] != p.key
                             or p.kind != "human_correction"):
            raise GraphError("invalid_supersession")
        record = dict(proposal=p.model_dump(), context_id=context_id, basis=context["basis"],
                      actor=self.policy.subject, origin="model" if from_model else "external",
                      trust="HUMAN_CORRECTION" if p.kind == "human_correction" else "UNAPPROVED_CANDIDATE")
        # Identical resubmission remains idempotent, including at the proposal cap.
        if len(existing) >= self.policy.limits.max_proposals and digest([self.view, record]) not in {x["id"] for x in existing}:
            raise GraphError("proposal_limit")
        return self.store.propose(self.view, record, context["id"])

    def proposals(self, context):
        rows = self.store.proposals(self.view)
        output = []
        superseded = {x["proposal"]["supersedes"] for x in rows if x["proposal"]["supersedes"]}
        for row in rows:
            fresh = row["basis"] == context["basis"]
            conflicting = [x["id"] for x in rows if x["id"] != row["id"]
                           and x["proposal"]["key"] == row["proposal"]["key"]
                           and x["proposal"]["statement"] != row["proposal"]["statement"]
                           and x["basis"] == row["basis"] and x["id"] not in superseded]
            output.append({**row, "status": "SUPERSEDED" if row["id"] in superseded else "CURRENT" if fresh else "STALE",
                           "conflicts_with": conflicting})
        return output

    def report_check(self, check):
        self.policy.require("report_check")
        check = ExternalCheck.model_validate(check) if isinstance(check, dict) else check
        context = self.context(check.context_id)
        self._current(context)
        for citation in check.citations:
            self.get_evidence(check.context_id, citation)
        return self.store.save(self.view, "external_check", dict(
            schema=SCHEMA, actor=self.policy.subject, report=check.model_dump(),
            status="EXTERNAL_REPORTED", independently_verified=False,
            requirement_approval=False, grants_execution=False))

    def analyze_change(self, base_context_id, task=""):
        self.policy.require("maintain")
        base = self.context(base_context_id)
        current = self.prepare_context(task or base["task"], base.get("operation_id"))
        old_ops = {o["id"]: o for o in base["graph"]["operations"]}
        new_ops = {o["id"]: o for o in current["graph"]["operations"]}
        findings, deltas = [], []
        for id, old in old_ops.items():
            new = new_ops.get(id)
            if base.get("operation_id") and id != base["operation_id"]:
                continue
            code = None
            if new is None:
                provider_repos = {base["sources"][e["source_id"]]["repository"] for e in old["evidence"]}
                uncertain = any(g.get("repository") in provider_repos
                                or g.get("source_id") in {s["id"] for s in current["sources"].values()
                                                         if s["repository"] in provider_repos}
                                for g in current["graph"]["gaps"])
                if uncertain:
                    continue  # missing/unparseable provider is not a proven removal
                code = "OPERATION_REMOVED"
            elif (not old.get("default_conflict") and not new.get("default_conflict")
                    and old["default_known"] and new["default_known"]
                    and old.get("page_size_default") != new.get("page_size_default")):
                code = "PAGE_DEFAULT_CHANGED"
            if code is None:
                continue
            delta = dict(operation_id=id, code=code, before=old.get("page_size_default"),
                         after=new.get("page_size_default") if new else None,
                         evidence=old["evidence"] + (new["evidence"] if new else []))
            deltas.append(delta)
            # Current scan can discover a NEW consumer in a formerly irrelevant file.
            # Old callsites stay in the old immutable result, not as live risks
            # after a repair/move. For a removed operation retain historical uses.
            dep_context = base if code == "OPERATION_REMOVED" else current
            deps = {d["id"]: d for d in dep_context["graph"]["dependencies"] if d["operation_id"] == id}
            live_ids = {d["id"] for d in current["graph"]["dependencies"]}
            for dep in deps.values():
                live = dep["id"] in live_ids
                after = delta["after"]
                limited = type(after) is int and after > 0 and (delta["before"] is None
                          or type(delta["before"]) is int and after < delta["before"])
                risk = code == "OPERATION_REMOVED" or (limited and dep["usage"] == "SINGLE_REQUEST_OBSERVED")
                rules = [r for r in current["graph"]["requirements"]
                         if r["operation_id"] == id and r["consumer"] == dep["consumer"]]
                findings.append(dict(
                    code="POSSIBLE_TRUNCATION" if risk and code != "OPERATION_REMOVED" else code if risk else "RECHECK_REQUIRED",
                    dependency_id=dep["id"], consumer=dep["consumer"], usage=dep["usage"],
                    callsite=dict(repository=dep["repository"], path=dep["path"], line=dep["call_line"]),
                    dependency_freshness="CURRENT" if live else "STALE",
                    condition=(f"If helper obeys page_size, result set exceeds {after}, and consumer needs complete data"
                               if limited else "If the changed declaration governs this call"),
                    evidence_stage="STATIC", evidence=delta["evidence"] + dep["evidence"] + dep["usage_evidence"],
                    requirement_ids=[r["id"] for r in rules],
                    check=(f"Run consumer with more than {after} records; compare full expected set, page traversal and explicit limits"
                           if limited else "Exercise the changed operation against this consumer's independent expectations"),
                    test_executed=False, compatibility_confirmed=False))
        result = dict(schema=SCHEMA, run_id=uuid.uuid4().hex, created_at=now(),
                      base_context_id=base_context_id, context_requested_id=base_context_id,
                      context_used_id=current["id"], base_basis=base["basis"], head_basis=current["basis"],
                      deltas=deltas, findings=findings, coverage=current["coverage"],
                      gaps=current["graph"]["gaps"], conflicts=current["graph"]["conflicts"],
                      freshness=self.freshness(current), release_decision=None,
                      unknowns=[] if deltas else ["no_supported_behavior_delta; arbitrary semantic changes are not classified"],
                      drafts=[dict(consumer=f["consumer"], text=f["check"], sent=False) for f in findings])
        return self.store.save(self.view, "analysis", result)
