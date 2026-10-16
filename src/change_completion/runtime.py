"""Internal bounded SQL transition runner; no production or GitHub effects."""
from datetime import datetime, timezone
import difflib
import json
import sqlite3
import time
from pathlib import Path
from typing import Callable

from pydantic import Field, StrictInt, model_validator

from .adapters import discover_repository, read_repository_file
from .executor import execute_select
from .models import Action, ContentRef, Contract, TransitionSpec
from .providers import PatchProvider, WindowPatchProvider
from .store import RunStore
from .verification import ExpectationSuite, TrustPolicy, context_digest, digest_bytes, load_json, verify_observations

RUNTIME_VERSION = "sql-window-runtime/1"


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


class WindowTarget(Contract):
    component_id: str
    path: str
    old_window: StrictInt = Field(ge=1, le=36500)
    new_window: StrictInt = Field(ge=1, le=36500)


class WindowIntent(Contract):
    profile: str = Field(pattern=r"^sql-window/1$")
    targets: tuple[WindowTarget, ...] = Field(min_length=1, max_length=10)

    @model_validator(mode="after")
    def unique(self):
        if (len({t.component_id for t in self.targets}) != len(self.targets)
                or len({t.path for t in self.targets}) != len(self.targets)):
            raise ValueError("duplicate targets")
        return self


def utc_now():
    return datetime.now(timezone.utc)


def _granted(spec, policy, actor, component, action, at):
    return action in spec.allowed_actions and any(
        g.grant_id not in policy.revoked_grant_ids and g.actor == actor
        and g.environment == spec.environment and component in g.component_ids
        and action in g.actions and g.starts_at <= at < g.expires_at for g in policy.grants)


