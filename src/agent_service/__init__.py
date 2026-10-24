"""Autonomous Jira/PR service: transport, durable queue and publication.

The analysis itself lives in ``agent_graph``; this package only receives
events, keeps one durable queue per installation, calls the analysis through
``agent_service.analysis`` and keeps one updatable comment per resource.
"""

from .envelope import EVENT_SCHEMA, INTENT_SCHEMA, EventEnvelope, PublicationIntent

__all__ = ["EVENT_SCHEMA", "INTENT_SCHEMA", "EventEnvelope", "PublicationIntent"]
