"""Real graph investigation on a pinned, unaccepted core candidate.

Only the Actions qualification process receives the Foundation Models secret.
No SDK/fallback, corpus execution, raw HTTP logging or secret artifacts.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
CONFIG = json.loads((HERE / "experiment.json").read_text())
ENDPOINT = "https://foundation-models.api.cloud.ru/v1/chat/completions"
TASK = (
    "Investigate HTTP dependencies in these sources using read_source. Read the callsite and provider "
    "before proposing; cite exact lines from both. Do not use path equality alone to equate services. "
    "For each dependency use kind hypothesis, key in the format 'consumer->provider METHOD /path' "
    "with the actual service IDs, and a concise statement explaining the evidence. "
    "Proposals remain unapproved. Do not invent dependencies, tests or approvals. "
    "Use only read_source, propose and finish. Finish after supported findings or insufficient evidence."
    " Action fields: read_source requires source_id and integer start_line/end_line, proposals=[]. "
    "For propose and finish, source_id=null, start_line=null, end_line=null, always. "
    "A proposal key uses repository/service names from inventory, NEVER source hashes. "
    "Citations must include BOTH callsite and provider; copy quotes verbatim including ASCII quotation marks. "
    "Operator service-address mapping (not dependencies): orders=https://orders.test; status=https://inventory.test."
)
PRIOR = HERE.parents[2] / "lab/reports/graph-cycle-2026-10-21/initial"


def prior_case():
    path = PRIOR / "0-reporting-http/report.json"
    return json.loads(path.read_text()) if path.exists() else None


def validated_resume(graph, context, prior):
    """Revalidate previously read evidence against this exact synthetic snapshot."""
    from agent_graph.contracts import Citation, GraphError, canonical
    if prior["basis"] != context["basis"] or prior["core_sha"] != CONFIG["core_sha"] or prior["request_count"] != 3:
        raise GraphError("resume_basis_or_budget_mismatch")
    messages = json.loads((PRIOR / "0-reporting-http/messages-3.json").read_text())
    seed, old_actions = [], []
    for i in range(2, len(messages), 2):
        action = json.loads(messages[i]["content"])
        evidence = json.loads(messages[i+1]["content"])["untrusted_source"]
        if action["action"] != "read_source" or action["proposals"]:
            raise GraphError("invalid_resume_action")
        if any(action[k] != evidence[k] for k in ("source_id", "start_line", "end_line")):
            raise GraphError("resume_evidence_mismatch")
        citation = Citation.model_validate({k: evidence[k] for k in ("source_id", "start_line", "end_line", "quote")})
        actual = graph.get_evidence(context["id"], citation)
        if actual != evidence:
            raise GraphError("resume_evidence_mismatch")
        seed.extend([dict(role="assistant", content=canonical(action)),
                     dict(role="user", content=canonical(dict(untrusted_source=actual)))])
        old_actions.append(action)
    seed.append(dict(role="assistant", content=canonical(prior["actions"][-1])))
    seed.append(dict(role="user", content=canonical(dict(operator_protocol_correction="Previous action was rejected: invalid_model_action. No proposal was stored. "
        "Correct the action format; propose requires all three source fields null. Use inventory repository/service "
        "names in keys, exact unchanged quotes from BOTH sources. Do not guess typographic quotes. "
        "Continue from already read, revalidated sources. At most three requests remain; finish after proposing."))))
    return seed, old_actions


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump(path, value):
    """Last defense for reports; never serialize environment or raw HTTP objects."""
    text = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    secret = os.environ.get("CLOUDRU_FOUNDATION_API_KEY", "")
    if secret:
        text = text.replace(secret, "[REDACTED]")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text)
    tmp.replace(path)


class Ledger:
    """Conservative attempted HTTP counts; failures are charged, never refunded."""
    def __init__(self, path):
        self.path = path
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE attempts(id INTEGER PRIMARY KEY, case_id TEXT, model TEXT)")

    def reserve(self, case_id, model):
        with sqlite3.connect(self.path) as db:
            db.execute("BEGIN IMMEDIATE")
            total = db.execute("SELECT count(*) FROM attempts").fetchone()[0]
            count = db.execute("SELECT count(*) FROM attempts WHERE case_id=? AND model=?", (case_id, model)).fetchone()[0]
            if total >= CONFIG["request_cap"] or count >= CONFIG["case_request_cap"]:
                raise RuntimeError("request_budget_exhausted")
            db.execute("INSERT INTO attempts(case_id,model) VALUES(?,?)", (case_id, model))
            return total + 1

    def count(self):
        with sqlite3.connect(self.path) as db:
            return db.execute("SELECT count(*) FROM attempts").fetchone()[0]


def build_corpus(core, destination, case_id):
    """Copied synthetic sources, not executed. E activates an existing allowed root."""
    fixture = core / "examples/agent_graph/corpus"
    names = {"reporting-http": ("orders", "reporting"),
             "export-E": ("orders", "export"),
             "status-decoy": ("orders", "health", "status")}[case_id]
    for name in names:
        root = destination / name
        root.mkdir(parents=True)
        if name == "status":
            # Dedicated Status provider uses the existing /orders declaration;
            # only service identity/address differs. No live HTTP service needed.
            shutil.copyfile(fixture / "orders/api.py", root / "api.py")
        else:
            source = "api.py" if name == "orders" else "client.py"
            shutil.copyfile(fixture / name / source, root / source)
    if case_id == "export-E":
        (destination / "export/client.py").write_text("# Export is inactive before scenario E.\n")
    return names


def model_config(model):
    # Keep the core's nonzero corporate monetary guard. Public catalogue rates
    # are estimates, not a claim of project billing or zero grant consumption.
    rates = CONFIG["tariff"]["per_million"][model]
    rate = int(max(Decimal(rates["input"]), Decimal(rates["output"])) * 1_000_000)
    return dict(endpoint=ENDPOINT, allowed_endpoints=[ENDPOINT], model=model,
                configuration_id=CONFIG["experiment_id"] + ":" + model,
                api_key_env="CLOUDRU_FOUNDATION_API_KEY", allow_source_transfer=True,
                route="corporate", context_tokens=65536, max_prompt_bytes=24000,
                max_output_tokens=CONFIG["max_output_tokens"], timeout_seconds=45.0,
                installation_token_cap=1_000_000, run_token_cap=100_000,
                currency="RUB", micro_per_million_tokens=rate,
                installation_micro_cap=244_000_000, run_micro_cap=(rate // 10))


def score_case(case_id, records, actions, source_paths, expectations):
    expected = expectations[case_id]
    accepted = [r for r in records if r["decision"] == "ACCEPTED_UNAPPROVED_CANDIDATE"]
    keys = [r["proposal"]["key"] for r in accepted]
    evidence_ok = True
    for required in expected["required"]:
        proposed_at = next((i for i, a in enumerate(actions) if a["action"] == "propose"
                            and any(p["key"] == required for p in a["proposals"])), 0)
        read = {source_paths.get(a.get("source_id")) for a in actions[:proposed_at] if a["action"] == "read_source"}
        evidence_ok = evidence_ok and all(path in read for path in expected["required_sources"])
        matches = [r for r in accepted if r["proposal"]["key"] == required]
        cited = {source_paths.get(c["source_id"]) for r in matches for c in r["proposal"]["citations"]}
        evidence_ok = evidence_ok and all(p in cited for p in expected["required_sources"])
    forbidden = [k for k in keys if k in expected["forbidden"]]
    extras = [k for k in keys if k not in expected["required"]]
    return dict(required_found=all(k in keys for k in expected["required"]),
                forbidden=forbidden, extra_keys=extras, tool_and_citation_coverage=evidence_ok,
                passed=all(k in keys for k in expected["required"]) and not forbidden and not extras and evidence_ok,
                scope="synthetic proposal keys plus provenance; manual statement review required")


def run_case(core, root, case_id, model_name, ledger, store):
    from agent_graph.contracts import GraphError, Policy
    from agent_graph.engine import Graph
    from agent_graph.inference import ChatModel, investigate

    started = time.monotonic()
    prior = prior_case() if case_id == "reporting-http" and model_name == CONFIG["models"][0] else None
    previous_seconds = prior["seconds"] if prior else 0
    corpus = root / "corpus"
    names = build_corpus(core, corpus, case_id)
    addresses = [dict(service="orders", base_url="https://orders.test"),
                 dict(service="status", base_url="https://inventory.test")]
    policy = Policy.model_validate(dict(
        installation_id=CONFIG["experiment_id"], environment=case_id,
        subject="bounded-cloudru-experiment", capabilities=["read_context", "maintain", "propose"],
        repositories=[dict(id=n, service=n, root=str(corpus / n), revision=CONFIG["core_sha"] + ":" + case_id) for n in names],
        addresses=addresses, limits=dict(max_model_steps=6, max_tool_lines=60),
        model=model_config(model_name)))
    if prior:
        policy.limits.max_model_steps = CONFIG["case_request_cap"] - prior["request_count"]
        policy.model.run_token_cap -= prior["investigation"]["budget"]["reserved_token_units"]
        policy.model.run_micro_cap -= prior["investigation"]["budget"]["reserved_micro"]
    records, actions, calls = [], [], []

    class AuditedGraph(Graph):
        def propose(self, context_id, proposal, *, from_model=False):
            p = proposal.model_dump() if hasattr(proposal, "model_dump") else proposal
            row = dict(proposal=p)
            try:
                value = super().propose(context_id, proposal, from_model=from_model)
                row.update(decision="ACCEPTED_UNAPPROVED_CANDIDATE", id=value["id"])
                return value
            except GraphError as exc:
                row.update(decision="REJECTED", reason=exc.code)
                raise
            finally:
                records.append(row)

    graph = AuditedGraph(policy, store)
    transition = None
    if case_id == "export-E":
        before = graph.prepare_context(TASK)
        view = graph.view
        shutil.copyfile(core / "examples/agent_graph/corpus/export/client.py", corpus / "export/client.py")
        after = graph.prepare_context(TASK)
        transition = dict(before_basis=before["basis"], after_basis=after["basis"],
                          same_view=graph.view == view,
                          before_export_edges=sum(d["consumer"] == "export" for d in before["graph"]["dependencies"]),
                          after_export_edges=sum(d["consumer"] == "export" for d in after["graph"]["dependencies"]))
        context = after
    else:
        context = graph.prepare_context(TASK)
    source_paths = {s["id"]: s["repository"] + "/" + s["path"] for s in context["sources"].values()}
    source_manifest = [{"path": source_paths[s["id"]], "sha256": s["sha256"]} for s in context["sources"].values()]
    dump(root / "source-manifest.json", source_manifest)
    seed = None
    if prior:
        seed, old_actions = validated_resume(graph, context, prior)
        actions.extend(old_actions)

    def on_http(event, safe):
        if event == "request":
            if previous_seconds + time.monotonic() - started >= CONFIG["case_seconds"]:
                raise GraphError("case_deadline")
            try:
                number = ledger.reserve(case_id, model_name)
            except RuntimeError:
                raise GraphError("request_budget_exhausted") from None
            calls.append(dict(global_request=number, started=time.monotonic(), usage=None))
        elif calls:
            calls[-1].update(safe)

    class RecordingModel(ChatModel):
        def complete(self, messages, **kwargs):
            # Safe synthetic-only context transcript. Expectations and graph
            # dependency maps are never part of messages produced by investigate.
            dump(root / f"messages-{len(calls)+1}.json", messages)
            try:
                reply, usage = super().complete(messages, **kwargs)
                actions.append(reply.model_dump())
                return reply, usage
            except GraphError as exc:
                if calls:
                    calls[-1]["error"] = exc.code
                raise
            finally:
                if calls:
                    calls[-1]["seconds"] = time.monotonic() - calls[-1].pop("started", time.monotonic())

    cancel = threading.Event()
    timer = threading.Timer(max(0.001, CONFIG["case_seconds"] - previous_seconds - (time.monotonic() - started)), cancel.set)
    timer.start()
    try:
        result = investigate(graph, context["id"], model=RecordingModel(policy.model, on_http), cancel=cancel,
                             resume_messages=seed)
    finally:
        timer.cancel()
    # This file is read only AFTER all model calls for the case are over.
    expected = json.loads((HERE / "expectations.json").read_text())
    quality = score_case(case_id, records, actions, source_paths, expected)
    continuation_calls = len(calls)
    calls = (prior["requests"] if prior else []) + calls
    usage_complete = all(isinstance(c.get("usage"), dict) and
                         all(k in c["usage"] for k in ("prompt_tokens", "completion_tokens")) for c in calls)
    totals = {k: sum(c.get("usage", {}).get(k, 0) for c in calls if isinstance(c.get("usage"), dict))
              for k in ("prompt_tokens", "completion_tokens")}
    rate = CONFIG["tariff"]["per_million"][model_name]
    cost = sum(Decimal(totals[k]) * Decimal(rate[r]) / 1_000_000
               for k, r in (("prompt_tokens", "input"), ("completion_tokens", "output")))
    protocol = result["status"] == "COMPLETED" and result["reason"] is None
    report = dict(case=case_id, model=model_name, core_sha=CONFIG["core_sha"], basis=context["basis"],
                  config=policy.model.model_dump(), limits=policy.limits.model_dump(),
                  transition=transition, actions=actions, proposals=records, requests=calls,
                  protocol_passed=protocol, quality=quality, investigation=result,
                  seconds=previous_seconds + time.monotonic() - started, request_count=len(calls),
                  continuation_requests=continuation_calls, prior_run="39611545230" if prior else None,
                  usage_observed=totals, usage_complete=usage_complete,
                  estimated_cost_rub=str(cost) if usage_complete else None,
                  known_usage_cost_rub=str(cost), actual_billed_cost="NOT_MEASURED",
                  native_function_calling="NOT_USED_FINITE_JSON_ACTION_PROTOCOL")
    dump(root / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--core", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    core = args.core.resolve()
    exact = subprocess.check_output(["git", "-C", str(core), "rev-parse", "HEAD"], text=True).strip()
    if exact != CONFIG["core_sha"]:
        raise SystemExit("core_sha_mismatch")
    args.output.mkdir(parents=True, exist_ok=False)
    output = args.output.resolve()
    dump(output / "expectations-before-calls.json", json.loads((HERE / "expectations.json").read_text()))
    dump(output / "manifest.json", dict(config=CONFIG, config_sha256=sha(HERE / "experiment.json"),
        expectations_sha256=sha(HERE / "expectations.json"), adapter_patch_sha256=sha(HERE / "adapter-observer.patch"),
        source_sha=os.environ.get("GITHUB_SHA", "LOCAL"), grant="OWNER_CONFIRMED",
        prior_evidence_sha256=sha(PRIOR / "0-reporting-http/report.json") if prior_case() else None,
        core_acceptance="CANDIDATE_ONLY_NOT_ACCEPTANCE_OR_VM_PERMISSION"))
    if not args.live:
        dump(output / "summary.json", dict(status="PREPARED_NO_NETWORK", requests=0))
        return 0
    if not os.environ.get("CLOUDRU_FOUNDATION_API_KEY", "").strip():
        dump(output / "summary.json", dict(status="BLOCKED_MISSING_FOUNDATION_KEY", requests=0))
        return 1
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_RUN_ATTEMPT") != "1":
        dump(output / "summary.json", dict(status="BLOCKED_ACTIONS_FIRST_ATTEMPT_REQUIRED", requests=0))
        return 1
    sys.path.insert(0, str(core / "src"))
    from agent_graph.store import Store
    state = output.parent / (output.name + "-private-state")
    ledger_dir = state / "ledger"
    ledger_dir.mkdir(parents=True, mode=0o700)
    ledger = Ledger(ledger_dir / "attempts.sqlite3")
    store = Store(state / "core")
    prior = prior_case()
    if prior:
        for _ in range(prior["request_count"]):
            ledger.reserve(prior["case"], prior["model"])
        # Carry forward conservative charged reserves, never reset them on resume.
        from agent_graph.contracts import ModelConfig
        config = ModelConfig.model_validate(model_config(prior["model"]))
        reservation = store.reserve(CONFIG["experiment_id"], "historical-run-39611545230",
                                    prior["investigation"]["budget"]["reserved_token_units"], config)
        store.finish_reservation(reservation)
    results, stopped = [], None
    try:
        for model_index, model in enumerate(CONFIG["models"]):
            for case_index, case in enumerate(CONFIG["cases"]):
                report = run_case(core, output / f"{model_index}-{case}", case, model, ledger, store)
                results.append(dict(case=case, model=model, protocol_passed=report["protocol_passed"],
                                    quality=report["quality"], request_count=report["request_count"],
                                    usage_observed=report["usage_observed"], usage_complete=report["usage_complete"],
                                    estimated_cost_rub=report["estimated_cost_rub"]))
                if not report["protocol_passed"]:
                    stopped = "PROTOCOL_OR_BUDGET_FAILURE_NO_RETRY"
                    break
                if model_index == case_index == 0 and not report["quality"]["passed"]:
                    stopped = "FIRST_QWEN_CASE_GATE_FAILED_NO_RETRY"
                    break
            if stopped:
                break
    except Exception as exc:
        # No traceback or arbitrary exception text in Actions logs/artifacts.
        from agent_graph.contracts import GraphError
        stopped = exc.code if isinstance(exc, GraphError) else "HARNESS_ERROR"
    finally:
        store.close()
        dump(output / "summary.json", dict(status=stopped or "SERIES_COMPLETED", requests=ledger.count(),
            request_cap=CONFIG["request_cap"], results=results, actual_billed_cost="NOT_MEASURED"))
    print("graph-cycle report ready; see safe artifact summary.json")
    return int(stopped is not None)


if __name__ == "__main__":
    raise SystemExit(main())