def run_transition(repository: Path, spec: TransitionSpec, suite_bytes: bytes,
                   fixture_loader: Callable[[str], bytes], policy_loader: Callable[[], TrustPolicy],
                   store: RunStore, *, actor: str, provider: PatchProvider | None = None,
                   clock: Callable[[], datetime] = utc_now) -> dict:
    """Capture exact approved bytes, prepare, execute and persist a review package.

    Roots, clock, policy_loader, fixture_loader and provider are deployment-owned.
    A terminal cache is reused only after fresh inputs/authority are validated.
    """
    provider = provider or WindowPatchProvider()
    deadline = time.monotonic() + 60
    repository = Path(repository)
    run_id = None
    result = {"runtime": RUNTIME_VERSION, "transition_id": spec.transition_id,
              "status": "STOP", "effects_authorized": False, "reason_codes": [],
              "scope": "declared_local_snapshot_and_restricted_sql"}

    def require(condition, reason):
        if not condition:
            raise ValueError(reason)

    try:
        now = clock()
        require(now.utcoffset() is not None, "invalid_runtime_clock")
        require(spec.environment.lower() not in {"prod", "production"}, "test_environment_required")
        require(not spec.unknowns and all(d.certainty == "observed" for d in spec.dependencies), "unresolved_scope")
        require(all(n.capability.action in {Action.DISCOVER, Action.PATCH, Action.VERIFY, Action.EXPORT}
                    and n.capability.artifact_kind in {"source", "source_code", "query", "observable_result"}
                    for n in spec.needs), "unsupported_requested_capability")
        suite = ExpectationSuite.model_validate(load_json(suite_bytes))
        suite_hash = digest_bytes(suite_bytes)
        policy = policy_loader()
        require(suite_hash in policy.approved_suite_digests and suite.approved_by in policy.approved_owners, "unapproved_expectations")
        require(suite.transition_id == spec.transition_id and suite.context_sha256 == context_digest(spec), "stale_suite_context")
        require(suite.prepared_at < now < suite.valid_until, "expired_or_future_suite")
        require(len(suite.cases) >= policy.minimum_cases and len({c.case_id for c in suite.cases}) == len(suite.cases), "incomplete_case_set")
        require({"normal", "boundary"} <= {tag for c in suite.cases for tag in c.tags}, "missing_profile_case_classes")
        require(set(suite.required_tags) <= {tag for c in suite.cases for tag in c.tags}, "missing_required_tags")
        require({r for c in suite.cases for r in c.requirement_ids} == {r.requirement_id for r in spec.requirements}, "incomplete_requirements")
        requirement_owner = {r.requirement_id: r.consumer_id for r in spec.requirements}
        require(all(len({requirement_owner[r] for r in c.requirement_ids}) == 1 for c in suite.cases), "ambiguous_case_consumer")
        for consumer in spec.consumers:
            tags = {tag for c in suite.cases if consumer in {requirement_owner[r] for r in c.requirement_ids} for tag in c.tags}
            require({"normal", "boundary"} <= tags, "missing_consumer_case_classes")
        for component in spec.components:
            require(component.profile in {"fixture-source/1", "sqlite-select/1"}, "unsupported_component_profile")
            for action in (Action.DISCOVER,):
                require(_granted(spec, policy, actor, component.component_id, action, now), "discovery_authority_unavailable")
        discovery = discover_repository(repository)
        static_limit = "static_snapshot_only_runtime_consumers_unknown"
        require(not [g for g in discovery["gaps"] if g != static_limit], "incomplete_static_discovery")
        # The unavoidable runtime-consumer gap is retained in every result.
        result["coverage_limits"] = discovery["gaps"]
        captured = {}
        refs = [spec.before, spec.target, *[c for component in spec.components for c in component.artifacts],
                *[r.basis for r in spec.requirements], *[d.basis for d in spec.dependencies if d.basis]]
        for ref in refs:
            content = read_repository_file(repository, ref.uri)
            require(digest_bytes(content) == ref.sha256, "snapshot_digest_mismatch")
            captured[ref.uri] = content
        discovered_hashes = {f["path"]: f["sha256"] for f in discovery["files"]}
        require(all(discovered_hashes.get(k) == digest_bytes(v) for k, v in captured.items()), "source_changed_after_discovery")
        intent = WindowIntent.model_validate(load_json(captured[spec.target.uri]))
        require({t.component_id for t in intent.targets} == set(spec.consumers), "target_consumer_mismatch")
        by_component = {c.component_id: c for c in spec.components}
        by_path = {t.path: t.component_id for t in intent.targets}
        sql_files = {f["path"] for f in discovery["files"] if f["path"].endswith(".sql")}
        require(sql_files == set(by_path), "unregistered_sql_consumer")
        declared_edges = {(d.source, d.target) for d in spec.dependencies}
        require({(e["source"], by_path[e["target"]]) for e in discovery["dependencies"]} == declared_edges, "dependency_mismatch")
        for target in intent.targets:
            require(target.path in {r.uri for r in by_component[target.component_id].artifacts}, "target_outside_component")
            require(target.path in captured, "missing_target_snapshot")
            for action in (Action.VERIFY, Action.EXPORT, *([Action.PATCH] if target.old_window != target.new_window else [])):
                require(_granted(spec, policy, actor, target.component_id, action, now), "action_authority_unavailable")
        fixture_bytes = {}
        source_schemas = {}
        for component in spec.components:
            if component.profile == "fixture-source/1":
                require(len(component.artifacts) == 1, "ambiguous_source_schema")
                descriptor = load_json(captured[component.artifacts[0].uri])
                require(set(descriptor) == {"table", "columns"} and descriptor["table"] == component.component_id,
                        "invalid_source_descriptor")
                source_schemas[descriptor["table"]] = descriptor["columns"]
        for case in suite.cases:
            content = fixture_loader(case.fixture.uri)
            require(type(content) is bytes and digest_bytes(content) == case.fixture.sha256, "fixture_digest_mismatch")
            fixture = load_json(content)
            require(type(fixture.get("tables")) is dict, "invalid_fixture")
            require(fixture.get("schemas") == source_schemas, "fixture_source_schema_mismatch")
            require(sum(len(rows) for rows in fixture["tables"].values()) == case.input_records, "fixture_count_mismatch")
            fixture_bytes[case.case_id] = content
        runtime_revision = digest_bytes(encode({name: digest_bytes(Path(__file__).with_name(name).read_bytes())
                                               for name in ("runtime.py", "executor.py", "sql_worker.py", "comparison.py", "verification.py", "adapters.py", "providers.py", "models.py")}))
        fingerprint = digest_bytes(encode({"runtime": RUNTIME_VERSION, "runtime_revision": runtime_revision, "context": context_digest(spec),
                                          "suite": suite_hash, "provider": provider.identity,
                                          "snapshot": {k: digest_bytes(v) for k, v in captured.items()},
                                          "inventory": discovery,
                                          "fixtures": {k: digest_bytes(v) for k, v in fixture_bytes.items()}}))
        claimed = store.claim(spec.transition_id, fingerprint)
        run_id = claimed["run_id"]
        if not claimed["claimed"]:
            previous = store.get(run_id)
            if previous["status"] == "RUNNING":
                result.update(run_id=run_id, reason_codes=["RUN_ALREADY_RUNNING_REQUIRES_REVIEW"])
                return result
            require(previous["result"] is not None, "missing_cached_result")
            result = previous["result"]
            require(result.get("context_sha256") == context_digest(spec), "cached_context_mismatch")
            if result["status"] == "READY_FOR_REVIEW":
                saved = result.get("patches", {})
                require(set(saved) == set(spec.consumers), "cached_patch_set_mismatch")
                require(all(digest_bytes(p["candidate"].encode()) == p["sha256"] for p in saved.values()), "cached_candidate_digest_mismatch")
                candidate = ContentRef(uri="runtime://"+run_id+"/candidate", sha256=digest_bytes(encode(saved)))
                require(candidate.sha256 == result.get("candidate_sha256"), "cached_bundle_digest_mismatch")
                fresh = verify_observations(spec, candidate, suite_bytes, encode(result["observations"]), policy_loader(), at=clock(), actor=actor)
                require(fresh.status == "PASS", "cached_verification_no_longer_valid")
                require(all(_granted(spec, policy_loader(), actor, t.component_id, Action.EXPORT, clock()) for t in intent.targets), "cached_export_authority_unavailable")
                result = {**result, "verification": fresh.model_dump(mode="json"), "revalidated_at": clock().isoformat()}
            return {**result, "reused": True}
        result.update(run_id=run_id, context_sha256=context_digest(spec), runtime_revision=runtime_revision, reused=False)
        store.append(run_id, "DISCOVERED", {"files": discovery["files"], "dependencies": discovery["dependencies"], "coverage_limits": discovery["gaps"]})
        proposals = {}
        created = clock()
        for target in intent.targets:
            require(time.monotonic() < deadline, "run_budget_exceeded")
            source = captured[target.path].decode("utf-8")
            if target.old_window == target.new_window:
                proposed = source
            else:
                # Repeat permissions immediately before invoking a proposal provider.
                require(_granted(spec, policy_loader(), actor, target.component_id, Action.PATCH, clock()), "patch_authority_revoked")
                proposal = provider.propose(source, old_window=target.old_window, new_window=target.new_window)
                require(proposal.get("status") == "prepared" and type(proposal.get("candidate")) is str, "patch_provider_unavailable_or_unsupported")
                proposed = proposal["candidate"]
            require(len(proposed.encode()) <= 65_536, "candidate_size_limit")
            diff = "".join(difflib.unified_diff(source.splitlines(True), proposed.splitlines(True), fromfile="a/"+target.path, tofile="b/"+target.path))
            proposals[target.component_id] = {"path": target.path, "source_sha256": digest_bytes(source.encode()),
                                              "candidate": proposed, "sha256": digest_bytes(proposed.encode()), "diff": diff}
        candidate_bytes = encode(proposals)
        require(len(candidate_bytes) <= 500_000, "candidate_bundle_limit")
        candidate = ContentRef(uri="runtime://"+run_id+"/candidate", sha256=digest_bytes(candidate_bytes))
        store.append(run_id, "PREPARED", {"candidate_sha256": candidate.sha256, "provider": provider.identity})
        requirement_owner = {r.requirement_id: r.consumer_id for r in spec.requirements}
        observations = []
        receipts = []
        for case in suite.cases:
            require(time.monotonic() < deadline, "run_budget_exceeded")
            owners = {requirement_owner[r] for r in case.requirement_ids}
            require(len(owners) == 1, "ambiguous_case_consumer")
            consumer = next(iter(owners))
            require(_granted(spec, policy_loader(), actor, consumer, Action.VERIFY, clock()), "verify_authority_revoked")
            output = execute_select(proposals[consumer]["candidate"], load_json(fixture_bytes[case.case_id]))
            observations.append({"case_id": case.case_id, "fixture": case.fixture.model_dump(),
                                 "status": output["status"], "actual": output.get("actual")})
            receipts.append({"case_id": case.case_id, "component_id": consumer,
                             "sql_sha256": proposals[consumer]["sha256"], "fixture_sha256": case.fixture.sha256,
                             "output_sha256": digest_bytes(encode(output)), "executor": "sqlite-readonly-subprocess/1"})
        captured_at = clock()
        require(time.monotonic() < deadline, "run_budget_exceeded")
        observation_bytes = encode({"format": "captured-observations/1", "transition_id": spec.transition_id,
                                    "context_sha256": context_digest(spec), "candidate_sha256": candidate.sha256,
                                    "suite_sha256": suite_hash, "candidate_created_at": created.isoformat(),
                                    "captured_at": captured_at.isoformat(), "cases": observations})
        report = verify_observations(spec, candidate, suite_bytes, observation_bytes, policy_loader(), at=clock(), actor=actor)
        result.update(candidate_sha256=candidate.sha256, receipts=receipts,
                      verification=report.model_dump(mode="json"))
        store.append(run_id, "VERIFIED", {"status": report.status, "observations_sha256": digest_bytes(observation_bytes)})
        require(all(read_repository_file(repository, k) == v for k, v in captured.items()), "source_changed_during_run")
        require(all(fixture_loader(c.fixture.uri) == fixture_bytes[c.case_id] for c in suite.cases), "fixture_changed_during_run")
        require(discover_repository(repository) == discovery, "repository_inventory_changed_during_run")
        for target in intent.targets:
            require(_granted(spec, policy_loader(), actor, target.component_id, Action.EXPORT, clock()), "export_authority_revoked")
        fresh = verify_observations(spec, candidate, suite_bytes, observation_bytes, policy_loader(), at=clock(), actor=actor)
        require(fresh.status == report.status, "verification_authority_or_time_changed")
        result["status"] = "READY_FOR_REVIEW" if report.status == "PASS" else report.status
        result["reason_codes"] = [] if report.status == "PASS" else ["verification_"+report.status.lower()]
        result["completion_conditions"] = ["acceptor reviews patch and known coverage limits", "production switch/retirement requires separate mandate"]
        if result["status"] == "READY_FOR_REVIEW":
            result.update(patches=proposals, observations=json.loads(observation_bytes))
        store.finish(run_id, result["status"], result)
        return result
    except (OSError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, RuntimeError, sqlite3.Error) as error:
        # Exceptions never carry source data or credentials into the public result.
        code = str(error) if type(error) is ValueError and str(error).replace("_", "").isalnum() else "runtime_input_or_execution_unavailable"
        result.update(status="STOP", reason_codes=[code])
        result.pop("patches", None)
        result.pop("observations", None)
        if run_id is not None:
            # A cached result is immutable: this path records no altered finish.
            existing = store.get(run_id)
            if existing["status"] == "RUNNING":
                store.finish(run_id, "STOP", result)
        return result
