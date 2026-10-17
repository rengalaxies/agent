"""Pure declaration assessment. Never executes tools or authorizes an effect.

Qualification records and grants are untrusted inputs until a future deployment
verifies their issuers, scope and freshness. Even a covered plan is NOT_EXECUTED.
"""
from datetime import datetime
from typing import Literal

from pydantic import Field

from .models import Action, AdapterDeclaration, Contract, TransitionSpec


class Blocker(Contract):
    code: str
    subject: str
    detail: str


class Assessment(Contract):
    transition_id: str
    coverage: str = Field(pattern=r"^(blocked|declared_coverage)$")
    execution: Literal["NOT_EXECUTED"] = "NOT_EXECUTED"
    blockers: tuple[Blocker, ...]
    effects_authorized: Literal[False] = False


def assess_declarations(spec: TransitionSpec, adapters: tuple[AdapterDeclaration, ...], *, at: datetime, actor: str) -> Assessment:
    if at.utcoffset() is None:
        raise ValueError("assessment time requires timezone")
    if len({a.adapter_id for a in adapters}) != len(adapters):
        raise ValueError("duplicate adapter_id")
    blockers = []

    def block(code, subject, detail):
        blockers.append(Blocker(code=code, subject=subject, detail=detail))

    for unknown in spec.unknowns:
        block("UNKNOWN_SCOPE", spec.transition_id, unknown)
    for edge in spec.dependencies:
        if edge.certainty != "observed":
            block("UNCONFIRMED_DEPENDENCY", f"{edge.source}:{edge.target}", edge.certainty)
    for need in spec.needs:
        capable = any(a.status == "qualified" and need.capability in a.capabilities for a in adapters)
        if not capable:
            block("MISSING_QUALIFIED_CAPABILITY", need.component_id, f"{need.capability.action}:{need.capability.profile}:{need.capability.artifact_kind}")
        if need.capability.action not in spec.allowed_actions:
            block("ACTION_OUTSIDE_MANDATE", need.component_id, need.capability.action)
        if not any(g.actor == actor and g.environment == spec.environment and g.starts_at <= at < g.expires_at
                   and need.component_id in g.component_ids and need.capability.action in g.actions
                   for g in spec.grants):
            block("MISSING_CURRENT_GRANT", need.component_id, need.capability.action)
        # Inspecting a production snapshot is distinct from changing production.
        if need.capability.action in (Action.DEPLOY, Action.RETIRE) or (
            spec.environment.lower() in ("prod", "production") and need.capability.action in (Action.PATCH,)
        ):
            block("EFFECT_NOT_IMPLEMENTED", need.component_id, "package 1 has no effect executor")
    return Assessment(transition_id=spec.transition_id,
                      coverage="blocked" if blockers else "declared_coverage",
                      blockers=tuple(blockers))
