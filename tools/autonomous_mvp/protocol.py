"""Run one 2B case through the real 2A executor (actions-v3, constitution agent-service-v1).

There is no second protocol implementation here. `agent_graph.executor.run_investigation`
owns the dialogue, the action layers, the constitution limits, the evidence checks and
the outcome. This module only supplies:

* `AccountedModel`, the `complete_raw` model the executor calls, over a 2B transport
  (Cloud.ru in live runs, a scripted transport offline). It books every attempt for
  the ledger and turns transport failures into the executor's GraphError codes.
* the case policy: pinned Git snapshots of the fixtures, operator addresses and the
  bundled constitution (a derived copy only lowers max_steps for step-limit controls);
* the persistent graph for the graph_* tools, built by trusted code: the code of every
  granted and revoked repository plus the operator ownership mapping. The model's
  policy excludes revoked repositories, so its graph snapshot must not show them;
  AccountedModel watches graph results for leaks, graph ids and owner statuses;
* `case_result`, which maps the executor report into the 2B records in
  agent-graph-output 2.0 terms (fact/hypothesis, provenance, sufficiency and
  ContractError-shaped diagnostics). The claim of each proposal is recovered with the
  executor's own `actions.parse` on the reply; no reply text is stored.
"""
from __future__ import annotations

from decimal import ROUND_CEILING, Decimal
import hashlib
import json
from pathlib import Path
import time

PROTOCOL_ID = "actions-v3"
CONFIDENCE = ("NOT_ADMITTED", "CANDIDATE", "CONFIRMED_WITHIN_PROFILE")
TERMINALS = {"step_limit": "STEP_LIMIT", "deadline": "DEADLINE", "transport_failure": "TRANSPORT_FAILED",
             "invalid_actions": "ACTION_REJECTED_LIMIT", "budget": "BUDGET", "cancelled": "CANCELLED"}
# transport.py code -> executor GraphError code (agent_graph.executor.TRANSPORT)
TRANSPORT_CODES = {"timeout": "model_timeout", "deadline_before_send": "model_timeout",
                   "deadline_during_body": "model_timeout", "missing_secret": "missing_model_secret",
                   "body_limit": "model_response_limit", "unsupported_content_encoding": "unsupported_content_encoding",
                   "http_rate_limited": "model_http_error", "http_unauthorized": "model_http_error",
                   "http_server_error": "model_http_error", "http_error": "model_http_error"}


def ref_digest(value):
    return hashlib.sha256(str(value).encode()).hexdigest()


