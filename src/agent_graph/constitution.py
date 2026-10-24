"""Versioned service constitution, validated before any model call.

The file is operator configuration. A constitution that omits a forbidden
capability, names an action the executor does not implement, removes a finite
limit or maps an outcome to an invalid status/reason is rejected, not repaired.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

from pydantic import Field, ValidationError, model_validator
import yaml

from .contracts import GraphError, Strict, canonical
from .output_contracts import REASONS

ACTIONS = ("list_sources", "search", "list_symbols", "read_source", "graph_query",
           "graph_find", "graph_neighbors", "graph_impact", "graph_relationship", "graph_owner",
           "propose_dependency", "propose_hypothesis", "finish")
FORBIDDEN = frozenset({"shell", "network_fetch", "write_source", "publish", "grant_access",
                       "approve_requirement", "confirm_hypothesis", "change_constitution"})
OUTCOMES = ("supported_dependency", "hypotheses_only", "abstained", "step_limit", "deadline", "budget",
            "transport_failure", "invalid_actions", "cancelled")
DEFAULT_PATH = Path(__file__).resolve().parents[2] / "constitutions" / "agent-service-v1.yaml"


class ActionLimits(Strict):
    max_results: int | None = Field(default=None, ge=1, le=500)
    max_query_chars: int | None = Field(default=None, ge=1, le=500)
    max_snippet_chars: int | None = Field(default=None, ge=1, le=1000)
    max_lines: int | None = Field(default=None, ge=1, le=200)
    max_evidence_refs: int | None = Field(default=None, ge=1, le=16)
    max_statement_chars: int | None = Field(default=None, ge=1, le=2000)
    max_depth: int | None = Field(default=None, ge=1, le=3)


class Sources(Strict):
    scope: Literal["request_snapshot"]
    model_supplied_urls: Literal[False]
    model_supplied_paths: Literal[False]
    model_supplied_refs: Literal[False]


class Publication(Strict):
    model_may_publish: Literal[False]


class EvidenceRules(Strict):
    quote_proves_meaning: Literal[False]
    hypothesis_promotion: Literal["never_automatic"]


class Limits(Strict):
    max_steps: int = Field(ge=1, le=50)
    max_seconds: float = Field(gt=0, le=900)
    max_reads: int = Field(ge=1, le=200)
    max_proposals: int = Field(ge=1, le=50)
    max_invalid_actions: int = Field(ge=0, le=5)


class Outcome(Strict):
    status: Literal["USEFUL", "PARTIAL", "ABSTAINED", "FAILED", "SUPERSEDED"]
    reason: str

    @model_validator(mode="after")
    def known(self):
        if self.reason not in REASONS[self.status]:
            raise ValueError("outcome_reason_not_allowed")
        return self


class Constitution(Strict):
    constitution: Literal["agent-service"]
    version: Literal["1.0"]
    actions: dict[str, ActionLimits]
    forbidden: list[str]
    sources: Sources
    publication: Publication
    evidence: EvidenceRules
    limits: Limits
    outcomes: dict[str, Outcome]

    @model_validator(mode="after")
    def complete(self):
        if not set(self.actions) <= set(ACTIONS) or "finish" not in self.actions or "read_source" not in self.actions:
            raise ValueError("unknown_or_missing_action")
        if set(self.forbidden) != FORBIDDEN:
            raise ValueError("forbidden_capabilities_changed")
        if set(self.outcomes) != set(OUTCOMES):
            raise ValueError("outcomes_incomplete")
        if self.outcomes["supported_dependency"].status != "USEFUL" or any(
                o.status == "USEFUL" for k, o in self.outcomes.items() if k != "supported_dependency"):
            raise ValueError("only_supported_dependency_is_useful")
        return self

    def limit(self, action, name, default):
        value = getattr(self.actions[action], name) if action in self.actions else None
        return default if value is None else value


def load(path=None) -> tuple[Constitution, str]:
    """Return the validated constitution and its version id (name, version, content digest)."""
    raw = Path(path or DEFAULT_PATH).read_bytes()
    try:
        data = yaml.safe_load(raw.decode("utf-8"))
        value = Constitution.model_validate(data)
    except (UnicodeError, yaml.YAMLError, ValidationError):
        raise GraphError("invalid_constitution") from None
    digest = hashlib.sha256(canonical(value.model_dump()).encode()).hexdigest()
    return value, f"{value.constitution}-v{value.version}:{digest[:12]}"
