"""Offline helpers. Every test drives the real runner and the real 2A executor;
only the transport is scripted (tools.autonomous_mvp.dryrun or ScriptedTransport)."""
from __future__ import annotations

import json
from pathlib import Path
import time

from tools.autonomous_mvp import dryrun, ledger, program as program_mod, runner

BASE, PROGRAM, CASES = program_mod.load()
ORACLE = program_mod.load_oracle(BASE)
MODEL = PROGRAM["models"][0]["id"]
# S01, one development case and one evaluation case of every family: the quick end-to-end corpus.
SMALL = {k: CASES[k] for k in ["S01", "D01"] + sorted(
    {c["family"]: k for k, c in sorted(CASES.items(), reverse=True) if c["split"] == "evaluation"}.values())}


def one_model_program(**phase_overrides):
    program = json.loads(json.dumps(PROGRAM))
    program["models"] = [program["models"][0]]
    for name, values in phase_overrides.items():
        program["phases"][name].update(values)
    return program


def subset(*case_ids):
    return {k: CASES[k] for k in case_ids}


def run_phase(directory, phase, transport, *, program=None, cases=None):
    """execute_phase exactly as the live runner calls it, with file ledgers in `directory`."""
    work = Path(directory) / f"work-{phase}-{time.monotonic_ns()}"
    return runner.execute_phase(phase, MODEL, program=program or one_model_program(), cases=cases or CASES,
                                manifest_digest="m" * 64, source_sha="a" * 40, transport=transport,
                                backend_for=lambda p: ledger.FileBackend(Path(directory) / "ledgers" / f"{p}.json"),
                                work=work)


def agent(behaviour="follow", cases=None):
    return dryrun.ScriptedAgentTransport(cases or CASES, ORACLE, models=[MODEL], behaviour=behaviour)


def stored(directory, phase):
    return json.loads((Path(directory) / "ledgers" / f"{phase}.json").read_text())["state"]
