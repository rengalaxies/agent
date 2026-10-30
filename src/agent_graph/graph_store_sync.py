"""Event-driven graph updates and periodic reconciliation over one code path.

An event (a push, a PR head, a closed runtime window, an ownership file change)
updates only its source. Reconciliation re-reads every configured source, so an
event that never arrived is recovered on the next run. A source that fails
keeps its last bases and turns stale; the next successful run resumes it.
Scheduling the reconciliation is the service's job (batch 4/5A).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from .contracts import GraphError
from .engine import Graph
from .graph_store import GraphStore, UNAVAILABLE_GAPS, load_ownership
from .runtime_observations import AccessLogSource, FreshnessPolicy, read_access_logs


class GraphMaintainer:
    def __init__(self, graph: Graph, graph_store: GraphStore, *, runtime_sources=(), ownership_path=None,
                 runtime_window_seconds=3600, runtime_freshness: FreshnessPolicy | None = None):
        self.graph, self.gs = graph, graph_store
        self.runtime_sources = [s if isinstance(s, AccessLogSource) else AccessLogSource.model_validate(s)
                                for s in runtime_sources]
        policy = graph.policy
        if any((s.installation_id, s.environment) != (policy.installation_id, policy.environment)
               for s in self.runtime_sources):
            raise GraphError("runtime_source_scope_mismatch")
        self.ownership_path = ownership_path
        self.window = timedelta(seconds=runtime_window_seconds)
        self.runtime_freshness = runtime_freshness

    def on_code_event(self, revisions=None, trigger="event"):
        context = self.graph.prepare_context(revisions=revisions)
        version, summary = self.gs.sync_code(context, trigger)
        unavailable = any(g.get("code") in UNAVAILABLE_GAPS and g.get("repository")
                          for g in context["graph"]["gaps"])
        return dict(source="code", version=version, summary=summary, context_id=context["id"],
                    status="UNAVAILABLE" if unavailable else "OK")

    def on_runtime_window(self, source, start, end, trigger="event"):
        result = read_access_logs(source, start, end, freshness=self.runtime_freshness)
        version, summary = self.gs.sync_runtime(result, trigger)
        return dict(source=f"runtime:{source.id}", version=version, summary=summary,
                    status=result["source"]["status"])

    def on_ownership_change(self, trigger="event"):
        policy = self.graph.policy
        mapping = load_ownership(self.ownership_path) if self.ownership_path else None
        version, summary = self.gs.sync_ownership(policy.installation_id, policy.environment, mapping,
                                                  trigger=trigger)
        return dict(source="ownership", version=version, summary=summary,
                    status="OK" if mapping else "UNAVAILABLE")

    def reconcile(self, revisions=None, now=None):
        """Re-read all sources. One failing source does not stop the others."""
        now = now or datetime.now(timezone.utc)
        results = []
        try:
            results.append(self.on_code_event(revisions, trigger="reconcile"))
        except GraphError as exc:
            results.append(dict(source="code", error=exc.code))
        for source in self.runtime_sources:
            results.append(self.on_runtime_window(source, now - self.window, now, trigger="reconcile"))
        if self.ownership_path:
            results.append(self.on_ownership_change(trigger="reconcile"))
        return results
