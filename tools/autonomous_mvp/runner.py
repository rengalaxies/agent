"""Batch 2B runner: one phase of one program revision for one model, exactly once.

    python -m tools.autonomous_mvp.runner preflight
    python -m tools.autonomous_mvp.runner execute --phase transport --model openai/gpt-oss-120b \
        --source-sha <accepted main SHA>
    python -m tools.autonomous_mvp.runner report --ledger-dir work/ledgers --output work/report

Live modes require the exact clean source SHA and the committed manifest.
Every case runs read -> ... -> finish through the protocol adapter with no
retries, a step limit and an absolute deadline. The oracle is never loaded here
except by `report`, after all requests are done.
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

from tools.autonomous_mvp import fixtures, ledger as ledger_mod, program as program_mod, protocol as protocol_mod
from tools.autonomous_mvp.transport import CloudRuTransport

ROOT = program_mod.ROOT
SAFE_TERMINALS = {"FINISHED", "ABSTAINED", "STEP_LIMIT", "DEADLINE", "TRANSPORT_FAILED", "ACTION_REJECTED_LIMIT",
                  "INPUT_LIMIT", "HARNESS_ERROR"}


class RunnerError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


class Breaker:
    """Phase-level stop rules from program.phase_rules.circuit_breaker."""

    def __init__(self):
        self.requests = self.failures = self.consecutive = 0

    def observe(self, attempt, family):
        if attempt["http_status"] in (401, 403):
            raise RunnerError("breaker_unauthorized")
        if family == "F10_timeout":
            return
        self.requests += 1
        if attempt["ok"]:
            self.consecutive = 0
            return
        self.failures += 1
        self.consecutive += 1
        if self.consecutive >= 5:
            raise RunnerError("breaker_consecutive_transport_failures")
        if self.requests >= 20 and self.failures / self.requests > 0.2:
            raise RunnerError("breaker_transport_failure_rate")


def run_case(case, repeat, *, protocol, transport, model, parameters, phase_deadline, work, breaker=None,
             attempts=None, mono=time.monotonic):
    """Run one case-run. Returns (attempts, result); both contain safe fields only.

    `attempts` is filled in place, so a caller that sees an exception still
    books every request that was actually sent.
    """
    started = mono()
    deadline = min(phase_deadline, started + case["limits"]["case_seconds"])
    max_steps = case["limits"]["max_model_steps"]
    attempts = [] if attempts is None else attempts
    steps, claims = [], []
    terminal, reason, final, invalid = None, None, None, 0
    repos = fixtures.materialize(case, work / "repos")
    session = protocol.open_case(case, repos, work, deadline_passed=lambda: mono() >= deadline)
    try:
        messages = session.initial_messages(max_steps)
        for index in range(max_steps):
            if mono() >= deadline:
                terminal, reason = "DEADLINE", "deadline_before_request"
                break
            payload = dict(model=model["id"], messages=messages, stream=False,
                           temperature=parameters["temperature"],
                           **{parameters["token_parameter"]: model["max_completion_tokens"]},
                           response_format=session.response_format())
            if len(json.dumps(payload, ensure_ascii=False).encode()) > parameters["max_prompt_bytes"]:
                terminal, reason = "INPUT_LIMIT", "max_prompt_bytes"
                break
            result = transport.complete(payload, deadline=min(deadline, mono() + parameters["request_timeout_seconds"]))
            late = mono() >= deadline
            attempt = dict(result.safe(), step=index, late=late)
            attempts.append(attempt)
            if breaker is not None:
                breaker.observe(attempt, case["family"])
            if late:
                # A response that arrives after the deadline is never shown to the executor.
                terminal, reason = "DEADLINE", "response_after_deadline" if result.ok else result.code
                break
            if not result.ok:
                terminal, reason = "TRANSPORT_FAILED", result.code
                break
            if result.finish_reason != "stop":
                outcome = protocol_mod.StepOutcome(action="<unparsed>", valid=False, layer="completion",
                                                   reason_code="finish_" + (result.finish_reason or "missing"))
                outcome.messages = [dict(role="user", content=json.dumps(dict(action_rejected=dict(
                    layer="completion", reason_code=outcome.reason_code), remaining_steps=max_steps - index - 1)))]
            else:
                outcome = session.step(result.content, remaining_steps=max_steps - index - 1)
            steps.append(dict(outcome.safe(), step=index))
            claims.extend(steps[-1]["claims"])
            messages = messages + outcome.messages
            if not outcome.valid:
                invalid += 1
                if invalid > parameters["max_invalid_actions_per_case"]:
                    terminal, reason = "ACTION_REJECTED_LIMIT", outcome.reason_code
                    break
            if outcome.terminal:
                terminal, final = outcome.terminal, outcome.final
                break
        else:
            terminal, reason = "STEP_LIMIT", "max_model_steps"
    except RunnerError:
        raise
    except fixtures.FixtureError:
        raise
    except Exception as exc:  # A protocol bug is not model behaviour; record only the class name.
        terminal, reason = "HARNESS_ERROR", type(exc).__name__
    finally:
        session.close()
    result = dict(case_id=case["case_id"], repeat=repeat, family=case["family"], split=case["split"],
                  terminal=terminal, reason_code=reason, steps=steps, claims=claims, final=final,
                  invalid_actions=invalid, requests=len(attempts), wall_seconds=round(mono() - started, 3),
                  deadline_seconds=case["limits"]["case_seconds"], max_model_steps=max_steps,
                  commits={k: v["commit"] for k, v in repos.items() if v["available"]},
                  protocol_id=protocol.protocol_id)
    if terminal not in SAFE_TERMINALS:
        raise RunnerError("invalid_terminal")
    return attempts, result


def phase_basic(state):
    """Transport and action rates of one finished ledger, for phase gates."""
    attempts = [a for r in state["case_runs"] for a in r["attempts"]]
    steps = [s for r in state["case_runs"] if r["result"] for s in r["result"]["steps"]]
    ok = sum(a["ok"] for a in attempts)
    valid = sum(s["valid"] for s in steps)
    full = sum(1 for r in state["case_runs"] if r["result"] and r["result"]["terminal"] in ("FINISHED", "ABSTAINED")
               and all(a["ok"] for a in r["attempts"]) and all(s["valid"] for s in r["result"]["steps"]))
    return dict(requests=len(attempts), transport_ok=ok, actions=len(steps), valid_actions=valid,
                full_cycles=full, transport_success=ok / len(attempts) if attempts else 0.0,
                action_validity=valid / len(steps) if steps else 0.0)


def requirement_met(phase, required_state):
    if required_state is None or required_state["status"] != "COMPLETED":
        return False
    basic = phase_basic(required_state)
    if required_state["phase"] == "transport":
        return basic["full_cycles"] >= 2
    if required_state["phase"] == "development":
        return basic["transport_success"] >= 0.80 and basic["action_validity"] >= 0.60
    return True


def execute_phase(phase, model_id, *, program, cases, manifest_digest, source_sha, transport, backend_for,
                  work, actions_run="local", protocol=None, clock=time.time, mono=time.monotonic):
    spec = program["phases"][phase]
    model = next((m for m in program["models"] if m["id"] == model_id), None)
    if model is None:
        raise RunnerError("model_not_in_program")
    protocol = protocol or protocol_mod.load(program["protocol"]["evaluation" if phase.startswith("evaluation")
                                                                  else phase])
    if phase.startswith("evaluation") and (protocol.interim or not set(protocol_mod.CAPABILITIES) <= protocol.capabilities):
        raise RunnerError("evaluation_requires_full_protocol")
    if spec["requires"]:
        required = ledger_mod.Ledger(backend_for(spec["requires"]), dict(
            run_id=program["run_id"], phase=spec["requires"], model=model_id, manifest_digest=manifest_digest,
            source_sha=source_sha), clock=clock).state
        if not requirement_met(phase, required):
            raise RunnerError("phase_requirement_not_met:" + spec["requires"])
    available = transport.list_models(deadline=mono() + 30)
    if not available["ok"]:
        raise RunnerError("model_list_" + available["code"])
    if model_id not in available["models"]:
        raise RunnerError("model_not_available")
    runs = program_mod.phase_cases(program, cases, phase)
    worst = program_mod.worst_micro_per_request(program, model)
    max_requests = sum(c["limits"]["max_model_steps"] for c, _ in runs)
    led = ledger_mod.Ledger(backend_for(phase), dict(
        run_id=program["run_id"], phase=phase, model=model_id, manifest_digest=manifest_digest, source_sha=source_sha,
        request_cap=max_requests, money_cap_micro=max_requests * worst, worst_micro_per_request=worst,
        price=model["price"], phase_seconds=spec["phase_seconds"]), clock=clock)
    led.claim(actions_run, started_epoch=clock())
    phase_deadline = mono() + spec["phase_seconds"]
    breaker = Breaker()
    try:
        for case, repeat in runs:
            led.check()
            key = led.start_case(case["case_id"], repeat, case["limits"]["max_model_steps"])
            case_work = work / f"{case['case_id']}-{repeat}"
            case_work.mkdir(parents=True)
            attempts = []
            try:
                _, result = run_case(case, repeat, protocol=protocol, transport=transport, model=model,
                                     parameters=program["parameters"], phase_deadline=phase_deadline,
                                     work=case_work, breaker=breaker, attempts=attempts, mono=mono)
            except RunnerError as exc:
                led.finish_case(key, attempts, dict(case_id=case["case_id"], repeat=repeat, family=case["family"],
                                                    split=case["split"], terminal="TRANSPORT_FAILED",
                                                    reason_code=exc.code, steps=[], claims=[], final=None,
                                                    invalid_actions=0, requests=len(attempts)))
                raise
            led.finish_case(key, attempts, result)
            shutil.rmtree(case_work, ignore_errors=True)
            if result["terminal"] == "HARNESS_ERROR":
                raise RunnerError("harness_error")
        led.finish("COMPLETED")
    except (RunnerError, ledger_mod.LedgerError, fixtures.FixtureError) as exc:
        try:
            led.finish("STOPPED_" + exc.code)
        except ledger_mod.LedgerError:
            pass
        raise
    return led.state


def source_identity(expected):
    if not re.fullmatch(r"[a-f0-9]{40}", expected or ""):
        raise RunnerError("invalid_source_sha")

    def git(*args):
        return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout

    if git("rev-parse", "HEAD").strip() != expected or git("status", "--porcelain", "--untracked-files=no"):
        raise RunnerError("runner_source_not_pinned_clean")
    if git("ls-files", "--others", "--exclude-standard", "--", "src", "tools", "experiments/autonomous_mvp").strip():
        raise RunnerError("runner_source_not_pinned_clean")
    if int(os.environ.get("GITHUB_RUN_ATTEMPT", "1")) != 1:
        raise RunnerError("actions_rerun_forbidden")
    return expected


def committed_manifest(name):
    current = program_mod.manifest(name)
    path = program_mod.PROGRAMS / name / "manifest.json"
    stored = json.loads(path.read_text(encoding="utf-8"))
    if stored["manifest_digest"] != current["manifest_digest"]:
        raise RunnerError("manifest_stale_or_changed")
    return current


def model_slug(model_id):
    return re.sub(r"[^A-Za-z0-9_.-]", "--", model_id)


def save_safe(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    for name in ledger_mod.SECRET_ENVS:
        secret = os.environ.get(name)
        if secret and len(secret) >= 8 and secret in text:
            raise RunnerError("report_secret_detected")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text + "\n", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["preflight", "execute", "report"])
    parser.add_argument("--program", default="2b-r1")
    parser.add_argument("--phase")
    parser.add_argument("--model")
    parser.add_argument("--source-sha")
    parser.add_argument("--repository", default="rengalaxies/agent", choices=["rengalaxies/agent"])
    parser.add_argument("--ledger-dir", type=Path, help="file ledgers instead of the GitHub accounting branch")
    parser.add_argument("--output", type=Path, default=Path("work/autonomous-mvp"))
    args = parser.parse_args(argv)
    base, program, cases = program_mod.load(args.program)
    if args.mode == "report":
        from tools.autonomous_mvp import scorer
        if args.ledger_dir:
            states = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(args.ledger_dir.rglob("*.json"))]
            states = [s.get("state", s) for s in states]
        else:
            # Authoritative copies from the accounting branches, read-only.
            states = []
            for m in program["models"]:
                for phase in program["phases"]:
                    _, state = ledger_mod.GitHubContentsBackend(
                        args.repository, os.environ.get("GH_TOKEN", ""),
                        f"experiment-state/autonomous-mvp/{program['run_id']}/{model_slug(m['id'])}",
                        f"{phase}.json").read()
                    if state is not None:
                        states.append(state)
        report = scorer.report(program, cases, program_mod.load_oracle(base), states)
        save_safe(args.output / "report.json", report)
        (args.output / "report.md").write_text(scorer.markdown(report), encoding="utf-8")
        print("REPORT " + " ".join(f"{m}={v['verdict']}" for m, v in report["models"].items()))
        return
    manifest = committed_manifest(args.program)
    transport = CloudRuTransport(endpoint=program["provider"]["chat_endpoint"],
                                 key_env=program["provider"]["credential_env"])
    if args.mode == "preflight":
        listed = transport.list_models(deadline=time.monotonic() + 30)
        out = dict(mode="preflight", tokens_spent=0, http_status=listed["http_status"], code=listed["code"],
                   manifest_digest=manifest["manifest_digest"],
                   models={m["id"]: m["id"] in listed["models"] for m in program["models"]})
        save_safe(args.output / "preflight.json", out)
        print("PREFLIGHT " + json.dumps(out, sort_keys=True))
        if not listed["ok"]:
            raise RunnerError("preflight_" + listed["code"])
        return
    if args.phase not in program["phases"] or not args.model:
        raise RunnerError("phase_and_model_required")
    source = source_identity(args.source_sha)
    if os.environ.get("GITHUB_ACTIONS") == "true" and os.environ.get("GITHUB_REF") != "refs/heads/main":
        raise RunnerError("live_requires_main")
    slug = model_slug(args.model)
    if args.ledger_dir:
        def backend_for(phase):
            return ledger_mod.FileBackend(args.ledger_dir / slug / f"{phase}.json")
    else:
        token = os.environ.get("GH_TOKEN", "")

        def backend_for(phase):
            return ledger_mod.GitHubContentsBackend(
                args.repository, token, f"experiment-state/autonomous-mvp/{program['run_id']}/{slug}", f"{phase}.json")
    state = None
    try:
        with tempfile.TemporaryDirectory(prefix="amvp-2b-") as work:
            state = execute_phase(args.phase, args.model, program=program, cases=cases,
                                  manifest_digest=manifest["manifest_digest"], source_sha=source, transport=transport,
                                  backend_for=backend_for, work=Path(work),
                                  actions_run=os.environ.get("GITHUB_RUN_ID", "local"))
    finally:
        try:
            current = ledger_mod.Ledger(backend_for(args.phase), dict(
                run_id=program["run_id"], phase=args.phase, model=args.model,
                manifest_digest=manifest["manifest_digest"], source_sha=source)).state
        except ledger_mod.LedgerError:
            current = state
        if current is not None:
            save_safe(args.output / "ledgers" / slug / f"{args.phase}.json", current)
    print(f"PHASE {args.phase} {args.model} {state['status'] if state else 'STOPPED'}")


if __name__ == "__main__":
    try:
        main()
    except (RunnerError, ledger_mod.LedgerError, fixtures.FixtureError, protocol_mod.ProtocolUnavailable) as exc:
        print("STOPPED " + exc.code)
        raise SystemExit(1) from None
