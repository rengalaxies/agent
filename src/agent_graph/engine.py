"""Advisory operations. No code execution, release decisions or message delivery."""
from __future__ import annotations

from datetime import datetime, timezone
import time
import uuid

from . import PROFILE, SCHEMA
from .contracts import Citation, ExternalCheck, GraphError, Policy, Proposal, digest
from .discovery import extract
from .sources import collect, pinned_freshness, pinned_only
from .store import Store, cited_bases, scope_id


MAX_EVIDENCE_BATCH = 5000


def now():
    return datetime.now(timezone.utc).isoformat()


def content_keys(context):
    return {(s["repository"], s["path"]): s["sha256"] for s in context["sources"].values()}


def config_digest(policy, repositories):
    """Configuration a proposal's sufficiency depends on: the extraction profile, service address map and the
    approved requirements stored in the repositories it cites. Other repositories and
    their requirements are excluded, so adding a repository keeps knowledge."""
    return digest([PROFILE, policy.addresses_dump(),
                   [r.model_dump() for r in policy.requirements if r.repository in repositories]])


def holds(row, keys, policy, view):
    """A proposal holds in a context while every cited file has the same content there and
    the address map and requirements are those it was made under. A v1 row has no stored
    configuration; its own view, which includes both, must then match."""
    bases = row.get("cited_bases") or []
    config = config_digest(policy, {b["repository"] for b in bases})
    same_config = (row["cited_config"] == config if row.get("cited_config")
                   else row.get("cited_view") == view and row.get("cited_profile") == PROFILE)
    return bool(bases) and same_config and all(
        keys.get((b["repository"], b["path"])) == b["sha256"] for b in bases)


