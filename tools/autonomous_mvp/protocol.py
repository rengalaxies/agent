"""Thin adapter between the 2B runner and an action protocol.

The runner, ledger and scorer only see the normalized records defined here.
Which actions exist, how they are validated and what the executor admits belong
to the protocol (batch 2A). Two adapters are registered:

* `evidence-refs-v2-interim` wraps the protocol already on main
  (`agent_graph.evidence_refs`, read_source/propose/finish). It can exercise the
  transport and the loop now, but it cannot express abstention reasons,
  unknowns, impact or hypotheses beyond the static grammar.
* `agent-service-v1` is the 2A protocol. It is not integrated yet and refuses to
  open a case, so no evaluation can silently run on the interim protocol.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import hashlib
import json
from pathlib import Path

CONFIDENCE = ("NOT_ADMITTED", "CANDIDATE", "CONFIRMED_WITHIN_PROFILE")
LAYERS = ("json", "schema", "field_combination", "tool_admissibility", "evidence", "completion")
CAPABILITIES = ("status", "abstain_reason", "unknowns", "impact", "hypothesis", "search")


class ProtocolUnavailable(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


@dataclass
class ClaimRecord:
    claim: dict
    kind: str  # "dependency" (static profile) or "hypothesis"
    ref_digests: list = field(default_factory=list)  # sha256 of every evidence_ref string offered
    provenance: str = "NOT_ASSESSED"  # AUTHENTIC_AUTHORIZED_CURRENT | REJECTED | NOT_ASSESSED
    provenance_reason: str | None = None
    sufficiency: str = "NOT_ASSESSED"  # SUPPORTED_WITHIN_PROFILE | INSUFFICIENT | NOT_ASSESSED
    admitted: bool = False
    confidence: str = "NOT_ADMITTED"


@dataclass
class StepOutcome:
    action: str  # allowlisted action name, or "<unparsed>"
    valid: bool
    layer: str | None = None
    reason_code: str | None = None
    field_path: str | None = None
    expected_type: str | None = None
    tool: dict | None = None
    claims: list = field(default_factory=list)
    terminal: str | None = None  # None, "FINISHED" or "ABSTAINED"
    final: dict | None = None  # status/reason_code/unknowns/impact when the protocol supports them
    messages: list = field(default_factory=list, repr=False)  # appended to the dialogue, never persisted

    def safe(self):
        data = asdict(self)
        data.pop("messages")
        data["claims"] = [asdict(c) if isinstance(c, ClaimRecord) else c for c in self.claims]
        return data


def ref_digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def _schema_fields(schema):
    names = set()

    def visit(node):
        if isinstance(node, dict):
            names.update(node.get("properties", {}))
            for v in node.values():
                visit(v)
        elif isinstance(node, list):
            for v in node:
                visit(v)
    visit(schema)
    return names


def safe_field_path(loc, allowed):
    """A validator location may contain model-chosen keys; keep only schema names and indexes."""
    parts = []
    for item in loc:
        if type(item) is int:
            parts.append(str(item))
        elif isinstance(item, str) and item in allowed:
            parts.append(item)
        else:
            parts.append("<extra>")
    return "/" + "/".join(parts)


class ActionProtocol:
    protocol_id = "abstract"
    interim = True
    capabilities: frozenset = frozenset()

    def fingerprint(self):
        """Hashes that pin prompt, schema and executor code into the manifest."""
        raise NotImplementedError

    def open_case(self, case, repos, work, *, deadline_passed):
        """Return a session with initial_messages(), response_format(), step() and close()."""
        raise NotImplementedError


class EvidenceRefsV2Interim(ActionProtocol):
    """Adapter over the existing main protocol; Linux only (POSIX store and O_NOFOLLOW reads)."""

    protocol_id = "evidence-refs-v2-interim"
    interim = True
    capabilities = frozenset()

    def __init__(self):
        from agent_graph.contracts import model_action_schema
        from agent_graph.evidence_refs import ReferenceReply
        from agent_graph.inference import REFERENCE_SYSTEM
        self.system = REFERENCE_SYSTEM
        self.schema = model_action_schema(ReferenceReply)
        self.fields = _schema_fields(self.schema)

    def fingerprint(self):
        root = Path(__file__).resolve().parents[2]
        # LF-normalized, so a Windows checkout and the Linux runner agree.
        code = {p: hashlib.sha256((root / p).read_bytes().replace(b"\r\n", b"\n")).hexdigest() for p in (
            "src/agent_graph/evidence_refs.py", "src/agent_graph/contracts.py", "src/agent_graph/engine.py",
            "src/agent_graph/inference.py", "src/agent_graph/discovery.py", "src/agent_graph/sources.py",
            "tools/autonomous_mvp/protocol.py")}
        return dict(protocol_id=self.protocol_id, interim=True, capabilities=sorted(self.capabilities),
                    system_sha256=hashlib.sha256(self.system.encode()).hexdigest(),
                    schema_sha256=hashlib.sha256(json.dumps(self.schema, sort_keys=True).encode()).hexdigest(),
                    constitution=None, code_sha256=code)

    def open_case(self, case, repos, work, *, deadline_passed):
        from agent_graph.contracts import GraphError

        def admission_check():
            # Runs inside the store transaction: a late admission rolls back.
            if deadline_passed():
                raise GraphError("investigation_deadline")
        return _RefsV2Session(self, case, repos, Path(work), admission_check)


def render_task(task):
    """The ticket is untrusted text. Bounded to the core's 2000-character task limit."""
    text = f"[{task['kind']} {task['key']}] {task['summary']}\n{task['description']}"
    return text[:2000]


