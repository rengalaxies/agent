"""The real analysis: the batch 2A core and the batch 3 graph behind the service's Analyzer protocol.

PR: base context at the PR base commit, ``Graph.analyze_change`` at the pinned
head map, ``agent_graph.results.change_result``. Jira before any diff: the
persistent graph is synced at the pinned default branches, the operations the
task names are found in the graph (``intent``), and the result is assembled
from ``GraphQuery.impact()`` (``jira_impact``). Owners always come from the
graph (``GraphQuery.owner``), never from a guess.

The persistent graph holds main-line memory only: Jira events, PR events and
the periodic reconciliation sync it at the default-branch tips, never at an
unmerged PR head.

The model part runs only through ``agent_graph.executor.run_investigation`` and
only when ``qualification.check`` verified a batch 2B report against the loaded
code. A configured model that fails the check is never called; its USEFUL
results become PARTIAL ``model_unavailable`` with the check's reason code.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import threading
import time

from agent_graph.contracts import GraphError, Policy
from agent_graph.output_contracts import dump_document, parse_document

from .analysis import AnalysisUnavailable
from .intent import match_operations
from .jira_impact import jira_result
from .qualification import check

OWNERSHIP_SOURCES = ("installation_mapping", "codeowners", "service_catalog")


class GraphOperations:
    """Operations visible to the grant-scoped graph query, in the shape ``intent`` expects."""

    def __init__(self, query):
        self.query = query

    def operations(self) -> list[dict]:
        result = {}
        for service in self.query.summary()["services"]:
            for hit in self.query.find(service, kind="operation", limit=100):
                entity = hit["entity"]
                if entity["service"] == service:
                    result[hit["id"]] = {"id": hit["id"], "service": service, "method": entity["method"],
                                         "path": entity["route"]}
        return sorted(result.values(), key=lambda o: o["id"])


class CoreAnalyzer:
    def __init__(self, policy: dict, state_dir: Path, *, ownership_path: str | None = None, runtime_sources=(),
                 code_version: str, constitution_path: str | None = None, model=None,
                 model_qualification: dict | None = None, runtime_window_seconds: int = 3600):
        from agent_graph.constitution import load
        from agent_graph.runtime_observations import AccessLogSource

        self.policy = Policy.model_validate(policy)
        self.state_dir = Path(state_dir)
        self.ownership_path = ownership_path
        self.runtime_sources = [s if isinstance(s, AccessLogSource) else AccessLogSource.model_validate(s)
                                for s in runtime_sources]
        self.runtime_window_seconds = runtime_window_seconds
        self.code_version = code_version
        self.constitution_path = constitution_path or self.policy.constitution
        self.model = model
        self._local = threading.local()  # the core store holds one SQLite connection per thread
        _, self.constitution_version = load(self.constitution_path)
        self.qualification = check(model_qualification, self.policy, self.constitution_path)

    # -- per-thread core objects -----------------------------------------

    def _parts(self):
        parts = getattr(self._local, "parts", None)
        if parts is None:
            from agent_graph.engine import Graph
            from agent_graph.graph_store import GraphStore
            from agent_graph.graph_store_sync import GraphMaintainer
            from agent_graph.store import Store

            store = Store(self.state_dir)
            graph = Graph(self.policy, store)
            gs = GraphStore(store)
            maintainer = GraphMaintainer(graph, gs, runtime_sources=self.runtime_sources,
                                         ownership_path=self.ownership_path,
                                         runtime_window_seconds=self.runtime_window_seconds)
            parts = self._local.parts = (graph, gs, maintainer)
        return parts

    @property
    def graph(self):
        return self._parts()[0]

    def query(self):
        from agent_graph.graph_query import GraphQuery

        _, gs, _ = self._parts()
        return GraphQuery.for_policy(gs, self.policy, runtime_sources=[s.id for s in self.runtime_sources],
                                     ownership_sources=OWNERSHIP_SOURCES)

    def close(self):
        parts = getattr(self._local, "parts", None)
        if parts is not None:
            parts[0].store.close()
            self._local.parts = None

    # -- service hooks ---------------------------------------------------

    def request_settings(self) -> dict:
        """Fields of AnalysisRequest that belong to the analysis configuration."""
        return {"view_id": self.policy.view_id(), "graph_version": f"graph-{self.query().version}",
                "constitution_version": self.constitution_version,
                "repositories": sorted(r.id for r in self.policy.repositories),
                "runtime_sources": sorted(s.id for s in self.runtime_sources),
                "model_configuration_id": self.policy.model.configuration_id
                if self.qualification.ok else None}

    def model_status(self):
        """For doctor and notices: whether the model path is on, and why not."""
        return self.qualification

    def reconcile_graph(self, revisions: dict) -> list[dict]:
        """Periodic re-read of code (at the default branches), runtime windows and ownership."""
        _, _, maintainer = self._parts()
        results = maintainer.reconcile(revisions, now=datetime.now(timezone.utc))
        return [{k: r[k] for k in ("source", "version", "status", "error") if k in r} for r in results]

    def graph_html(self) -> str:
        """Rendered on its own short-lived connection: it is called from the web server's thread pool."""
        from agent_graph.graph_query import GraphQuery
        from agent_graph.graph_store import GraphStore
        from agent_graph.graph_view import render_html
        from agent_graph.store import Store

        store = Store(self.state_dir)
        try:
            query = GraphQuery.for_policy(GraphStore(store), self.policy,
                                          runtime_sources=[s.id for s in self.runtime_sources],
                                          ownership_sources=OWNERSHIP_SOURCES)
            return render_html(query, environments=[self.policy.environment])
        finally:
            store.close()

    # -- analysis --------------------------------------------------------

    def _ownership(self, query) -> dict | None:
        """Graph owners in the mapping shape ``change_result`` reads."""
        services, source, version = {}, None, None
        for service in query.summary()["services"]:
            owner = query.owner(service)
            if owner["status"] != "UNKNOWN":
                services[service] = [t["team"] for t in owner["teams"]]
                source, version = owner["source"], owner["source_version"]
        return {"source": source, "version": version, "services": services} if services else None

    def _investigate(self, context_id, cancelled, deadline_epoch):
        if not self.qualification.ok:
            return None
        from agent_graph.executor import run_investigation

        cancel = threading.Event()
        watcher = threading.Thread(target=_watch, args=(cancel, cancelled), daemon=True)
        watcher.start()
        graph, gs, _ = self._parts()
        try:
            # graph_* tools read the persistent graph within the same grants as the service query;
            # graph ids are not evidence receipts, so anything built on them stays a candidate.
            return run_investigation(graph, context_id, model=self.model, cancel=cancel,
                                     deadline_epoch=deadline_epoch, constitution_path=self.constitution_path,
                                     graph_store=gs, runtime_sources=[s.id for s in self.runtime_sources],
                                     ownership_sources=OWNERSHIP_SOURCES)
        except GraphError:
            return None  # model failures leave the static result; the report keeps its own diagnostics
        finally:
            cancel.set()

    def analyze(self, request: dict, *, attachments: dict, cancelled) -> dict:
        from agent_graph.results import change_result, failed_result

        req = parse_document(request)
        meta = dict(code_version=self.code_version, constitution_version=self.constitution_version,
                    correlation_id=req.request_id)
        started, clock = _now(), time.monotonic()
        deadline_epoch = _epoch(req.deadline)
        revisions = dict(req.repository_revisions)
        graph, _, maintainer = self._parts()
        try:
            if req.pr is not None:
                if attachments.get("mainline_revisions"):
                    maintainer.on_code_event(attachments["mainline_revisions"], trigger="pr_event")
                base = graph.prepare_context(revisions={**revisions, req.pr.repository: req.pr.base_sha})
                if cancelled():
                    return dump_document(failed_result(req, "newer_head", superseded_by="newer-generation", **meta))
                analysis = graph.analyze_change(base["id"], revisions=revisions)
                investigation = self._investigate(analysis["context_used_id"], cancelled, deadline_epoch)
                result = change_result(graph, req, analysis, ownership=self._ownership(self.query()),
                                       investigation=investigation, started_at=started, finished_at=_now(),
                                       seconds={"analysis": time.monotonic() - clock}, **meta)
            else:
                synced = maintainer.on_code_event(revisions, trigger="jira_event")
                context = graph.context(synced["context_id"])
                if cancelled():
                    return dump_document(failed_result(req, "newer_resource_version",
                                                       superseded_by="newer-generation", **meta))
                query = self.query()
                texts = list(req.jira.text_fields.values())
                operation_ids, reason = match_operations(GraphOperations(query).operations(), texts)
                impacts = [query.impact(op, depth=2, limit=50) for op in operation_ids]
                investigation = self._investigate(context["id"], cancelled, deadline_epoch)
                result = jira_result(req, query, impacts, context=context, intent_reason=reason,
                                     investigation=investigation,
                                     code_version=self.code_version, constitution_version=self.constitution_version,
                                     started_at=started, seconds=time.monotonic() - clock)
        except GraphError as exc:
            if str(exc) in ("sources_changed_during_scan", "busy"):
                raise AnalysisUnavailable("source_unavailable") from None
            return dump_document(failed_result(req, "source_unavailable" if "commit" in str(exc)
                                               or "source" in str(exc) else "internal_error", **meta))
        return self._without_model(dump_document(result))

    def _without_model(self, document: dict) -> dict:
        """A configured model that failed its 2B check: the static result, explicitly marked partial."""
        if self.policy.model is None or self.qualification.ok or document["status"] in ("FAILED", "SUPERSEDED"):
            return document
        document["unknowns"] = document["unknowns"] + [
            {"code": "model_hypothesis_unverified", "subject": "qualification:" + self.qualification.reason_code}]
        if document["status"] == "USEFUL":
            document.update(status="PARTIAL", reason_code="model_unavailable")
        return dump_document(parse_document(document))


def _watch(cancel: threading.Event, cancelled):
    while not cancel.wait(0.2):
        if cancelled():
            cancel.set()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch(timestamp: str) -> float:
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