class Graph:
    def __init__(self, policy: Policy, store: Store):
        self.policy, self.store = policy, store
        self.view = policy.view_id()
        # Knowledge is shared by installation/environment and filtered by read grants,
        # so a wider or narrower view neither loses nor leaks it.
        self.scope = scope_id(policy.installation_id, policy.environment)
        self.grants = {r.id for r in policy.repositories}

    def prepare_context(self, task="", operation_id=None, revisions=None):
        """revisions: commit per git repository; worktree repositories stay unpinned."""
        self.policy.require("maintain")
        self.policy.require("read_context")
        if not isinstance(task, str) or len(task) > 2000:
            raise GraphError("invalid_task")
        generation, previous = self.store.head(self.view)
        started = time.monotonic()
        c = collect(self.policy, revisions)
        graph = extract(self.policy, c)
        # Pinned objects cannot change under the scan; a worktree can.
        checked = c if pinned_only(self.policy) else collect(self.policy, revisions)
        if checked["basis"] != c["basis"]:
            raise GraphError("sources_changed_during_scan")
        context = dict(schema=SCHEMA, profile=PROFILE, run_id=uuid.uuid4().hex,
                       installation_id=self.policy.installation_id, environment=self.policy.environment,
                       task=task, operation_id=operation_id, created_at=now(), created_epoch=time.time(),
                       basis=c["basis"], previous_context_id=previous, sources=c["sources"],
                       inventory=c["inventory"], graph=graph, snapshots=c["snapshots"],
                       revisions=c["revisions"],
                       coverage="PARTIAL" if graph["gaps"] else "COMPLETE_WITHIN_PROFILE",
                       scope="authorized offline corpus; static grammar only; no global absence claim",
                       metrics=dict(bytes_read=c["bytes_read"] + (0 if checked is c else checked["bytes_read"]),
                                    scan_passes=1 if checked is c else 2,
                                    prepare_seconds=time.monotonic() - started))
        return self.store.save(self.view, "context", context, generation)

    def context(self, id):
        self.policy.require("read_context")
        return self.store.get(self.view, id)

    def freshness(self, context):
        self.policy.require("read_context")
        if context.get("profile") != PROFILE:
            return dict(status="STALE", assessed_at=now(), comparison_basis="EXTRACTOR_PROFILE",
                        reasons=["extractor_profile_changed"])
        if pinned_only(self.policy) and context.get("snapshots"):
            return pinned_freshness(self.policy, context)
        expired = time.time() - context["created_epoch"] > self.policy.limits.freshness_seconds
        try:
            c = collect(self.policy, context.get("revisions"))
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
        assessment = self.freshness(c)
        result = dict(schema=SCHEMA, context_id=c["id"], basis=c["basis"], profile=PROFILE,
                      installation_id=c["installation_id"], environment=c["environment"],
                      coverage=c["coverage"], freshness=assessment,
                      operations=[o for o in graph["operations"] if operation_id is None or o["id"] == operation_id],
                      dependencies=[d for d in graph["dependencies"] if operation_id is None or d["operation_id"] == operation_id],
                      requirements=[r for r in graph["requirements"] if operation_id is None or r["operation_id"] == operation_id],
                      candidates=graph["candidates"], conflicts=graph["conflicts"], gaps=graph["gaps"],
                      file_coverage=graph.get("file_coverage", []),
                      proposals=self.proposals(c, assessment=assessment), scope=c["scope"])
        return result

    def get_evidence(self, context_id, citation):
        return self._evidence(self.context(context_id), citation)

    def evidence_batch(self, items):
        """Validate many citations in one call; each item tries its contexts in order.

        Replaces one CLI process per citation. A context is loaded once per batch.
        Only not_found moves on to the next context; any other error is that item's result.
        """
        self.policy.require("read_context")
        if not isinstance(items, list) or len(items) > MAX_EVIDENCE_BATCH:
            raise GraphError("evidence_batch_limit")
        loaded, results = {}, []
        for item in items:
            contexts = item.get("contexts") if isinstance(item, dict) else None
            if not isinstance(contexts, list) or not 1 <= len(contexts) <= 4 or not all(
                    isinstance(c, str) for c in contexts):
                raise GraphError("invalid_evidence_batch")
            outcome = None
            for index, context_id in enumerate(contexts):
                try:
                    if context_id not in loaded:
                        loaded[context_id] = self.context(context_id)
                    outcome = dict(context_id=context_id, evidence=self._evidence(loaded[context_id], item.get("citation")))
                    break
                except GraphError as exc:
                    outcome = dict(error=exc.code)
                    if exc.code != "not_found":
                        break
                except ValueError:  # pydantic ValidationError of a malformed citation
                    outcome = dict(error="invalid_citation")
                    break
            results.append(outcome)
        return dict(schema=SCHEMA, results=results)

    def _evidence(self, context, citation):
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

    def propose(self, context_id, proposal, *, from_model=False, admission_check=None):
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
        record = dict(proposal=p.model_dump(), context_id=context_id, basis=context["basis"],
                      actor=self.policy.subject, origin="model" if from_model else "external",
                      trust="HUMAN_CORRECTION" if p.kind == "human_correction" else "UNAPPROVED_CANDIDATE")
        keys, bases = content_keys(context), cited_bases(context, [c.model_dump() for c in p.citations])
        return self.store.propose(self.view, record, context["id"], limit=self.policy.limits.max_proposals,
                                  scope=self.scope, grants=self.grants, bases=bases,
                                  config=config_digest(self.policy, {b["repository"] for b in bases}),
                                  active=lambda row: holds(row, keys, self.policy, self.view),
                                  **({"admission_check": admission_check} if admission_check is not None else {}))

    def proposals(self, context, *, assessment=None):
        """Each proposal is judged by the files it cites, not by the whole corpus basis.

        An unrelated edit (a README) keeps it CURRENT in the new context; a change of a
        cited file, of the service address map or of approved requirements makes it STALE
        with proposal_basis_differs. History stays readable.
        """
        assessment = self.freshness(context) if assessment is None else assessment
        rows = self.store.scoped_proposals(self.scope, self.grants)
        keys = content_keys(context)
        output = []
        superseded = {x["proposal"]["supersedes"] for x in rows if x["proposal"]["supersedes"]}
        holding = {x["id"] for x in rows if holds(x, keys, self.policy, self.view)}
        for row in rows:
            fresh = assessment if row["id"] in holding else {
                **assessment, "status": "STALE", "reasons": assessment["reasons"] + ["proposal_basis_differs"]}
            conflicting = [x["id"] for x in rows if x["id"] != row["id"]
                           and x["proposal"]["key"] == row["proposal"]["key"]
                           and x["proposal"]["statement"] != row["proposal"]["statement"]
                           and x["id"] in holding and row["id"] in holding and x["id"] not in superseded]
            public = {k: v for k, v in row.items()
                      if k not in ("cited_bases", "cited_config", "cited_view", "cited_profile")}
            output.append({**public, "status": "SUPERSEDED" if row["id"] in superseded else fresh["status"],
                           "freshness": fresh,
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

    def analyze_change(self, base_context_id, task="", revisions=None):
        """Compare a stored base context with a new head context (pinned by revisions)."""
        self.policy.require("maintain")
        base = self.context(base_context_id)
        if base.get("profile") != PROFILE:
            raise GraphError("base_profile_mismatch")
        current = self.prepare_context(task or base["task"], base.get("operation_id"), revisions)
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
            elif ((old.get("page_size_declared") or new.get("page_size_declared"))
                    and not (old["default_known"] and new["default_known"])
                    and old.get("declarations") != new.get("declarations")):
                # The declaration changed but its default is outside the grammar on
                # at least one side: unknown, never "no supported delta".
                code = "PAGE_DEFAULT_UNRESOLVED"
            elif (old.get("tracked_basis") is not None and new.get("tracked_basis") is not None
                    and sorted(old["tracked_basis"]) != sorted(new["tracked_basis"])):
                # The tracked declaration changed but no classifier knows how. Unknown,
                # never "no change" and never a proven break. Helpers it calls are untracked.
                code = "UNCLASSIFIED_OPERATION_CHANGE"
            if code is None:
                continue
            def default(op):
                return op.get("page_size_default") if op["default_known"] else "UNRESOLVED"
            unclassified = code == "UNCLASSIFIED_OPERATION_CHANGE"
            delta = dict(operation_id=id, code=code,
                         before="TRACKED_BASIS_CHANGED" if unclassified
                         else default(old) if code == "PAGE_DEFAULT_UNRESOLVED" else old.get("page_size_default"),
                         after="TRACKED_BASIS_CHANGED" if unclassified
                         else default(new) if code == "PAGE_DEFAULT_UNRESOLVED"
                         else new.get("page_size_default") if new else None,
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
                    code="UNCLASSIFIED_CHANGE_RECHECK" if unclassified
                    else "POSSIBLE_TRUNCATION" if risk and code != "OPERATION_REMOVED" else code if risk
                    else "RECHECK_REQUIRED",
                    dependency_id=dep["id"], consumer=dep["consumer"], usage=dep["usage"],
                    callsite=dict(repository=dep["repository"], path=dep["path"], line=dep["call_line"]),
                    dependency_freshness="CURRENT" if live else "STALE",
                    condition=(f"If helper obeys page_size, result set exceeds {after}, and consumer needs complete data"
                               if limited else "The tracked declaration changed in a way no classifier covers"
                               if unclassified else "If the changed declaration governs this call"),
                    evidence_stage="STATIC", evidence=delta["evidence"] + dep["evidence"] + dep["usage_evidence"],
                    requirement_ids=[r["id"] for r in rules],
                    check=(f"Run consumer with more than {after} records; compare full expected set, page traversal and explicit limits"
                           if limited else "Exercise the changed operation against this consumer's independent expectations"),
                    test_executed=False, compatibility_confirmed=False))
        result = dict(schema=SCHEMA, run_id=uuid.uuid4().hex, created_at=now(),
                      base_context_id=base_context_id, context_requested_id=base_context_id,
                      context_used_id=current["id"], base_basis=base["basis"], head_basis=current["basis"],
                      base_snapshots=base.get("snapshots", []), head_snapshots=current["snapshots"],
                      deltas=deltas, findings=findings, coverage=current["coverage"],
                      gaps=current["graph"]["gaps"], conflicts=current["graph"]["conflicts"],
                      freshness=self.freshness(current), release_decision=None,
                      unknowns=([] if deltas else ["no_supported_behavior_delta; arbitrary semantic changes are not classified"])
                      + (["unclassified_change; tracked declaration changed outside known classifiers, not a proven break; "
                          "helpers outside the declaration are not tracked"]
                         if any(d["code"] == "UNCLASSIFIED_OPERATION_CHANGE" for d in deltas) else []),
                      drafts=[dict(consumer=f["consumer"], text=f["check"], sent=False) for f in findings])
        return self.store.save(self.view, "analysis", result)