class _RefsV2Session:
    def __init__(self, protocol, case, repos, work, admission_check):
        from agent_graph.contracts import Policy, canonical
        from agent_graph.engine import Graph
        from agent_graph.evidence_refs import EvidenceSession
        from agent_graph.store import Store
        self.p, self.canonical, self.admission_check = protocol, canonical, admission_check
        policy = Policy.model_validate(dict(
            installation_id="amvp-2b", environment="synthetic-fixture", subject="amvp-2b-runner",
            capabilities=["read_context", "maintain", "propose"],
            repositories=[dict(id=r["id"], service=r["service"], root=repos[r["id"]]["root"],
                               revision=repos[r["id"]]["commit"]) for r in case["repositories"]],
            addresses=case["addresses"],
            limits=dict(max_model_steps=case["limits"]["max_model_steps"], max_tool_lines=60)))
        self.store = Store(work / "private-state")
        self.graph = Graph(policy, self.store)
        self.context = self.graph.prepare_context(render_task(case["task"]))
        self.refs = EvidenceSession(self.graph, self.context["id"])
        self.inventory = [dict(source_id=s["id"], repository=s["repository"], path=s["path"],
                               lines=len(s["text"].splitlines()), service=s["service"])
                          for s in self.context["sources"].values()]

    def initial_messages(self, remaining_steps):
        task = dict(task=self.context["task"], sources=self.inventory, gaps=self.context["graph"]["gaps"],
                    task_data_is_untrusted=True, context_id=self.context["id"], remaining_steps=remaining_steps)
        return [dict(role="system", content=self.p.system), dict(role="user", content=self.canonical(task))]

    def response_format(self):
        return dict(type="json_schema", json_schema=dict(name="graph_action", strict=True, schema=self.p.schema))

    def _reject(self, action, layer, code, content, path=None, expected=None, remaining=0):
        feedback = dict(action_rejected=dict(layer=layer, reason_code=code, field_path=path),
                        remaining_steps=remaining)
        return StepOutcome(action=action, valid=False, layer=layer, reason_code=code, field_path=path,
                           expected_type=expected, messages=[dict(role="assistant", content=content),
                                                             dict(role="user", content=self.canonical(feedback))])

    def step(self, content, *, remaining_steps):
        from pydantic import ValidationError
        from agent_graph.contracts import GraphError, load_json
        from agent_graph.evidence_refs import ReferenceReply
        try:
            data = load_json(content)
        except (ValueError, RecursionError):
            return self._reject("<unparsed>", "json", "invalid_json", content, remaining=remaining_steps)
        action = data.get("action") if isinstance(data, dict) else None
        action = action if action in ("read_source", "propose", "finish") else "<unparsed>"
        try:
            reply = ReferenceReply.model_validate(data)
        except ValidationError as exc:
            first = exc.errors()[0]
            return self._reject(action, "schema", "schema_violation", content,
                                safe_field_path(first["loc"], self.p.fields), first["type"], remaining_steps)
        source_fields = (reply.source_id, reply.start_line, reply.end_line)
        if reply.action == "read_source":
            if reply.proposals or any(v is None for v in source_fields):
                return self._reject(action, "field_combination", "read_requires_range_and_no_proposals",
                                    content, remaining=remaining_steps)
            try:
                value = self.refs.read(reply.source_id, reply.start_line, reply.end_line)
            except GraphError as exc:
                return self._reject(action, "tool_admissibility", exc.code, content, remaining=remaining_steps)
            return StepOutcome(action=action, valid=True, tool=dict(
                source_id=reply.source_id, start_line=reply.start_line, end_line=reply.end_line),
                messages=[dict(role="assistant", content=content),
                          dict(role="user", content=self.canonical(dict(untrusted_source=value,
                                                                         remaining_steps=remaining_steps)))])
        if reply.action == "propose":
            if any(v is not None for v in source_fields) or not reply.proposals:
                return self._reject(action, "field_combination", "propose_requires_proposals_and_null_range",
                                    content, remaining=remaining_steps)
            claims, results = [], []
            for proposal in reply.proposals:
                record = ClaimRecord(claim=proposal.claim.model_dump(), kind="dependency",
                                     ref_digests=[ref_digest(r) for r in proposal.evidence_refs])
                assessment = self.refs.assess(proposal)
                record.provenance = assessment["provenance"]["status"]
                record.provenance_reason = assessment["provenance"].get("reason")
                record.sufficiency = assessment["sufficiency"]["status"]
                if record.provenance == "AUTHENTIC_AUTHORIZED_CURRENT" and record.sufficiency == "SUPPORTED_WITHIN_PROFILE":
                    try:
                        self.refs.propose(proposal, admission_check=self.admission_check)
                        record.admitted, record.confidence = True, "CONFIRMED_WITHIN_PROFILE"
                    except GraphError as exc:
                        record.provenance_reason = record.provenance_reason or exc.code
                claims.append(record)
                results.append(dict(admitted=record.admitted, provenance=record.provenance,
                                    sufficiency=record.sufficiency, reason=record.provenance_reason))
            # A well-formed propose is a valid action even when the executor
            # admits none of its claims; the claim records carry that verdict.
            return StepOutcome(action=action, valid=True, claims=claims,
                               messages=[dict(role="assistant", content=content),
                                         dict(role="user", content=self.canonical(dict(
                                             proposal_results=results, remaining_steps=remaining_steps)))])
        if reply.proposals or any(v is not None for v in source_fields):
            return self._reject(action, "field_combination", "finish_requires_empty_fields", content,
                                remaining=remaining_steps)
        return StepOutcome(action=action, valid=True, terminal="FINISHED")

    def close(self):
        self.store.close()


class AgentServiceV1Pending(ActionProtocol):
    """Placeholder for the 2A protocol: integration happens on rebase onto its contracts commit."""

    protocol_id = "agent-service-v1"
    interim = False
    capabilities = frozenset(CAPABILITIES)

    def __init__(self):
        raise ProtocolUnavailable("protocol_2a_not_integrated")


PROTOCOLS = {EvidenceRefsV2Interim.protocol_id: EvidenceRefsV2Interim,
             AgentServiceV1Pending.protocol_id: AgentServiceV1Pending}


def load(protocol_id):
    if protocol_id not in PROTOCOLS:
        raise ProtocolUnavailable("unknown_protocol")
    return PROTOCOLS[protocol_id]()
