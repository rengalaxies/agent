"""Orchestration of one installation: receive → ingest → analyze → publish.

``step()`` performs one unit of work in a fixed priority: ingest deliveries
first (they may revoke older generations), then publish, then analyze. One
worker calls ``step()``; the webhook receiver only calls ``receive()``.
"""

from __future__ import annotations

import uuid

from agent_graph.output_contracts import ContractError

from .analysis import AnalysisUnavailable, build_request, view_from_result
from .connectors.base import ResourceNotAllowed, Snapshot, WebhookRejected
from .envelope import EventEnvelope, canonical, digest, iso
from .http import AuthError, ClientError, ConnectorError, NotFound, RateLimited
from .publisher import AUTH_RETRY_SECONDS, Publisher, doc_digest, failure_doc, resource_marker, result_doc, stale_doc
from .queue import ServiceStore

TRIGGER = {"pr": "pr", "jira": "jira"}


class Service:
    def __init__(self, *, store: ServiceStore, connectors: dict, analyzer, installation_id: str, environment: str,
                 analysis_settings: dict | None = None, backends: dict | None = None, hook=None, worker_id=None):
        self.store, self.connectors, self.analyzer = store, connectors, analyzer
        self.installation_id, self.environment = installation_id, environment
        self.analysis_settings = analysis_settings or {}
        self.hook = hook or (lambda phase, item: None)
        self.worker_id = worker_id or uuid.uuid4().hex
        self.publisher = Publisher(store, connectors, backends or connectors, hook=self.hook)

    # -- receive ----------------------------------------------------------

    def receive(self, provider: str, headers: dict[str, str], body: bytes) -> tuple[int, dict]:
        """Verify and durably record a delivery. Never fetches and never trusts payload URLs."""
        connector = self.connectors.get(provider)
        if connector is None:
            return 404, {"error": "provider_not_configured"}
        headers = {k.lower(): v for k, v in headers.items()}
        try:
            envelope = connector.parse_webhook(headers, body)
        except WebhookRejected as exc:
            return exc.status, {"error": exc.code}
        inserted, state = self.store.add_event(envelope)
        return (202 if inserted else 200), {"event_id": envelope.event_id, "state": state, "duplicate": not inserted}

    # -- worker -----------------------------------------------------------

    def recover(self) -> dict:
        return self.store.recover()

    def step(self) -> str | None:
        self.store.unblock_due()
        event = self.store.due_event()
        if event:
            return self._ingest(event)
        intent = self.store.claim_intent(self.worker_id)
        if intent:
            try:
                return "publish:" + self.publisher.publish(intent, ingest_snapshot=self._apply)
            except ResourceNotAllowed as exc:
                self.store.intent_final(intent, "FAILED", exc.code)
                return "publish:failed"
        job = self.store.claim_job(self.worker_id)
        if job:
            return self._analyze(job)
        return None

    def run_until_idle(self, max_steps: int = 500) -> list[str]:
        done = []
        for _ in range(max_steps):
            outcome = self.step()
            if outcome is None:
                return done
            done.append(outcome)
        raise RuntimeError("step_limit_exceeded")

    # -- ingest -----------------------------------------------------------

    def _stale_notice(self, snapshot: Snapshot):
        def render(generation):
            doc = stale_doc(snapshot=snapshot.data, kind=snapshot.kind, generation=generation)
            return canonical(doc), doc_digest(doc), resource_marker(self.installation_id, snapshot.resource_id)
        return render

    def _apply(self, snapshot: Snapshot, event_id: str) -> dict:
        provider = snapshot.resource_id.split(":", 1)[0]
        return self.store.apply_snapshot(resource_id=snapshot.resource_id, provider=provider, kind=snapshot.kind,
                                         version=snapshot.version, snapshot=snapshot.data, event_id=event_id,
                                         closed=snapshot.closed, stale_notice=self._stale_notice(snapshot))

    def _ingest(self, event) -> str:
        connector = self.connectors[event["provider"]]
        try:
            snapshot = connector.fetch(event["resource_id"])
        except ResourceNotAllowed as exc:
            self.store.finish_event(event, "IGNORED", exc.code)
            return "ingest:ignored"
        except AuthError as exc:
            self.store.note("connection_unauthorized", event["provider"], f"{event['provider']}:{exc.status}")
            self.store.defer_event(event, exc.code, AUTH_RETRY_SECONDS)
            return "ingest:deferred"
        except ClientError as exc:
            self.store.finish_event(event, "FAILED", exc.code)
            self.store.note("provider_rejected", event["resource_id"], str(exc.status))
            return "ingest:failed"
        except ConnectorError as exc:
            # 429/5xx/timeouts: bounded retries, then FAILED until the next reconciliation revives it.
            delay = exc.retry_after if isinstance(exc, RateLimited) else None
            state = self.store.defer_event(event, exc.code, delay)
            return "ingest:" + ("failed" if state == "FAILED" else "deferred")
        self.store.clear_notice("connection_unauthorized", event["provider"])
        self.store.clear_notice("postsend_check_failed", event["resource_id"])
        self.store.clear_notice("provider_rejected", event["resource_id"])
        outcome = self._apply(snapshot, event["event_id"])
        self.store.finish_event(event, "COALESCED" if outcome["action"] == "coalesced" else "INGESTED",
                                outcome["action"])
        return "ingest:" + outcome["action"]

    # -- analyze ----------------------------------------------------------

    def _failure_intent(self, job, reason_code):
        doc = failure_doc(reason_code=reason_code, snapshot=job["snapshot"], kind=_kind(job), generation=job["generation"])
        return {"kind": "failure", "body": canonical(doc), "body_digest": doc_digest(doc),
                "marker": resource_marker(self.installation_id, job["resource_id"])}

    def _give_up_or_retry(self, job, reason_code, delay=None) -> str:
        if job["attempts"] >= self.store.limits.max_analysis_attempts:
            self.store.complete_job(job, state="FAILED", result=None, reason=reason_code,
                                    intent=self._failure_intent(job, reason_code))
            return "analyze:failed"
        self.store.requeue_job(job, reason_code, count_attempt=True, delay=delay)
        return "analyze:retry"

    def _analyze(self, job) -> str:
        connector = self.connectors[job["resource_id"].split(":", 1)[0]]
        snapshot = Snapshot(job["resource_id"], _kind(job), job["resource_version"], job["snapshot"])
        self.hook("claimed", job)
        git = self.connectors.get("github")
        failing = connector.provider
        try:
            prepared = connector.prepare(snapshot)
            revisions = prepared.repository_revisions
            if git is not None and (not revisions or hasattr(self.analyzer, "reconcile_graph")):
                failing = git.provider
                mainline = git.pin_revisions(None)  # default-branch tips: the graph's main-line memory
                if not revisions:
                    revisions = mainline  # a Jira analysis reads the pinned branches
                else:
                    prepared.attachments["mainline_revisions"] = mainline
        except AuthError as exc:
            self.store.note("connection_unauthorized", failing, f"{failing}:{exc.status}")
            self.store.requeue_job(job, exc.code, count_attempt=False, delay=AUTH_RETRY_SECONDS)
            return "analyze:blocked"
        except NotFound:
            return self._give_up_or_retry(job, "source_unavailable")
        except ClientError as exc:
            self.store.note("provider_rejected", job["resource_id"], str(exc.status))
            self.store.complete_job(job, state="FAILED", result=None, reason=exc.code,
                                    intent=self._failure_intent(job, exc.code))
            return "analyze:failed"
        except ConnectorError as exc:
            return self._give_up_or_retry(job, exc.code, delay=exc.retry_after)
        for provider in {connector.provider, failing}:
            self.store.clear_notice("connection_unauthorized", provider)
        self.store.clear_notice("provider_rejected", job["resource_id"])
        settings = dict(self.analysis_settings)
        describe = getattr(self.analyzer, "request_settings", None)
        if describe is not None:
            settings.update(describe())  # view, graph and constitution versions of the real analysis
        if git is not None:
            settings.setdefault("repositories", git.readable_repository_ids())
        deadline = min(job["deadline"], self.store.clock() + settings.get("analysis_seconds", 600))
        try:
            request = build_request(
                installation_id=self.installation_id, environment=self.environment,
                request_id=f"{job['job_id']}:{job['attempts']}", trigger_kind=TRIGGER[snapshot.kind],
                event_id=job["event_id"], resource_version=job["resource_version"], subject=prepared.subject,
                repository_revisions=revisions, settings=settings, deadline=iso(deadline))
        except ContractError as exc:
            # Configuration or input cannot form a valid request: a retry would not help.
            self.store.note("invalid_analysis_request", job["resource_id"], exc.code)
            self.store.complete_job(job, state="FAILED", result=None, reason="invalid_analysis_request",
                                    intent=self._failure_intent(job, "invalid_analysis_request"))
            return "analyze:failed"

        def cancelled() -> bool:
            return not self.store.job_is_current(job) or self.store.newer_event_pending(
                job["resource_id"], job["resource_version"], job["claimed_at"])

        try:
            result = self.analyzer.analyze(request, attachments=prepared.attachments, cancelled=cancelled)
        except AnalysisUnavailable as exc:
            return self._give_up_or_retry(job, exc.reason_code)
        self.hook("analyzed", job)
        if not self.store.job_is_current(job):
            self.store.complete_job(job, state="SUPERSEDED", result=result, reason="superseded", intent=None)
            return "analyze:superseded"
        if cancelled() or (isinstance(result, dict) and result.get("status") == "SUPERSEDED"):
            # A signed delivery claims a newer version: let ingestion decide, do not publish this one.
            self.store.requeue_job(job, "newer_event_pending", count_attempt=False)
            return "analyze:deferred"
        view = view_from_result(result, request)
        doc = result_doc(view, snapshot=job["snapshot"], kind=snapshot.kind, generation=job["generation"],
                         gaps=prepared.gaps)
        intent = {"kind": "result", "result_digest": digest(result) if isinstance(result, dict) else None,
                  "body": canonical(doc), "body_digest": doc_digest(doc),
                  "marker": resource_marker(self.installation_id, job["resource_id"])}
        created = self.store.complete_job(job, state="ANALYZED", result=result if isinstance(result, dict) else None,
                                          reason=view.reason_code, intent=intent)
        return "analyze:done" if created else "analyze:superseded"

    # -- reconciliation ---------------------------------------------------

    def reconcile(self) -> dict:
        """Recover leases, revive bounded work and enqueue changes whose deliveries were missed."""
        recovered = self.store.recover()
        revived = self.store.revive()
        added = 0
        for provider, connector in sorted(self.connectors.items()):
            name = f"reconcile:{provider}"
            since = self.store.checkpoint(name)
            started = self.store.clock()
            try:
                candidates = connector.reconcile_candidates(float(since) if since else None)
            except ConnectorError as exc:
                self.store.note("reconcile_failed", provider, f"{provider}:{exc.code}")
                continue
            self.store.clear_notice("reconcile_failed", provider)
            seen = set()
            for rid, version in candidates:
                seen.add(rid)
                resource = self.store.resource(rid)
                if resource is None or resource["version"] != version or resource["closed"]:
                    added += self._synthetic(provider, rid, f"reconcile:{rid}:{version}:{resource['generation'] if resource else 0}:"
                                             f"{resource['closed'] if resource else 0}")
            # Known resources outside a windowed listing still need a fetch:
            # deleted/moved Jira issues cannot appear in a recent-updates search.
            for resource in self.store.resources(provider):
                if not resource["closed"] and resource["resource_id"] not in seen:
                    added += self._synthetic(provider, resource["resource_id"],
                                             f"reconcile:{resource['resource_id']}:absent:{int(started)}")
            self.store.checkpoint(name, str(started))
        graph = self.reconcile_graph()
        return {"recovered": recovered, "revived": revived, "enqueued": added, "graph": graph,
                "reanalysed": self.reanalyse_on_new_basis(graph)}

    def reanalyse_on_new_basis(self, graph) -> int:
        """A new analysis basis (extractor profile, constitution, view) re-analyses open resources.

        Their versions did not change, so ingestion alone would leave the old basis'
        results published indefinitely. An unrecorded basis counts as new: an upgraded
        installation re-analyses once. Waits for a clean graph reconciliation, so the new
        basis is analysed on rebuilt graph bases.
        """
        basis = getattr(self.analyzer, "analysis_basis", None)
        if basis is None:
            return 0
        current = basis()
        if self.store.checkpoint("analysis_basis") == current:
            return 0
        if getattr(self.analyzer, "reconcile_graph", None) is not None and "github" in self.connectors and (
                graph is None or any(r.get("error") or r.get("status") == "UNAVAILABLE" for r in graph)):
            return 0
        reopened = self.store.reopen_open_resources(reason="analysis_basis_changed",
                                                    event_id=f"analysis_basis:{current[:16]}")
        self.store.checkpoint("analysis_basis", current)
        return reopened

    def reconcile_graph(self):
        """Periodic graph reconciliation: code at the default branches, runtime windows, ownership."""
        status = getattr(self.analyzer, "model_status", None)
        if status is not None:
            model = status()
            if model.ok or model.reason_code == "model_not_configured":
                self.store.clear_notice("model_disabled", None)
            else:
                self.store.note("model_disabled", None, model.reason_code)
        maintain = getattr(self.analyzer, "reconcile_graph", None)
        git = self.connectors.get("github")
        if maintain is None or git is None:
            return None
        try:
            results = maintain(git.pin_revisions(None))
        except ConnectorError as exc:
            self.store.note("graph_reconcile_failed", "github", exc.code)
            return None
        failed = [r for r in results if r.get("error") or r.get("status") == "UNAVAILABLE"]
        if failed:
            self.store.note("graph_source_unavailable", None, ",".join(sorted(r["source"] for r in failed)))
        else:
            self.store.clear_notice("graph_source_unavailable", None)
        return results

    def _synthetic(self, provider, rid, event_id) -> int:
        envelope = EventEnvelope(provider=provider, source="reconcile", event_id=event_id[:200],
                                 event_kind="reconcile", resource_id=rid, payload_digest=digest(event_id),
                                 received_at=self.store.clock())
        inserted, _ = self.store.add_event(envelope)
        return int(inserted)


def _kind(job) -> str:
    return "pr" if job["resource_id"].startswith("github:") else "jira"

