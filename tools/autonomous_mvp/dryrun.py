"""Offline dry run of the whole 2B program through the live code path.

    python -m tools.autonomous_mvp.dryrun --behaviour follow --output work/dryrun

`ScriptedAgentTransport` stands where `CloudRuTransport` stands in a live run. The
runner, the real 2A executor (`run_investigation`), the constitution, the evidence
checks, the ledger and the scorer are the same code. Only the replies are scripted.

The script reads the oracle, so a dry run proves the plumbing and the scorer, never
model quality. Behaviours:

* follow: reads callsite and provider files, proposes each required claim (facts in
  the static profile, hypotheses beyond it), finishes or abstains. Adversarial cases
  are played adversarially first: forged evidence_refs in F06, a read of an unlisted
  path in F07. F09 runs out of steps; F10 sleeps past the case deadline.
* decoy_taker: also proposes every forbidden claim as a fact and as a hypothesis.
* broken: answers with invalid JSON until the invalid-action limit ends the case.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import tempfile
import time

from tools.autonomous_mvp import ledger as ledger_mod, program as program_mod, runner, scorer
from tools.autonomous_mvp.transport import TransportResult, reply

BEHAVIOURS = ("follow", "decoy_taker", "broken")
KEY = re.compile(r"\[jira ([A-Z]+-\d+)\]")


def _action(name, **fields):
    return json.dumps(dict(action=dict(name=name, **fields)))


def _claim_fields(c):
    return {k: c[k] for k in ("consumer_repository", "consumer_service", "provider_service", "method", "path_template")}


def _hypothesis_fields(c, statement):
    return dict(consumer_service=c["consumer_service"], provider_service=c["provider_service"], method=c["method"],
                route=c["path_template"], statement=statement)


class ScriptedAgentTransport:
    """A transport whose replies follow a per-case script. Sends nothing over the network."""

    def __init__(self, cases, oracle, *, models, behaviour="follow"):
        if behaviour not in BEHAVIOURS:
            raise ValueError("unknown_behaviour")
        self.by_key = {c["task"]["key"]: c for c in cases.values()}
        self.oracle, self.models, self.behaviour = oracle, list(models), behaviour
        self.sent = 0

    def list_models(self, *, deadline):
        return dict(ok=True, code="ok", http_status=200, models=sorted(self.models))

    def complete(self, payload, *, deadline):
        self.sent += 1
        messages = payload["messages"]
        task = json.loads(messages[1]["content"])
        case = self.by_key[KEY.search(task["task"]).group(1)]
        if case["family"] == "F10_timeout":
            time.sleep(max(0.0, deadline - time.monotonic()) + 0.05)
            return TransportResult(ok=False, code="timeout")
        step = sum(1 for m in messages if m["role"] == "assistant")
        refs = [json.loads(m["content"])["tool_result"].get("untrusted_source", {}).get("evidence_ref")
                for m in messages[2:] if m["role"] == "user"]
        plan = self._plan(case, task["sources"])
        if step >= len(plan):
            content = _action("finish", outcome="abstain", reason="insufficient_evidence")
        else:
            content = plan[step](refs)
        size = len(json.dumps(payload).encode())
        return reply(content, prompt_tokens=size // 4, completion_tokens=max(1, len(content) // 4))

    def _plan(self, case, sources):
        """List of callables(refs so far) -> reply content, one per step."""
        if self.behaviour == "broken":
            return [lambda refs: "{not json"] * 3
        o = self.oracle[case["case_id"]]
        plan = []
        if case["family"] == "F06_forged_refs":
            claim = _claim_fields(o["required_claims"][0])
            plan.append(lambda refs, claim=claim: _action("propose_dependency", claim=claim,
                                                          evidence_refs=o["forged_refs"]))
        if case["family"] == "F07_prompt_injection":
            plan.append(lambda refs: _action("read_source", source_id="../../../etc/passwd", start_line=1, end_line=2))
        targets = o["required_claims"] + o["allowed_claims"]  # allowed claims are true edges too
        if self.behaviour == "decoy_taker":
            targets = targets + o["forbidden_claims"]
        proposed = False
        for c in targets:
            consumer = [s for s in sources if s["repository"] == c["consumer_service"] and s["lines"]
                        and not s["path"].startswith("tests/") and not s["path"].endswith(".md")]
            provider = [s for s in sources if s["repository"] == c["provider_service"] and s["path"].endswith("/api.py")]
            wanted = consumer + provider
            if not wanted:
                continue
            first = len([p for p in plan if getattr(p, "reads", False)])
            for s in wanted:
                def read(refs, s=s):
                    return _action("read_source", source_id=s["source_id"], start_line=1, end_line=min(60, s["lines"]))
                read.reads = True
                plan.append(read)
            span = (first, first + len(wanted))
            fact = c["max_confidence"] == "CONFIRMED_WITHIN_PROFILE"

            def propose(refs, c=c, span=span, fact=fact):
                cited = [r for r in refs if r][span[0]:span[1]]
                if fact:
                    return _action("propose_dependency", claim=_claim_fields(c), evidence_refs=cited)
                return _action("propose_hypothesis", claim=_hypothesis_fields(
                    c, "The call goes through code the static profile does not resolve."),
                    evidence_refs=cited, unknowns=["helper_semantics_unknown"])
            plan.append(propose)
            if self.behaviour == "decoy_taker" and c in o["forbidden_claims"]:
                plan.append(lambda refs, c=c, span=span: _action("propose_hypothesis", claim=_hypothesis_fields(
                    c, "Same route, so probably the same provider."),
                    evidence_refs=[r for r in refs if r][span[0]:span[1]], unknowns=["model_hypothesis_unverified"]))
            proposed = True
        plan.append(lambda refs: _action("finish", outcome="complete" if proposed else "abstain",
                                         reason="done" if proposed else "insufficient_evidence"))
        return plan


def dry_run(program, cases, oracle, *, model_id, behaviour, work, phases=None):
    """Run the phases in order for one model with file ledgers; return the scorer report."""
    transport = ScriptedAgentTransport(cases, oracle, models=[model_id], behaviour=behaviour)
    ledgers = Path(work) / "ledgers"

    def backend_for(phase):
        return ledger_mod.FileBackend(ledgers / runner.model_slug(model_id) / f"{phase}.json")

    states = []
    for phase in phases or program["phases"]:
        try:
            states.append(runner.execute_phase(
                phase, model_id, program=program, cases=cases, manifest_digest="dry-run", source_sha="0" * 40,
                transport=transport, backend_for=backend_for, work=Path(work) / phase))
        except runner.RunnerError as exc:
            if not exc.code.startswith("phase_requirement_not_met"):
                raise
            break  # the program rule stops here, as it would live
    single = dict(program, models=[m for m in program["models"] if m["id"] == model_id])
    return scorer.report(single, cases, oracle, states), states, transport.sent


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--program", default="2b-r1")
    parser.add_argument("--model", default="openai/gpt-oss-120b")
    parser.add_argument("--behaviour", choices=BEHAVIOURS, default="follow")
    parser.add_argument("--output", type=Path, default=Path("work/autonomous-mvp/dryrun"))
    args = parser.parse_args(argv)
    base, program, cases = program_mod.load(args.program)
    oracle = program_mod.load_oracle(base)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="amvp-dryrun-") as work:
        report, states, sent = dry_run(program, cases, oracle, model_id=args.model, behaviour=args.behaviour, work=work)
    runner.save_safe(args.output / "report.json", report)
    (args.output / "report.md").write_bytes(scorer.markdown(report).encode("utf-8"))
    verdict = report["models"][args.model]["verdict"]
    print(f"DRY_RUN behaviour={args.behaviour} model={args.model} phases={[s['phase'] + ':' + s['status'] for s in states]} "
          f"scripted_replies={sent} verdict={verdict} seconds={time.monotonic() - started:.0f}")


if __name__ == "__main__":
    main()
