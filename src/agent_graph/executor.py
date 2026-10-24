"""Constitution-bound executor for actions-v3 investigations.

Trusted code decides every effect: tools read only the context's pinned sources,
proposals go through the exact-quote validator and the static sufficiency check,
hypotheses stay unverified candidates, and the run stops on the constitution's
step, time, read, proposal and invalid-action limits. Cancellation, deadline and
step limits end the loop before another paid call; the reservation of the call
in flight is finished by the request worker when it actually ends.

The report and the diagnostics log hold only allowlisted fields: action name,
layer, reason code, field path, expected type, timings, IDs and content digests.
Prompts, source text, quotes and model replies are never logged or stored in it.
"""
from __future__ import annotations

import ast
import json
import logging
import threading
import time
import uuid

from .actions import (PROTOCOL, Rejection, action_schema, check_permitted, evidence_rejection, parse,
                      system_prompt)
from .constitution import load
from . import graph_query as persistent
from .contracts import GraphError, canonical, digest
from .evidence_refs import EvidenceSession
from .inference import ChatModel

LOG = logging.getLogger("agent_graph.diagnostics")
TRANSPORT = {"model_http_error", "model_timeout", "model_incomplete_or_refused", "model_response_limit",
             "model_unavailable_or_invalid", "invalid_model_usage", "unsupported_content_encoding",
             "model_input_limit", "missing_model_secret", "invalid_secret"}


def log_event(event, **fields):
    """One JSON line; callers pass allowlisted, already safe values only."""
    LOG.info(json.dumps(dict(event=event, **fields), ensure_ascii=True, sort_keys=True))


def compact_relationship(view):
    """What the model sees of a graph relationship: identities, status and where the
    bases are. No source text; ids are graph ids, not evidence receipts."""
    target = view["target"]
    bases = []
    for b in (view.get("bases") or []) + (view.get("history") or []):
        item = dict(origin=b["origin"], status=b["status"], closed_reason=b["closed_reason"])
        if b["origin"] == "code":
            item.update(repository=b["repository"], path=b["path"], line=b["start_line"], usage=b.get("usage"),
                        symbol=(b.get("callsite") or {}).get("symbol"))
        elif b["origin"] == "runtime":
            item.update(source=b["source"], method=b["method"], route=b["route"], window=b["window"],
                        request_count=b["aggregates"]["request_count"])
        bases.append(item)
    return dict(id=view["id"], kind=view["kind"], status=view["status"], source=view["source"].get("service"),
                target=target.get("service") + (f' {target["method"]} {target["route"]}'
                                                if target["kind"] == "operation" else ""),
                origins=view["origins"], freshness=dict(status=view["freshness"]["status"],
                                                         reasons=view["freshness"]["reasons"]),
                conflicts=[c["code"] for c in view["conflicts"]], bases=bases)


