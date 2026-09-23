"""E4: isolated domain workers and a conservative event collector."""

from __future__ import annotations

import hashlib
import json
import multiprocessing as mp
import queue
import time
from dataclasses import dataclass, field

from .engine import finalize, scenario_snapshot_id
from .models import BaselinePolicy, Decision, LocalVerdict, Scenario, ValidationMode
from .validators import validate


def _digest(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


@dataclass
class EventCollector:
    proposal_id: str
    snapshot_id: str
    expected_domains: frozenset[str]
    received: dict[str, LocalVerdict] = field(default_factory=dict)
    duplicates: int = 0
    invalid: int = 0
    conflicts: set[str] = field(default_factory=set)

    def ingest(self, event: dict) -> None:
        if event.get("proposal_id") != self.proposal_id or event.get("snapshot_id") != self.snapshot_id:
            self.invalid += 1
            return
        domain = event.get("domain_id")
        if domain not in self.expected_domains:
            self.invalid += 1
            return
        try:
            verdict = LocalVerdict.model_validate(event["verdict"])
        except (KeyError, ValueError):
            self.invalid += 1
            return
        if verdict.domain_id != domain or event.get("event_id") != _digest({
            "proposal_id": self.proposal_id, "snapshot_id": self.snapshot_id,
            "domain_id": domain, "verdict": verdict.model_dump(mode="json"),
        }):
            self.invalid += 1
            return
        if domain in self.received:
            if self.received[domain] == verdict:
                self.duplicates += 1
            else:
                self.conflicts.add(domain)
            return
        self.received[domain] = verdict

    @property
    def decision(self) -> Decision:
        if self.conflicts:
            return Decision.NEEDS_REVIEW
        # A known rejection remains decisive even when another domain is unavailable.
        if any(item.decision == Decision.REJECT for item in self.received.values()):
            return Decision.REJECT
        if self.expected_domains - self.received.keys():
            return Decision.NEEDS_REVIEW
        return finalize([item.decision for item in self.received.values()])


def _worker(domain: str, scenario_json: dict, policy_json: dict, mode: str,
            proposal_id: str, snapshot_id: str, out: mp.Queue, delay_s: float) -> None:
    scenario = Scenario.model_validate(scenario_json)
    policy = BaselinePolicy.model_validate(policy_json)
    verdict = validate(scenario, ValidationMode(mode), policy)[0]
    payload = {"proposal_id": proposal_id, "snapshot_id": snapshot_id,
               "domain_id": domain, "verdict": verdict.model_dump(mode="json")}
    payload["event_id"] = _digest(payload)
    if delay_s:
        time.sleep(delay_s)
    out.put(payload)


def run_distributed(scenario: Scenario, policy: BaselinePolicy, *,
                    mode: ValidationMode = ValidationMode.V2, timeout_s: float = 0.5,
                    delays: dict[str, float] | None = None,
                    unavailable: frozenset[str] = frozenset(),
                    duplicate: bool = False, reverse: bool = False) -> dict:
    """One process per consumer domain; a timeout is an escalation, never acceptance."""
    domains = frozenset(item.consumer_domain for item in scenario.obligations)
    if len(domains) < 2 or timeout_s <= 0 or unavailable - domains:
        raise ValueError("expected at least two domains, positive timeout, known unavailable domains")
    proposal_id = f"E4:{scenario.scenario_id}:{mode.value}"
    snapshot_id = scenario_snapshot_id(scenario)
    collector = EventCollector(proposal_id, snapshot_id, domains)
    ctx = mp.get_context("spawn")
    out = ctx.Queue()
    workers = [ctx.Process(target=_worker, args=(domain, scenario.model_copy(update={
                   "obligations": [item for item in scenario.obligations if item.consumer_domain == domain],
               }).model_dump(mode="json"),
               policy.model_dump(mode="json"), mode.value, proposal_id, snapshot_id, out,
               (delays or {}).get(domain, 0))) for domain in sorted(domains - unavailable)]
    start = time.monotonic()
    try:
        for worker in workers:
            worker.start()
        events: list[dict] = []
        deadline = start + timeout_s
        while len(events) < len(workers):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                events.append(out.get(timeout=remaining))
            except queue.Empty:
                break
        for event in reversed(events) if reverse else events:
            collector.ingest(event)
            if duplicate:
                collector.ingest(event)
    finally:
        for worker in workers:
            if worker.is_alive():
                worker.terminate()
            worker.join(timeout=1)
        out.close()
        out.join_thread()
    return {"scenario_id": scenario.scenario_id, "mode": mode.value,
            "proposal_id": proposal_id, "snapshot_id": snapshot_id,
            "expected_domains": sorted(domains), "received_domains": sorted(collector.received),
            "missing_domains": sorted(domains - collector.received.keys()),
            "decision": collector.decision.value, "duplicates": collector.duplicates,
            "invalid_events": collector.invalid, "conflicts": sorted(collector.conflicts),
            "elapsed_ms": round((time.monotonic() - start) * 1000, 2),
            "worker_exitcodes": {domain: worker.exitcode for domain, worker in zip(sorted(domains - unavailable), workers)}}
