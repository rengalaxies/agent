"""The real analysis: the batch 2A core behind the service's Analyzer protocol.

PR: base context at the PR base commit, ``Graph.analyze_change`` at the pinned
head map, ``agent_graph.results.change_result``. Jira: one context at the
pinned branches, operations named by the task (``intent``), consumers through
``DependencyQuery``, ``preliminary_result``. Statuses come from the 2A result
builder; the service adds none of its own.

``DependencyQuery`` is the thin seam batch 3 replaces with its graph query.
The model part runs only through ``agent_graph.executor.run_investigation`` and
only when the configuration is marked qualified (batch 2B); otherwise the
result is the static core result and no model is called.
"""

from __future__ import annotations

from pathlib import Path
import threading
import time
from typing import Protocol

from agent_graph.contracts import GraphError, Policy
from agent_graph.output_contracts import dump_document, parse_document

from .analysis import AnalysisUnavailable
from .intent import match_operations


class DependencyQuery(Protocol):
    def operations(self, context_id: str) -> list[dict]:
        """Operations declared in the context."""


class CoreDependencies:
    """Uses ``Graph.dependencies()`` until the batch 3 graph query exists."""

    def __init__(self, graph):
        self.graph = graph

    def operations(self, context_id: str) -> list[dict]:
        return self.graph.dependencies(context_id)["operations"]


class CoreAnalyzer:
    def __init__(self, policy: dict, state_dir: Path, *, ownership: dict | None = None, code_version: str,
                 constitution_path: str | None = None, model=None, model_qualified: bool = False,
                 query_factory=CoreDependencies):
        self.policy = Policy.model_validate(policy)
        self.state_dir = Path(state_dir)
        self.ownership, self.code_version = ownership, code_version
        self.constitution_path = constitution_path or self.policy.constitution
        self.model, self.model_qualified = model, model_qualified
        self.query_factory = query_factory
        self._local = threading.local()  # the core store holds a SQLite connection per thread
        from agent_graph.constitution import load

        _, self.constitution_version = load(self.constitution_path)

    @property
    def graph(self):
        graph = getattr(self._local, "graph", None)
        if graph is None:
            from agent_graph.engine import Graph
            from agent_graph.store import Store

            graph = self._local.graph = Graph(self.policy, Store(self.state_dir))
        return graph

    def close(self):
        graph = getattr(self._local, "graph", None)
        if graph is not None:
            graph.store.close()
            self._local.graph = None

    def request_settings(self) -> dict:
        """Fields of AnalysisRequest that belong to the analysis configuration."""
        view = self.policy.view_id()
        return {"view_id": view, "graph_version": "view:" + view[:32],
                "constitution_version": self.constitution_version,
                "repositories": sorted(r.id for r in self.policy.repositories),
                "model_configuration_id": self.policy.model.configuration_id
                if self.policy.model and self.model_qualified else None}

    def _investigate(self, context_id, cancelled, deadline_epoch):
        if not (self.model_qualified and self.policy.model):
            return None
        from agent_graph.executor import run_investigation

        cancel = threading.Event()
        watcher = threading.Thread(target=_watch, args=(cancel, cancelled), daemon=True)
        watcher.start()
        try:
            return run_investigation(self.graph, context_id, model=self.model, cancel=cancel,
                                     deadline_epoch=deadline_epoch, constitution_path=self.constitution_path)
        except GraphError:
            return None  # model failures leave the static result; the report keeps its own diagnostics
        finally:
            cancel.set()

    def analyze(self, request: dict, *, attachments: dict, cancelled) -> dict:
        from agent_graph.results import change_result, failed_result, preliminary_result

        req = parse_document(request)
        meta = dict(code_version=self.code_version, constitution_version=self.constitution_version,
                    correlation_id=req.request_id)
        started, clock = _now(), time.monotonic()
        deadline_epoch = _epoch(req.deadline)
        revisions = dict(req.repository_revisions)
        graph = self.graph
        try:
            if req.pr is not None:
                base = graph.prepare_context(revisions={**revisions, req.pr.repository: req.pr.base_sha})
                if cancelled():
                    return dump_document(failed_result(req, "newer_head", superseded_by="newer-generation", **meta))
                analysis = graph.analyze_change(base["id"], revisions=revisions)
                investigation = self._investigate(analysis["context_used_id"], cancelled, deadline_epoch)
                result = change_result(graph, req, analysis, ownership=self.ownership, investigation=investigation,
                                       started_at=started, finished_at=_now(),
                                       seconds={"analysis": time.monotonic() - clock}, **meta)
            else:
                texts = list(req.jira.text_fields.values())
                context = graph.prepare_context(task=" ".join(texts)[:2000], revisions=revisions)
                if cancelled():
                    return dump_document(failed_result(req, "newer_resource_version",
                                                       superseded_by="newer-generation", **meta))
                operation_ids, _ = match_operations(self.query_factory(graph).operations(context["id"]), texts)
                investigation = self._investigate(context["id"], cancelled, deadline_epoch)
                result = preliminary_result(graph, req, context, operation_ids, ownership=self.ownership,
                                            investigation=investigation, started_at=started, finished_at=_now(),
                                            seconds={"analysis": time.monotonic() - clock}, **meta)
        except GraphError as exc:
            if str(exc) in ("sources_changed_during_scan", "busy"):
                raise AnalysisUnavailable("source_unavailable") from None
            return dump_document(failed_result(req, "source_unavailable" if "commit" in str(exc)
                                               or "source" in str(exc) else "internal_error", **meta))
        return dump_document(result)


def _watch(cancel: threading.Event, cancelled):
    while not cancel.wait(0.2):
        if cancelled():
            cancel.set()


def _now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _epoch(timestamp: str) -> float:
    from datetime import datetime

    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp()