class Investigation:
    def __init__(self, graph, context_id, constitution, *, request_id, graph_snapshot=None):
        self.graph, self.context_id, self.constitution = graph, context_id, constitution
        self.request_id = request_id
        # Built by trusted code from graph.policy: this scope and these grants only.
        self.graph_snapshot = graph_snapshot
        self.context = graph.context(context_id)
        graph._current(self.context)
        self.session = EvidenceSession(graph, context_id)
        self.reads = self.proposals = self.invalid = 0
        self.supported, self.hypotheses, self.insufficient = [], [], []
        self.finished = None

    # Tools. Results are bounded and bound to the session's snapshot.
    def _sources(self, repository=None):
        coverage = {f["source_id"]: f["status"] for f in self.context["graph"].get("file_coverage", [])}
        return [dict(source_id=s["id"], repository=s["repository"], service=s["service"], path=s["path"],
                     lines=len(s["text"].splitlines()), file_status=coverage.get(s["id"]))
                for s in sorted(self.context["sources"].values(), key=lambda s: (s["repository"], s["path"]))
                if repository is None or s["repository"] == repository]

    def list_sources(self, action):
        limit = self.constitution.limit("list_sources", "max_results", 200)
        items = self._sources(action.repository)
        return dict(sources=items[:limit], truncated=len(items) > limit)

    def search(self, action):
        limit = self.constitution.limit("search", "max_results", 20)
        width = self.constitution.limit("search", "max_snippet_chars", 200)
        hits = []
        for source in self._sources(action.repository):
            text = self.context["sources"][source["source_id"]]["text"]
            for number, line in enumerate(text.splitlines(), 1):
                if action.query in line:  # literal match: no regular expressions from the model
                    hits.append(dict(source_id=source["source_id"], line=number, snippet=line.strip()[:width]))
                    if len(hits) > limit:
                        return dict(hits=hits[:limit], truncated=True, untrusted=True)
        return dict(hits=hits, truncated=False, untrusted=True)

    def list_symbols(self, action):
        source = self.context["sources"].get(action.source_id)
        if source is None:
            raise GraphError("not_found")
        limit = self.constitution.limit("list_symbols", "max_results", 100)
        symbols = []
        if source["path"].endswith(".py"):
            try:
                tree = ast.parse(source["text"])
            except (SyntaxError, ValueError, RecursionError):
                return dict(symbols=[], parse_error=True)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    first = min([node.lineno] + [d.lineno for d in node.decorator_list])
                    symbols.append(dict(name=node.name, kind=type(node).__name__, start_line=first,
                                        end_line=node.end_lineno))
        symbols.sort(key=lambda s: s["start_line"])
        return dict(symbols=symbols[:limit], truncated=len(symbols) > limit)

    def read_source(self, action):
        value = self.session.read(action.source_id, action.start_line, action.end_line)
        self.reads += 1
        return dict(untrusted_source=value)

    def graph_query(self, action):
        limit = self.constitution.limit("graph_query", "max_results", 50)
        graph = self.context["graph"]
        ops = [o for o in graph["operations"]
               if (action.service is None or o["service"] == action.service)
               and (action.method is None or o["method"] == action.method)
               and (action.route is None or o["path"] == action.route)]
        if action.query == "operations":
            items = [dict(operation_id=o["id"], service=o["service"], method=o["method"], route=o["path"],
                          evidence=[{k: e[k] for k in ("source_id", "start_line", "end_line")} for e in o["evidence"]])
                     for o in ops]
        else:
            ids = {o["id"]: o for o in ops}
            items = [dict(dependency_id=d["id"], operation_id=d["operation_id"], provider=ids[d["operation_id"]]["service"],
                          consumer=d["consumer"], repository=d["repository"], path=d["path"], line=d["call_line"],
                          usage=d["usage"], evidence=[{k: e[k] for k in ("source_id", "start_line", "end_line")}
                                                      for e in d["evidence"]])
                     for d in graph["dependencies"] if d["operation_id"] in ids]
        return dict(results=items[:limit], truncated=len(items) > limit, static_profile_only=True)

    def _persistent(self, request):
        if self.graph_snapshot is None:
            raise GraphError("graph_unavailable")
        value = persistent.dispatch(self.graph_snapshot, request)
        return value

    def _graph_result(self, value):
        return dict(graph_version=f"graph-{self.graph_snapshot.version}", result=value,
                    graph_ids_are_not_evidence_refs=True, confirms_hypotheses=False)

    def graph_find(self, action):
        hits = self._persistent(dict(tool="graph_find", text=action.text, kind=action.kind, limit=action.limit))
        return self._graph_result([dict(id=h["id"], kind=h["entity"]["kind"], label=h["label"]) for h in hits])

    def graph_neighbors(self, action):
        views = self._persistent(dict(tool="graph_neighbors", entity_id=action.entity_id,
                                      direction=action.direction, limit=action.limit))
        return self._graph_result([compact_relationship(v) for v in views])

    def graph_impact(self, action):
        impact = self._persistent(dict(tool="graph_impact", entity_id=action.entity_id, depth=action.depth,
                                       limit=action.limit))
        return self._graph_result(dict(
            target=impact["target"]["entity"],
            paths=[{k: p[k] for k in ("relationship_refs", "summary", "consumer", "service_level", "status")}
                   for p in impact["paths"]],
            affected=[dict(service=a["service"]["service"], owner_status=a["owner"]["status"],
                           teams=[t["team"] for t in a["owner"]["teams"]]) for a in impact["affected"]],
            relationships={k: compact_relationship(v) for k, v in impact["relationships"].items()},
            unknowns=impact["unknowns"],
            sources=[dict(source_kind=x["source_kind"], source_id=x["source_id"], status=x["status"],
                          freshness=x["freshness"]["status"], reasons=x["freshness"]["reasons"])
                     for x in impact["sources"]]))

    def graph_relationship(self, action):
        view = self._persistent(dict(tool="graph_relationship", relationship_id=action.relationship_id))
        return self._graph_result(compact_relationship(view))

    def graph_owner(self, action):
        value = self._persistent(dict(tool="graph_owner", service=action.service))
        owner = value["owner"]
        return self._graph_result(dict(status=owner["status"], teams=[t["team"] for t in owner["teams"]],
                                       source=owner["source"], source_version=owner["source_version"],
                                       history=value["history"]))

    def propose_dependency(self, action):
        self.proposals += 1
        assessment = self.session.assess(dict(claim=action.claim.model_dump(), evidence_refs=action.evidence_refs))
        if assessment["provenance"]["status"] == "REJECTED":
            raise GraphError(assessment["provenance"]["reason"])
        if assessment["sufficiency"]["status"] != "SUPPORTED_WITHIN_PROFILE":
            self.insufficient.append(digest(action.claim.model_dump()))
            return dict(status="INSUFFICIENT", sufficiency=assessment["sufficiency"],
                        hint="Not proven within the static profile; propose_hypothesis with unknowns if you still suspect it.")
        outcome = self.session.propose(dict(claim=action.claim.model_dump(), evidence_refs=action.evidence_refs))
        self.supported.append(outcome["candidate"]["id"])
        return dict(status="STORED_UNAPPROVED_CANDIDATE", candidate_id=outcome["candidate"]["id"],
                    sufficiency=assessment["sufficiency"])

    def propose_hypothesis(self, action):
        self.proposals += 1
        citations = [self.session.resolve(ref).model_dump() for ref in action.evidence_refs]
        claim = action.claim
        operation = f"{claim.method} {claim.route}" if claim.method else "operation unknown"
        statement = (f"UNVERIFIED HYPOTHESIS outside the static profile: {claim.consumer_service} -> "
                     f"{claim.provider_service or 'provider unknown'} {operation}. "
                     f"Unknowns: {', '.join(action.unknowns)}. Model statement: {claim.statement}")
        record = self.graph.propose(self.context_id, dict(
            key="hypothesis:" + digest(claim.model_dump()), kind="hypothesis", statement=statement[:4000],
            citations=citations, supersedes=None), from_model=True)
        self.hypotheses.append(record["id"])
        return dict(status="STORED_UNVERIFIED_HYPOTHESIS", candidate_id=record["id"],
                    sufficiency="NOT_ASSESSED", promotion="never_automatic")

    def finish(self, action):
        self.finished = action
        return dict(status="FINISHED")

    def handle(self, content):
        """Execute one reply. Returns (tool_result, record) where record is the safe event."""
        try:
            action = parse(content)
            check_permitted(action, self.constitution, reads=self.reads, proposals=self.proposals)
            try:
                result = getattr(self, action.name)(action)
            except GraphError as exc:
                raise evidence_rejection(exc, action) from None
        except Rejection as rejection:
            self.invalid += 1
            record = rejection.record
            return dict(rejected=True, **{k: v for k, v in record.items()
                                          if k in ("layer", "reason_code", "field_path", "expected")}), record
        return result, dict(action=action.name, accepted=True)


