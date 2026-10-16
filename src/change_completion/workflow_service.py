"""Authenticated callers coordinate review/delivery; never execute from a GET."""
from dataclasses import dataclass
from pathlib import Path

from .adapters import discover_repository, read_repository_file
from .delivery import DeliveryConfig, GatewayDelivery
from .models import Action, ContentRef, TransitionSpec
from .runtime import _granted, authority_digest, encode, runtime_revision, utc_now
from .verification import ExpectationSuite, context_digest, digest_bytes, verify_observations


@dataclass(frozen=True)
class Principal:
    actor: str
    transitions: frozenset[str]
    permissions: frozenset[str]


class WorkflowService:
    """Operator-controlled bindings and loaders, not paths from request bodies."""
    def __init__(self, runs, workflows, repository: Path, spec_loader, suite_loader,
                 fixture_loader, policy_loader, *, worker_actor, gateway=None, clock=utc_now,
                 destinations=None, notification_routes=None):
        self.runs, self.workflows, self.repository = runs, workflows, Path(repository)
        self.spec_loader, self.suite_loader = spec_loader, suite_loader
        self.fixture_loader, self.policy_loader = fixture_loader, policy_loader
        self.worker_actor, self.gateway, self.clock = worker_actor, gateway or GatewayDelivery(DeliveryConfig()), clock
        self.destinations, self.notification_routes = dict(destinations or {}), dict(notification_routes or {})

    def authorize(self, principal, transition_id, permission):
        if transition_id not in principal.transitions or permission not in principal.permissions:
            raise PermissionError("project permission required")

    def _rows(self):
        with self.runs._connection() as c:
            return [dict(r) for r in c.execute("SELECT run_id,transition_id,status,created_at FROM runs ORDER BY created_at DESC")]

    def _load(self, run_id, principal, permission="read"):
        row = self.runs.get(run_id)
        self.authorize(principal, row["transition_id"], permission)
        spec = self.spec_loader()
        if spec.transition_id != row["transition_id"]:
            raise KeyError("run not bound to this installation")
        return row, spec

    def _fresh(self, row, spec):
        """Revalidate receipts without running SQL, a model or an external sender."""
        try:
            result = row["result"]
            if row["status"] != "READY_FOR_REVIEW" or not result:
                return False, "run_not_ready"
            now, policy = self.clock(), self.policy_loader()
            if (result["context_sha256"] != context_digest(spec)
                    or result.get("runtime_revision") != runtime_revision()
                    or result.get("authority_sha256") != authority_digest(policy, self.worker_actor)):
                return False, "context_runtime_or_authority_changed"
            refs = [spec.before, spec.target, *[r for c in spec.components for r in c.artifacts],
                    *[r.basis for r in spec.requirements], *[d.basis for d in spec.dependencies if d.basis]]
            for ref in refs:
                if digest_bytes(read_repository_file(self.repository, ref.uri)) != ref.sha256:
                    return False, "snapshot_changed"
            discovery = discover_repository(self.repository)
            if discovery["gaps"] != ["static_snapshot_only_runtime_consumers_unknown"]:
                return False, "discovery_incomplete"
            expected_sql = {r.uri for c in spec.components if c.component_id in spec.consumers for r in c.artifacts}
            if {f["path"] for f in discovery["files"] if f["path"].endswith(".sql")} != expected_sql:
                return False, "consumer_scope_changed"
            suite_bytes = self.suite_loader()
            suite = ExpectationSuite.model_validate_json(suite_bytes)
            for case in suite.cases:
                if digest_bytes(self.fixture_loader(case.fixture.uri)) != case.fixture.sha256:
                    return False, "fixture_changed"
            patches = result["patches"]
            if set(patches) != set(spec.consumers):
                return False, "cached_patch_set_changed"
            if any(digest_bytes(p["candidate"].encode()) != p["sha256"] for p in patches.values()):
                return False, "cached_candidate_changed"
            candidate = ContentRef(uri="runtime://"+row["run_id"]+"/candidate", sha256=digest_bytes(encode(patches)))
            if candidate.sha256 != result["candidate_sha256"]:
                return False, "candidate_bundle_changed"
            report = verify_observations(spec, candidate, suite_bytes, encode(result["observations"]), policy,
                                         at=now, actor=self.worker_actor)
            if report.status != "PASS":
                return False, "verification_expired_or_revoked"
            for component in spec.components:
                if not _granted(spec, policy, self.worker_actor, component.component_id, Action.DISCOVER, now):
                    return False, "discovery_revoked"
            for consumer in spec.consumers:
                if not _granted(spec, policy, self.worker_actor, consumer, Action.EXPORT, now):
                    return False, "export_revoked"
            return True, None
        except (OSError, ValueError, TypeError, KeyError, RuntimeError):
            return False, "freshness_unavailable"

    def _workflow(self, row, spec, fresh, reason):
        digest = digest_bytes(encode({"run": row["result"], "spec": spec.model_dump(mode="json")}))
        try:
            workflow = self.workflows.get(row["run_id"])
        except KeyError:
            if not fresh:
                return None
            owners = {c.component_id: c.owner for c in spec.components if c.component_id in spec.consumers}
            workflow = self.workflows.register(row["run_id"], digest, owners, spec.acceptor)
        if fresh and workflow["package_digest"] != digest:
            fresh, reason = False, "review_package_changed"
        if not fresh:
            workflow = self.workflows.invalidate(row["run_id"], reason or "stale")
        return workflow

    def view(self, run_id, principal):
        row, spec = self._load(run_id, principal)
        fresh, reason = self._fresh(row, spec)
        workflow = self._workflow(row, spec, fresh, reason)
        if workflow and workflow["status"] == "STALE":
            fresh, reason = False, "workflow_invalidated"
        result = row["result"] or {}
        if not fresh:
            result = {"reason_codes": [reason], "coverage_limits": result.get("coverage_limits", []), "effects_authorized": False}
        # Outbox payloads are private; stale views must not leak cached patches.
        if workflow:
            workflow = {**workflow, "outbox": [{k: v for k, v in item.items() if k != "payload"} for item in workflow["outbox"]]}
        history = row["events"] + (workflow["history"] if workflow else [])
        if not fresh:
            history = [{k: v for k, v in event.items() if k != "payload"} for event in history]
        return {"run": {"run_id": run_id, "transition_id": spec.transition_id, "status": row["status"],
                        "criticality": spec.criticality, "owner": spec.owner, "acceptor": spec.acceptor,
                        "freshness": "current" if fresh else "stale", "workflow_status": workflow["status"] if workflow else "UNAVAILABLE",
                        "delivery_enabled": bool(self.gateway.config and self.gateway.config.allow_send),
                        "actor": principal.actor,
                        "can_review": "review" in principal.permissions and principal.actor in ({c.owner for c in spec.components if c.component_id in spec.consumers} | {spec.acceptor}),
                        "can_prepare_delivery": "prepare_delivery" in principal.permissions,
                        "can_send_delivery": "send_delivery" in principal.permissions,
                        "can_revalidate": "revalidate" in principal.permissions},
                "spec": spec.model_dump(mode="json"), "result": result, "workflow": workflow,
                "history": history}

    def list_runs(self, principal):
        rows = []
        for row in self._rows():
            if row["transition_id"] not in principal.transitions:
                continue
            try:
                rows.append(self.view(row["run_id"], principal)["run"])
                if len(rows) >= 100:
                    break
            except KeyError:
                continue
        return {"runs": rows}

    def review(self, run_id, principal, decision, package_digest, comment=""):
        row, spec = self._load(run_id, principal, "review")
        current = self.view(run_id, principal)
        if current["run"]["freshness"] != "current":
            raise ValueError("stale package")
        owners = current["workflow"]["owners"]
        if principal.actor not in set(owners.values()) | {spec.acceptor}:
            raise PermissionError("not an owner or acceptor")
        self.workflows.review(run_id, principal.actor, decision, package_digest, comment)
        return self.view(run_id, principal)

    def reopen(self, run_id, principal, package_digest):
        row, spec = self._load(run_id, principal, "revalidate")
        fresh, _ = self._fresh(row, spec)
        digest = digest_bytes(encode({"run": row["result"], "spec": spec.model_dump(mode="json")}))
        if not fresh or digest != package_digest:
            raise ValueError("cannot reopen an unverified package")
        self.workflows.reopen(run_id, package_digest)
        return self.view(run_id, principal)

    def deliver(self, run_id, principal, kind, *, send=False):
        row, spec = self._load(run_id, principal, "send_delivery" if send else "prepare_delivery")
        current = self.view(run_id, principal)
        if current["run"]["freshness"] != "current" or current["workflow"]["status"] == "REJECTED":
            raise ValueError("package is stale or rejected")
        if kind not in {"pr", "notification"}:
            raise ValueError("invalid delivery kind")
        digest = current["workflow"]["package_digest"]
        result = current["result"]
        patches = {k: v for k, v in result["patches"].items() if v["diff"]}
        recipients = sorted({c.owner for c in spec.components if c.component_id in spec.consumers})
        payload = {"run_id": run_id, "transition_id": spec.transition_id, "package_digest": digest,
                   "criticality": spec.criticality, "recipients": recipients,
                   "requested_action": "review transition package", "acceptor": spec.acceptor,
                   "conditions": result["completion_conditions"], "coverage_limits": result["coverage_limits"]}
        if kind == "pr":
            if not patches:
                raise ValueError("no changed components")
            payload["patches"] = patches
            payload["destinations"] = {c: self.destinations[c] for c in patches if c in self.destinations}
        else:
            payload["destinations"] = {r: self.notification_routes[r] for r in recipients if r in self.notification_routes}
        key = digest_bytes(encode({"package": digest, "kind": kind, "payload": payload}))
        queued = self.workflows.enqueue(run_id, key, kind, payload)
        if not send:
            return {"status": "draft", "key": key, "outbox_status": queued["status"], "draft": payload, "effects_authorized": False}
        if not self.gateway.config or not self.gateway.config.allow_send:
            return {"status": "draft", "key": key, "effects_authorized": False}
        # A proposal PR is allowed before acceptance; it is not auto-merge/deploy.
        action = Action.PUBLISH_PR if kind == "pr" else Action.NOTIFY
        scope = set(patches) if kind == "pr" else set(spec.consumers)
        if set(payload["destinations"]) != (scope if kind == "pr" else set(recipients)):
            raise PermissionError("delivery destination not configured")
        now, policy = self.clock(), self.policy_loader()
        if not all(_granted(spec, policy, principal.actor, c, action, now) for c in scope):
            raise PermissionError("delivery authority unavailable")
        if queued["status"] == "DELIVERED":
            return {"status": "delivered", "key": key, "receipt": queued["receipt"], "reused": True}
        if queued["status"] != "PENDING":
            return {"status": "unknown", "key": key, "reason_codes": ["reconcile_existing_delivery"]}
        latest = self.view(run_id, principal)
        if latest["run"]["freshness"] != "current" or latest["workflow"]["status"] == "REJECTED":
            raise ValueError("package invalidated before send")
        if not all(_granted(spec, self.policy_loader(), principal.actor, c, action, self.clock()) for c in scope):
            raise PermissionError("delivery authority revoked")
        self.workflows.claim_delivery(key)
        outcome = self.gateway.send("pull_request" if kind == "pr" else "notification", payload, key)
        if outcome["status"] == "delivered":
            self.workflows.delivered(key, outcome["receipt"])
        else:
            self.workflows.uncertain(key, "outcome_"+outcome["status"])
        return {**outcome, "key": key}

    def tick(self):
        """Deployment timer; no candidate/source event is required."""
        checked = invalidated = 0
        try:
            spec = self.spec_loader()
        except (OSError, ValueError, RuntimeError):
            for item in self._rows():
                try:
                    self.workflows.invalidate(item["run_id"], "installation_context_unavailable")
                    checked += 1
                    invalidated += 1
                except KeyError:
                    continue
            return {"checked": checked, "invalidated": invalidated}
        for item in self._rows():
            if item["transition_id"] != spec.transition_id:
                continue
            row = self.runs.get(item["run_id"])
            fresh, reason = self._fresh(row, spec)
            self._workflow(row, spec, fresh, reason)
            checked += 1
            if not fresh:
                invalidated += 1
        return {"checked": checked, "invalidated": invalidated}
