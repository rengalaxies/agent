from __future__ import annotations

import hashlib
import json

from .models import (
    ChangeProposal,
    Decision,
    ProtocolState,
    ReleaseDecision,
    Scenario,
    ValidationMode,
)
from .validators import validate


def scenario_snapshot_id(scenario: Scenario) -> str:
    payload = {
        "old_contract": scenario.old_contract.model_dump(mode="json"),
        "new_contract": scenario.new_contract.model_dump(mode="json"),
        "obligations": [item.model_dump(mode="json") for item in scenario.obligations],
        "baseline_rules": [item.model_dump(mode="json") for item in scenario.baseline_rules],
        "migrations": [item.model_dump(mode="json") for item in scenario.migrations],
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def finalize(decisions: list[Decision]) -> Decision:
    if not decisions:
        return Decision.NEEDS_REVIEW
    if Decision.REJECT in decisions:
        return Decision.REJECT
    if Decision.NEEDS_REVIEW in decisions:
        return Decision.NEEDS_REVIEW
    return Decision.ACCEPT


class ReleaseEngine:
    def run(self, scenario: Scenario, mode: ValidationMode, run_id: str) -> ReleaseDecision:
        trace = [ProtocolState.RECEIVED]
        snapshot_id = scenario_snapshot_id(scenario)
        trace.append(ProtocolState.SNAPSHOT_LOCKED)
        proposal = ChangeProposal(
            proposal_id=f"{run_id}:{scenario.scenario_id}:{mode.value}",
            run_id=run_id,
            scenario_id=scenario.scenario_id,
            mode=mode,
            product_id=scenario.new_contract.product_id,
            old_contract_version=scenario.old_contract.contract_version,
            new_contract_version=scenario.new_contract.contract_version,
            snapshot_id=snapshot_id,
        )
        local_verdicts = validate(scenario, mode)
        trace.extend([ProtocolState.LOCALLY_VALIDATED, ProtocolState.NEGOTIATING])
        decision = finalize([verdict.decision for verdict in local_verdicts])
        trace.append(ProtocolState.DECIDED)
        terminal = {
            Decision.ACCEPT: ProtocolState.COMMITTED,
            Decision.REJECT: ProtocolState.QUARANTINED,
            Decision.NEEDS_REVIEW: ProtocolState.ESCALATED,
        }[decision]
        trace.append(terminal)
        reason_codes = sorted(
            {
                check.reason_code
                for local_verdict in local_verdicts
                for consumer_verdict in local_verdict.consumer_verdicts
                for check in consumer_verdict.checks
                if check.outcome != "TRUE"
            }
        )
        return ReleaseDecision(
            proposal=proposal,
            decision=decision,
            terminal_state=terminal,
            local_verdicts=local_verdicts,
            reason_codes=reason_codes,
            state_trace=trace,
        )