def text_sha256(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


class AccountedModel:
    """The model object handed to run_investigation. One call is one booked attempt."""

    def __init__(self, transport, model, parameters, *, attempts, breaker=None, family=None, revoked=()):
        self.transport, self.model, self.parameters = transport, model, parameters
        self.attempts, self.breaker, self.family = attempts, breaker, family
        self.parsed = []  # per attempt: typed proposal of the reply, or None
        self.revoked = tuple(revoked)
        self.graph = dict(calls={}, revoked_leaks=0, owners={})
        self.graph_ids = set()  # digests of every id a graph result showed the model

    def _observe(self, messages):
        """Safe facts about the last graph result the model is about to see: ids, owners, leaks."""
        if len(messages) < 4 or messages[-1]["role"] != "user" or messages[-2]["role"] != "assistant":
            return
        try:
            result = json.loads(messages[-1]["content"]).get("tool_result")
        except (ValueError, AttributeError):
            return
        if not isinstance(result, dict) or "graph_version" not in result:
            return
        from agent_graph.actions import Rejection, parse
        try:
            action = parse(messages[-2]["content"])
        except Rejection:
            return
        self.graph["calls"][action.name] = self.graph["calls"].get(action.name, 0) + 1
        text = json.dumps(result)
        self.graph["revoked_leaks"] += sum(1 for r in self.revoked if r in text)

        def ids(value):
            if isinstance(value, dict):
                for k, v in value.items():
                    if len(k) == 64:
                        self.graph_ids.add(ref_digest(k))
                    ids(v)
            elif isinstance(value, list):
                for v in value:
                    ids(v)
            elif isinstance(value, str) and len(value) == 64 and all(c in "0123456789abcdef" for c in value):
                self.graph_ids.add(ref_digest(value))
        ids(result["result"])
        if action.name == "graph_owner":
            self.graph["owners"][action.service] = result["result"]["status"]
        if action.name == "graph_impact":
            for a in result["result"]["affected"]:
                self.graph["owners"][a["service"]] = a["owner_status"]

    def complete_raw(self, messages, schema, *, cancel=None, deadline_epoch=None):
        from agent_graph.contracts import GraphError
        self._observe(messages)
        payload = dict(model=self.model["id"], messages=messages, stream=False,
                       temperature=self.parameters["temperature"],
                       **{self.parameters["token_parameter"]: self.model["max_completion_tokens"]},
                       response_format=dict(type="json_schema", json_schema=dict(
                           name="agent_action", strict=True, schema=schema)))
        if len(json.dumps(payload, ensure_ascii=False).encode()) > self.parameters["max_prompt_bytes"]:
            raise GraphError("model_input_limit")  # nothing was sent, so no attempt is booked
        timeout = self.parameters["request_timeout_seconds"]
        if deadline_epoch is not None:
            timeout = min(timeout, deadline_epoch - time.time())
        result = self.transport.complete(payload, deadline=time.monotonic() + timeout)
        late = deadline_epoch is not None and time.time() >= deadline_epoch
        attempt = dict(result.safe(), step=len(self.attempts), late=late)
        self.attempts.append(attempt)
        self.parsed.append(_proposal(result.content) if result.ok else None)
        if self.breaker is not None:
            self.breaker.observe(attempt, self.family)
        if not result.ok:
            raise GraphError(TRANSPORT_CODES.get(result.code, "model_unavailable_or_invalid"))
        if result.finish_reason != "stop" or result.has_tool_calls:
            raise GraphError("model_incomplete_or_refused")  # same rule as agent_graph ChatModel
        if result.usage is None or result.usage["completion_tokens"] > self.model["max_completion_tokens"]:
            raise GraphError("invalid_model_usage")
        return result.content, dict(result.usage)


def _proposal(content):
    """Typed claim of a propose action, via the executor's own parser; None otherwise."""
    from agent_graph.actions import Rejection, parse
    from agent_graph.contracts import digest
    try:
        action = parse(content)
    except Rejection:
        return None
    if action.name == "propose_dependency":
        claim = action.claim.model_dump()
        return dict(kind="fact", digest=digest(claim), claim=claim,
                    refs=[ref_digest(r) for r in action.evidence_refs], unknowns=[])
    if action.name == "propose_hypothesis":
        c = action.claim
        return dict(kind="hypothesis", digest=None, claim=dict(
            consumer_service=c.consumer_service, provider_service=c.provider_service, method=c.method,
            path_template=c.route), refs=[ref_digest(r) for r in action.evidence_refs], unknowns=list(action.unknowns))
    return None


def constitution_for(case, work):
    """The bundled constitution; step-limit controls get a copy with only max_steps lowered."""
    import yaml
    from agent_graph.constitution import DEFAULT_PATH, load
    _, bundled_version = load(DEFAULT_PATH)
    steps = case["limits"]["max_model_steps"]
    data = yaml.safe_load(Path(DEFAULT_PATH).read_text(encoding="utf-8"))
    if steps == data["limits"]["max_steps"]:
        return str(DEFAULT_PATH), bundled_version
    data["limits"]["max_steps"] = steps
    path = Path(work) / "constitution-step-control.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return str(path), load(path)[1]


def case_policy(case, repos, model, parameters, constitution_path, run_id, *, include_revoked=False):
    """The reader's policy; include_revoked=True gives the wider policy the graph was synced with earlier."""
    from agent_graph.contracts import Policy
    p = parameters
    granted = [r for r in case["repositories"] if include_revoked or r.get("scope", "granted") != "revoked"]
    # The executor reserves messages + schema + 4096 + max output per call; bound it for every step.
    tokens = (p["max_prompt_bytes"] + 4096 + model["max_completion_tokens"]) * case["limits"]["max_model_steps"]
    # Whole RUB per million tokens, rounded up: the core store bound is never below the published rate.
    rate = int(max(Decimal(model["price"]["input_per_million"]), Decimal(model["price"]["output_per_million"]))
               .to_integral_value(rounding=ROUND_CEILING))
    endpoint = p["chat_endpoint"]
    return Policy.model_validate(dict(
        installation_id="amvp-2b", environment="synthetic-fixture", subject="amvp-2b-runner",
        capabilities=["read_context", "maintain", "propose"], constitution=constitution_path,
        repositories=[dict(id=r["id"], service=r["service"], root=repos[r["id"]]["root"],
                           revision=repos[r["id"]]["commit"], snapshot="git") for r in granted],
        addresses=case["addresses"], limits=dict(max_tool_lines=60),
        model=dict(endpoint=endpoint, allowed_endpoints=[endpoint], model=model["id"],
                   configuration_id=f"{run_id}:{model['id']}", api_key_env=p["credential_env"],
                   protocol=PROTOCOL_ID, token_parameter=p["token_parameter"], allow_source_transfer=True,
                   route="corporate", context_tokens=p["context_tokens"],
                   max_output_tokens=model["max_completion_tokens"], max_prompt_bytes=p["max_prompt_bytes"],
                   timeout_seconds=min(60.0, float(p["request_timeout_seconds"])),
                   installation_token_cap=tokens, run_token_cap=tokens, currency="RUB",
                   # The 2B ledger holds the program money cap; the core store gets the same case bound.
                   micro_per_million_tokens=rate * 1_000_000, installation_micro_cap=tokens * rate,
                   run_micro_cap=tokens * rate)))


def render_task(task):
    """The ticket is untrusted text, bounded to the core's 2000-character task limit."""
    return f"[{task['kind']} {task['key']}] {task['summary']}\n{task['description']}"[:2000]


def run(case, repos, *, model, parameters, transport, work, deadline_epoch, run_id, attempts, breaker=None):
    """Prepare the pinned context and run the real executor. Returns (report, accounted model, versions)."""
    from agent_graph.engine import Graph
    from agent_graph.executor import run_investigation
    from agent_graph.store import Store
    from agent_graph.graph_store import GraphStore, OwnershipMapping
    constitution_path, constitution_version = constitution_for(case, work)
    policy = case_policy(case, repos, model, parameters, constitution_path, run_id)
    revoked = [r for r, v in repos.items() if v.get("scope") == "revoked"]
    task = render_task(case["task"])
    store = Store(Path(work) / "private-state")
    try:
        gs = GraphStore(store)
        if revoked:
            # The graph was built while the revoked repositories were still granted.
            wider = case_policy(case, repos, model, parameters, constitution_path, run_id, include_revoked=True)
            gs.sync_code(Graph(wider, store).prepare_context(task, revisions={r: v["commit"] for r, v in repos.items()}))
        if case.get("ownership") is not None:
            gs.sync_ownership(policy.installation_id, policy.environment, OwnershipMapping.model_validate(case["ownership"]))
        graph = Graph(policy, store)
        context = graph.prepare_context(task, revisions={r: v["commit"] for r, v in repos.items() if r not in revoked})
        if not revoked:
            gs.sync_code(context)
        accounted = AccountedModel(transport, model, parameters, attempts=attempts, breaker=breaker,
                                   family=case["family"], revoked=revoked)
        report = run_investigation(graph, context["id"], model=accounted, deadline_epoch=deadline_epoch,
                                   request_id=case["case_id"], graph_store=gs)
        return report, accounted, dict(constitution_version=constitution_version,
                                       graph_version=report.get("graph_version"))
    finally:
        store.close()


def case_result(report, accounted):
    """Executor report -> 2B steps, claims and final, with no reply text."""
    rejected = {d["step"]: d for d in report["diagnostics"]}
    insufficient = set(report["insufficient_claims"])
    steps, claims = [], []
    for event in report["events"]:
        step = event["step"]
        if event.get("accepted"):
            steps.append(dict(step=step, action=event["action"], valid=True, layer=None, reason_code=None, errors=[]))
        else:
            d = rejected.get(step, event)
            steps.append(dict(step=step, action=d.get("action") or "<unparsed>", valid=False, layer=d["layer"],
                              reason_code=d["reason_code"],
                              errors=[dict(path=d.get("field_path") or "", type=d.get("expected") or d["reason_code"])]))
        proposal = accounted.parsed[step] if step < len(accounted.parsed) else None
        if proposal is None:
            continue
        record = dict(claim=proposal["claim"], kind=proposal["kind"], ref_digests=proposal["refs"],
                      graph_refs=sum(1 for r in proposal["refs"] if r in accounted.graph_ids),
                      origin="code" if proposal["kind"] == "fact" else "model_hypothesis",
                      provenance="UNVERIFIED", provenance_reason=None, sufficiency="NOT_ASSESSED",
                      unknowns=proposal["unknowns"], admitted=False, confidence="NOT_ADMITTED")
        if event.get("accepted"):
            record["provenance"] = "AUTHENTIC"  # every cited receipt resolved in this session
            if proposal["kind"] == "fact":
                ok = proposal["digest"] not in insufficient
                record.update(sufficiency="SUPPORTED_WITHIN_PROFILE" if ok else "INSUFFICIENT", admitted=ok,
                              confidence="CONFIRMED_WITHIN_PROFILE" if ok else "NOT_ADMITTED")
            else:
                record.update(admitted=True, confidence="CANDIDATE")
        elif steps[-1]["layer"] == "evidence":
            record.update(provenance="REJECTED", provenance_reason=steps[-1]["reason_code"])
        claims.append(record)
    finish = report.get("finish") or {}
    if finish:
        terminal = "ABSTAINED" if finish.get("outcome") == "abstain" else "FINISHED"
    else:
        terminal = TERMINALS.get(report["outcome"], "HARNESS_ERROR")
    final = dict(status=report["status"], reason_code=report["reason_code"], outcome=report["outcome"],
                 finish_reason=finish.get("reason"))
    graph = dict(accounted.graph, ids_seen=len(accounted.graph_ids))
    return terminal, steps, claims, final, graph


def contract_violations(record):
    """Rules of AnalysisResult.semantics and HypothesisEvidence applied to one claim record."""
    from agent_graph.output_contracts import FactSufficiency
    problems = []
    if record["admitted"] and record["kind"] == "fact" and not (
            record["origin"] != "model_hypothesis" and record["provenance"] == "AUTHENTIC"
            and record["sufficiency"] in FactSufficiency):
        problems.append("fact_without_sufficient_evidence")
    if record["origin"] == "model_hypothesis" and record["sufficiency"] in FactSufficiency:
        problems.append("hypothesis_cannot_be_sufficient")
    if record["admitted"] and record["provenance"] == "REJECTED":
        problems.append("claim_cites_rejected_evidence")
    return problems


def hypothesis_evidence(record, *, model_configuration_id, visibility, checked_at):
    """The HypothesisEvidence of a candidate, validated by the 2.0 contract (raises if invalid)."""
    from pydantic import TypeAdapter
    from agent_graph.output_contracts import HypothesisEvidence
    return TypeAdapter(HypothesisEvidence).validate_python(dict(
        id="hyp:" + ref_digest(json.dumps(record["claim"], sort_keys=True))[:40],
        provenance=record["provenance"], sufficiency=record["sufficiency"],
        freshness=dict(status="CURRENT", checked_at=checked_at), visibility=list(visibility),
        model_configuration_id=model_configuration_id, supporting_refs=list(record["ref_digests"])[:16],
        unknowns=list(record["unknowns"]))).model_dump(mode="json")


def fingerprint():
    """Hashes that pin the executor, prompt, schema and constitution into the manifest."""
    from agent_graph.actions import action_schema, system_prompt
    from agent_graph.constitution import DEFAULT_PATH, load
    root = Path(__file__).resolve().parents[2]
    constitution, version = load(DEFAULT_PATH)
    files = ("src/agent_graph/actions.py", "src/agent_graph/executor.py", "src/agent_graph/constitution.py",
             "src/agent_graph/evidence_refs.py", "src/agent_graph/engine.py", "src/agent_graph/sources.py",
             "src/agent_graph/git_sources.py", "src/agent_graph/discovery.py", "src/agent_graph/output_contracts.py",
             "src/agent_graph/graph_query.py", "src/agent_graph/graph_store.py",
             "constitutions/agent-service-v1.yaml", "tools/autonomous_mvp/protocol.py")
    return dict(protocol=PROTOCOL_ID, executor="agent_graph.executor.run_investigation",
                constitution_version=version,
                system_sha256=hashlib.sha256(system_prompt(constitution).encode()).hexdigest(),
                schema_sha256=hashlib.sha256(json.dumps(action_schema(), sort_keys=True).encode()).hexdigest(),
                code_sha256={f: text_sha256(root / f) for f in files})