def _outcome(inv, stop):
    if stop:
        return stop
    if inv.invalid > inv.constitution.limits.max_invalid_actions:
        return "invalid_actions"
    if inv.finished is None:
        return "step_limit"
    if inv.supported:
        return "supported_dependency"
    if inv.hypotheses:
        return "hypotheses_only"
    return "abstained"


def run_investigation(graph, context_id, *, model=None, cancel=None, deadline_epoch=None, request_id=None,
                      constitution_path=None, graph_store=None, runtime_sources=(),
                      ownership_sources=("installation_mapping",)):
    """graph_store enables the graph_* tools. The snapshot is built here from
    graph.policy, so the model sees only this installation/environment and grants;
    runtime_sources and ownership_sources come from operator configuration."""
    graph.policy.require("maintain")
    graph.policy.require("propose")
    config = graph.policy.model
    if config is None:
        raise GraphError("model_not_configured")
    if config.protocol != PROTOCOL:
        raise GraphError("protocol_mismatch")
    constitution, version = load(constitution_path or graph.policy.constitution)
    request_id = request_id or uuid.uuid4().hex
    cancel = cancel or threading.Event()
    model = model or ChatModel(config)
    started_epoch, started = time.time(), time.monotonic()
    stop_epoch = started_epoch + constitution.limits.max_seconds
    if deadline_epoch is not None:
        stop_epoch = min(stop_epoch, deadline_epoch)
    snapshot = (persistent.GraphQuery.for_policy(graph_store, graph.policy, runtime_sources=runtime_sources,
                                                 ownership_sources=ownership_sources)
                if graph_store is not None else None)
    inv = Investigation(graph, context_id, constitution, request_id=request_id, graph_snapshot=snapshot)
    schema = action_schema()
    task = dict(task=inv.context["task"], task_data_is_untrusted=True, context_id=context_id,
                sources=inv._sources()[:constitution.limit("list_sources", "max_results", 200)],
                gaps=[{k: g[k] for k in ("code", "repository", "path") if k in g} for g in inv.context["graph"]["gaps"]][:100],
                remaining_steps=constitution.limits.max_steps,
                persistent_graph=f"graph-{snapshot.version}" if snapshot is not None else None)
    messages = [dict(role="system", content=system_prompt(constitution)), dict(role="user", content=canonical(task))]
    run = uuid.uuid4().hex
    events, diagnostics, stop = [], [], None
    log_event("investigation_started", request_id=request_id, run_id=run, context_id=context_id,
              configuration_id=config.configuration_id, constitution=version, protocol=PROTOCOL)
    for step in range(constitution.limits.max_steps):
        if cancel.is_set():
            stop = "cancelled"
            break
        if time.time() >= stop_epoch:
            stop = "deadline"
            break
        graph._current(inv.context)  # stale or superseded context: the caller decides (SUPERSEDED)
        estimated = len(canonical(messages).encode()) + len(canonical(schema).encode()) + 4096
        call_started = time.monotonic()
        try:
            reservation = graph.store.reserve(graph.policy.installation_id, run,
                                              estimated + config.max_output_tokens, config)
        except GraphError as exc:
            stop = "budget" if exc.code in ("budget_exhausted", "model_busy", "budget_currency_changed") else None
            if stop is None:
                raise
            break
        try:
            if isinstance(model, ChatModel):
                content, usage = model.complete_raw(messages, schema, cancel=cancel, deadline_epoch=stop_epoch,
                                                    on_finished=graph.store.reservation_finalizer(reservation))
            else:
                try:
                    content, usage = model.complete_raw(messages, schema, cancel=cancel, deadline_epoch=stop_epoch)
                finally:
                    graph.store.finish_reservation(reservation)
        except GraphError as exc:
            seconds = time.monotonic() - call_started
            if exc.code in ("cancelled",):
                stop = "cancelled"
            elif exc.code in ("model_timeout", "investigation_deadline") and time.time() >= stop_epoch:
                stop = "deadline"
            else:
                stop = "transport_failure"
            record = Rejection("transport", exc.code if exc.code in TRANSPORT | {"cancelled"} else "transport_error").record
            diagnostics.append(dict(step=step, seconds=round(seconds, 3), **record))
            log_event("action_rejected", request_id=request_id, run_id=run, step=step, **record)
            break
        seconds = time.monotonic() - call_started
        if cancel.is_set() or time.time() >= stop_epoch:
            # The reply arrived after the stop signal: never execute it.
            stop = "cancelled" if cancel.is_set() else "deadline"
            break
        result, record = inv.handle(content)
        event = dict(step=step, seconds=round(seconds, 3), usage=usage, **record)
        events.append(event)
        if not record.get("accepted"):
            diagnostics.append(dict(step=step, seconds=round(seconds, 3), **record))
            log_event("action_rejected", request_id=request_id, run_id=run, step=step,
                      configuration_id=config.configuration_id, **record)
            if inv.invalid > constitution.limits.max_invalid_actions:
                break
        else:
            log_event("action_accepted", request_id=request_id, run_id=run, step=step, action=record["action"],
                      seconds=round(seconds, 3))
        if inv.finished is not None:
            break
        messages.append(dict(role="assistant", content=content))
        messages.append(dict(role="user", content=canonical(dict(
            tool_result=result, remaining_steps=constitution.limits.max_steps - step - 1))))
    outcome = _outcome(inv, stop)
    mapped = constitution.outcomes[outcome]
    report = dict(schema="graph-investigation-2", protocol=PROTOCOL, run_id=run, request_id=request_id,
                  context_id=context_id, configuration_id=config.configuration_id, model=config.model,
                  constitution_version=version, outcome=outcome, status=mapped.status, reason_code=mapped.reason,
                  finish=inv.finished.model_dump() if inv.finished else None, steps=len(events),
                  invalid_actions=inv.invalid, reads=inv.reads, events=events, diagnostics=diagnostics,
                  candidate_ids=inv.supported, hypothesis_ids=inv.hypotheses,
                  insufficient_claims=inv.insufficient,
                  graph_version=f"graph-{snapshot.version}" if snapshot is not None else None,
                  budget=graph.store.budget_totals(graph.policy.installation_id),
                  seconds=round(time.monotonic() - started, 3), model_quality_established=False)
    log_event("investigation_finished", request_id=request_id, run_id=run, outcome=outcome, status=mapped.status,
              reason_code=mapped.reason, steps=len(events), invalid_actions=inv.invalid)
    return graph.store.save(graph.view, "investigation", report)

