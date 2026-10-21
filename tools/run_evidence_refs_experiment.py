"""New evidence-refs-v2 series. Live requires explicit initialize + execute commands.

No old runner imports, no continuation/retry/reset. Default command is prepare.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

from agent_graph.contracts import GraphError, ModelConfig, Policy, canonical, digest, model_action_schema
from agent_graph.evidence_refs import ReferenceReply
from agent_graph.engine import Graph
from agent_graph.inference import ChatModel, investigate
from agent_graph.store import Store
from tools.evidence_refs_ledger import GitHubLedgerBackend, RunLedger
from tools.prepare_evidence_refs_experiment import CORPORA, FIXTURES, ROOT, manifest

ENDPOINT = "https://foundation-models.api.cloud.ru/v1/chat/completions"
KEY_ENV = "CLOUDRU_FOUNDATION_API_KEY"


class AccountedModel(ChatModel):
    """Preserve ChatModel worker-owned finalizer/OS-lock, including delayed DNS."""
    def __init__(self, config, ledger, case_key, deadline):
        super().__init__(config)
        self.ledger, self.case_key, self.deadline = ledger, case_key, deadline

    def complete(self, messages, *, cancel=None, on_finished=None, deadline_epoch=None):
        attempt = None
        delegated = False
        metadata = dict(http_status=None, usage=None, finish_reason=None)
        error = None
        try:
            self.ledger.check(self.case_key)
            upper = (len(canonical(messages).encode()) + len(canonical(model_action_schema(ReferenceReply)).encode())
                     + 4096 + self.config.max_output_tokens)
            attempt = self.ledger.reserve(self.case_key, digest(messages), upper)
            self.ledger.check(self.case_key)
            delegated = True
            return super().complete(messages, cancel=cancel, on_finished=on_finished,
                                    deadline_epoch=min(self.deadline, deadline_epoch or self.deadline),
                                    metadata=metadata)
        except GraphError as exc:
            error = exc.code
            raise
        finally:
            if not delegated and on_finished:
                on_finished()
            if attempt is not None:
                self.ledger.record(attempt, dict(metadata), error)


def case_policy(root, case, model, packet, money_cap):
    plan, p = packet["plan"], packet["plan"]["parameters"]
    corpus = root / "corpus"
    shutil.copytree(FIXTURES / CORPORA[case], corpus)
    repos = sorted(v.name for v in corpus.iterdir())
    config = ModelConfig(
        endpoint=ENDPOINT, allowed_endpoints=[ENDPOINT], model=model, api_key_env=KEY_ENV,
        configuration_id=plan["experiment_id"] + ":" + model, protocol="evidence-refs-v2",
        token_parameter=p["token_parameter"], allow_source_transfer=True, route="corporate",
        context_tokens=p["context_tokens"], max_output_tokens=p["max_output_tokens"],
        max_prompt_bytes=p["max_prompt_bytes"], timeout_seconds=float(p["request_timeout_seconds"]),
        installation_token_cap=10_000_000, run_token_cap=1_000_000,
        currency="RUB", micro_per_million_tokens=plan["budget"]["worst_micro_per_million_tokens"],
        installation_micro_cap=money_cap, run_micro_cap=money_cap)
    return Policy.model_validate(dict(
        installation_id=plan["experiment_id"], environment="synthetic-approved-corpus", subject="bounded-model-runner",
        capabilities=["read_context", "maintain", "propose"],
        repositories=[dict(id=r, service=r, root=str(corpus / r), revision=plan["historical_pr31_sha"]) for r in repos],
        addresses=plan["addresses"], limits=dict(max_model_steps=p["max_model_steps"], max_tool_lines=p["max_tool_lines"]),
        model=config.model_dump()))


def score(report, oracle, required_reads=None):
    """Score new typed claims, including rejected claims. Never import old results."""
    claims = [p["claim"] for e in report["events"] for p in e.get("reference_proposals", [])]
    assessments = [a for e in report["events"] for a in e.get("evidence_assessments", [])]
    required = {digest(c) for c in oracle["required"]}
    forbidden = {digest(c) for c in oracle["forbidden"]}
    proposed = {digest(c) for c in claims}
    provenance = bool(assessments) and len(assessments) == len(claims) and all(
        a["provenance"]["status"] == "AUTHENTIC_AUTHORIZED_CURRENT" for a in assessments)
    sufficiency = bool(assessments) and len(assessments) == len(claims) and all(
        a["sufficiency"]["status"] == "SUPPORTED_WITHIN_PROFILE" for a in assessments)
    quality = required <= proposed and not proposed & forbidden and not proposed - required
    unread = {source: set(range(1, count + 1)) for source, count in (required_reads or {}).items()}
    early_proposal = False
    for event in report["events"]:
        read = event.get("evidence_read")
        if read and read["source_id"] in unread:
            unread[read["source_id"]].difference_update(range(read["start_line"], read["end_line"] + 1))
        if event.get("action") == "propose" and any(unread.values()):
            early_proposal = True
    corpus_read = not any(unread.values()) and not early_proposal
    protocol = report["status"] == "COMPLETED" and corpus_read
    admitted = bool(report["candidate_ids"])
    return dict(protocol_passed=protocol, corpus_read_protocol_passed=corpus_read, provenance_passed=provenance, sufficiency_passed=sufficiency,
                held_out_quality_passed=quality, candidates_admitted=admitted,
                all_passed=protocol and provenance and sufficiency and quality and admitted,
                proposed_claims=claims, rejected_or_unassessed_claims=len(claims) - sum(
                    a["sufficiency"]["status"] == "SUPPORTED_WITHIN_PROFILE" for a in assessments),
                trust="UNAPPROVED_CANDIDATE", runtime_verified=False)


def run_series(ledger, work, *, model_factory=AccountedModel):
    packet = ledger.packet
    # Evaluator-only; loaded here, never added to task/messages/model config.
    oracle = json.loads((ROOT / "experiments/evidence_refs_v2/oracle.json").read_text())
    store = Store(work / "private-state")
    try:
        for case in packet["plan"]["case_order"]:
            for index, model in enumerate(packet["plan"]["models"]):
                key, deadline = ledger.start_case(case, model)  # Before scanning/context preparation.
                root = work / f"{case}-{index}"
                root.mkdir()
                graph = Graph(case_policy(root, case, model, packet, ledger.state["money_cap_micro"]), store)
                context = graph.prepare_context(packet["plan"]["task"])
                ledger.check(key)
                report = investigate(graph, context["id"],
                                     model=model_factory(graph.policy.model, ledger, key, deadline), deadline_epoch=deadline)
                result = dict(status=report["status"], reason=report["reason"], report=report,
                              evaluation=score(report, oracle[case], {s["id"]: len(s["text"].splitlines()) for s in context["sources"].values()}))
                ledger.finish_case(key, result)
                reason = report["reason"] or ""
                if reason.startswith("ledger_") or reason in {
                    "new_budget_exhausted", "budget_exhausted", "model_busy", "cancelled",
                    "missing_model_secret", "invalid_model_usage", "investigation_deadline", "series_or_case_deadline",
                    "clock_moved_backwards", "series_not_running",
                }:
                    raise GraphError(reason)
                last = ledger.state["attempts"][-1] if ledger.state["attempts"] else {}
                if last.get("http_status") in (401, 403, 429):
                    raise GraphError("foundation_authorization_or_quota_rejected")
                ledger.check(key)
        ledger.finish("COMPLETED_NEW_SERIES")
        if ledger.clock() >= ledger.state["deadline"]:
            ledger.finish("STOPPED_DEADLINE")
            raise GraphError("series_or_case_deadline")
    except GraphError as exc:
        # Preserve reservations and safe stable codes; do not continue after an
        # uncertain accounting write, expired deadline or exhausted budget.
        try:
            if ledger.state["status"] == "RUNNING":
                ledger.finish("STOPPED_" + exc.code)
        except GraphError:
            pass
        raise
    finally:
        store.close()


def source_identity(expected):
    if not re.fullmatch(r"[a-f0-9]{40}", expected):
        raise GraphError("invalid_source_sha")
    current = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()
    dirty = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    untracked = subprocess.run(["git", "ls-files", "--others", "--exclude-standard", "--", "src/agent_graph", "tools",
                                "experiments/evidence_refs_v2", "tests/graph/fixtures/pr31"],
                               cwd=ROOT, capture_output=True, text=True, check=True).stdout
    if expected != current or dirty or untracked:
        raise GraphError("runner_source_not_pinned_clean")
    if int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")) != 1:
        raise GraphError("actions_rerun_forbidden")
    return current


def save_report(path, report):
    # No raw provider body, request headers, credential/config environment or
    # private SQLite state is exported. Audit contains bounded typed actions only.
    data = json.dumps(report, ensure_ascii=False, indent=2)
    for name in (KEY_ENV, "GH_TOKEN", "GITHUB_TOKEN"):
        secret = os.environ.get(name)
        if secret and secret in data:
            raise GraphError("report_secret_detected")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(data + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["prepare", "initialize", "execute"], nargs="?", default="prepare")
    parser.add_argument("--source-sha")
    parser.add_argument("--repository", default="rengalaxies/agent", choices=["rengalaxies/agent"])
    parser.add_argument("--new-request-cap", type=int, default=0)
    parser.add_argument("--new-money-microrub", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("work/evidence-refs-v2/report.json"))
    args = parser.parse_args()
    packet = manifest()
    if args.mode == "prepare":
        save_report(args.output, packet)
        print("PREPARED_NO_MODEL_CALLS " + packet["manifest_digest"])
        return
    source = source_identity(args.source_sha or "")
    # An Actions run only executes accepted main code, never a PR/ref input.
    if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise GraphError("live_requires_main")
    backend = GitHubLedgerBackend(args.repository, os.environ.get("GH_TOKEN", ""))
    ledger = RunLedger(backend, packet, source)
    if args.mode == "initialize":
        ledger.initialize(args.new_request_cap, args.new_money_microrub)
        save_report(args.output, dict(status="INITIALIZED_NO_MODEL_CALLS", source_sha=source,
                                     request_cap=ledger.state["request_cap"], money_cap_micro=ledger.state["money_cap_micro"]))
        return
    if not os.environ.get(KEY_ENV):
        raise GraphError("missing_model_secret")
    run_id = os.environ.get("GITHUB_RUN_ID", "operator-command")
    started = backend.run_created_epoch(run_id) if str(run_id).isdigit() else time.time()
    ledger.claim(run_id, started_epoch=started)
    try:
        with tempfile.TemporaryDirectory(prefix="evidence-refs-v2-") as work:
            run_series(ledger, Path(work))
    finally:
        save_report(args.output, ledger.report())


if __name__ == "__main__":
    try:
        main()
    except GraphError as exc:
        print("STOPPED " + exc.code)
        raise SystemExit(1) from None
    except Exception:
        print("STOPPED invalid_runner_state")
        raise SystemExit(1) from None
