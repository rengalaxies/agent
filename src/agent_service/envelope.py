"""Versioned event and publication contracts (spec section 5).

An envelope never carries the raw payload: only identifiers the connector
re-fetches with its own credentials, plus a digest of the signed body.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

EVENT_SCHEMA = "agent-service-event/1"
INTENT_SCHEMA = "agent-service-intent/1"

Provider = Literal["github", "jira"]
EventState = Literal["RECEIVED", "INGESTED", "COALESCED", "IGNORED", "FAILED"]
JobState = Literal["QUEUED", "RUNNING", "ANALYZED", "DONE", "SUPERSEDED", "FAILED", "CLOSED"]
IntentKind = Literal["result", "stale", "failure"]
IntentState = Literal["PENDING", "SENDING", "UNKNOWN", "DELIVERED", "SUPERSEDED", "BLOCKED", "FAILED"]


def canonical(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    data = value if isinstance(value, bytes) else canonical(value).encode()
    return hashlib.sha256(data).hexdigest()


def iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EventEnvelope(Strict):
    """One provider delivery. ``event_id`` is the delivery, not the resource version."""

    schema_version: Literal["agent-service-event/1"] = EVENT_SCHEMA
    provider: Provider
    source: str = Field(min_length=1, max_length=200)  # owner/repo or Jira project key
    event_id: str = Field(min_length=1, max_length=200)  # X-GitHub-Delivery / X-Atlassian-Webhook-Identifier
    event_kind: str = Field(min_length=1, max_length=100)
    resource_id: str = Field(min_length=1, max_length=300)
    # Version claimed by the signed payload. Only a hint: ingestion re-fetches
    # the resource and uses the fetched version, so reordered deliveries are safe.
    resource_version_hint: str | None = Field(default=None, max_length=200)
    payload_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    received_at: float
    # Set when the delivery is known to need no analysis (comments, pings).
    ignored_reason: str | None = Field(default=None, max_length=100)


class PublicationIntent(Strict):
    """Durable right to write one comment body for one resource generation."""

    schema_version: Literal["agent-service-intent/1"] = INTENT_SCHEMA
    intent_id: str
    resource_id: str
    generation: int = Field(ge=1)
    resource_version: str
    kind: IntentKind
    result_digest: str | None
    body_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    marker: str = Field(pattern=r"^[0-9a-f]{16}$")
    comment_id: str | None = None
    state: IntentState
    attempts: int = Field(ge=0)
    not_before: float
    reason: str | None = None
