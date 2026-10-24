"""Offline doubles. The fake protocol stands in for the 2A executor so runner,
ledger and scorer logic can be tested without agent_graph; it is never used live."""
from __future__ import annotations

import json
import os
import time

from tools.autonomous_mvp import program as program_mod
from tools.autonomous_mvp.protocol import ClaimRecord, StepOutcome, ref_digest

POSIX_CORE = hasattr(os, "O_DIRECTORY")
try:
    import fcntl  # noqa: F401
except ImportError:
    POSIX_CORE = False


class FakeSession:
    def __init__(self, protocol, case):
        self.protocol, self.case = protocol, case

    def initial_messages(self, remaining_steps):
        return [dict(role="system", content="fake"), dict(role="user", content=self.case["case_id"])]

    def response_format(self):
        return dict(type="json_schema", json_schema=dict(name="fake", strict=True, schema={}))

    def step(self, content, *, remaining_steps):
        self.protocol.seen.append(content)
        data = json.loads(content)
        msgs = [dict(role="assistant", content=content), dict(role="user", content="ok")]
        if data["action"] == "read":
            return StepOutcome(action="read_source", valid=True, tool=dict(source_id="s"), messages=msgs)
        if data["action"] == "propose":
            claims = [ClaimRecord(claim=c["claim"], kind=c.get("kind", "dependency"),
                                  ref_digests=[ref_digest(r) for r in c.get("refs", ["issued"])],
                                  provenance=c.get("provenance", "AUTHENTIC_AUTHORIZED_CURRENT"),
                                  sufficiency="SUPPORTED_WITHIN_PROFILE", admitted=c.get("admitted", True),
                                  confidence=c.get("confidence", "CONFIRMED_WITHIN_PROFILE")) for c in data["claims"]]
            return StepOutcome(action="propose", valid=True, claims=claims, messages=msgs)
        if data["action"] == "finish":
            return StepOutcome(action="finish", valid=True, terminal=data.get("terminal", "FINISHED"),
                               final=data.get("final"), messages=msgs)
        return StepOutcome(action="<unparsed>", valid=False, layer="schema", reason_code="schema_violation",
                           field_path="/action", expected_type="literal_error", messages=msgs)

    def close(self):
        self.protocol.closed += 1


class FakeProtocol:
    protocol_id = "fake-test-protocol"
    interim = False
    capabilities = frozenset(("status", "abstain_reason", "unknowns", "impact", "hypothesis", "search"))

    def __init__(self):
        self.seen, self.closed = [], 0

    def open_case(self, case, repos, work, *, deadline_passed):
        return FakeSession(self, case)


def act(action, **extra):
    return json.dumps(dict(action=action, **extra))


def claim(consumer, provider="orders", path="/orders"):
    return dict(consumer_repository=consumer, consumer_service=consumer, provider_service=provider,
                method="GET", path_template=path)


def small_program(**phase_overrides):
    """The real 2b-r1 program with a one-model, small-phase shape for tests."""
    _, program, cases = program_mod.load()
    program = json.loads(json.dumps(program))
    program["models"] = [program["models"][0]]
    for name, values in phase_overrides.items():
        program["phases"][name].update(values)
    return program, cases


class Clock:
    """Wall and monotonic clocks advanced together by tests."""

    def __init__(self):
        self.offset = 0.0

    def wall(self):
        return time.time() + self.offset

    def mono(self):
        return time.monotonic() + self.offset
