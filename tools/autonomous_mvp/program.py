"""Load a 2B program revision and freeze it into a manifest before any run.

The manifest pins program parameters, thresholds, every case and oracle file,
the runner code, the protocol fingerprint and the volume/cost estimate. Text
files are hashed with LF line endings so a Windows checkout and the Linux runner
produce the same digest. The live runner recomputes the manifest and refuses to
start when it differs from the committed one.
"""
from __future__ import annotations

import argparse
from decimal import ROUND_CEILING, Decimal
import hashlib
import json
from pathlib import Path

from tools.autonomous_mvp.ledger import micro_cost

ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = ROOT / "experiments/autonomous_mvp/programs"
SPLITS = ("transport", "development", "evaluation")


def text_sha256(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def load(name="2b-r1"):
    base = PROGRAMS / name
    program = json.loads((base / "program.json").read_text(encoding="utf-8"))
    cases = {}
    for split in SPLITS:
        for path in sorted((base / "cases" / split).glob("*.json")):
            case = json.loads(path.read_text(encoding="utf-8"))
            if case["split"] != split or case["case_id"] != path.stem:
                raise ValueError("case_file_mismatch")
            cases[case["case_id"]] = case
    return base, program, cases


def load_oracle(base):
    oracle = {}
    for split in SPLITS:
        data = json.loads((base / "oracle" / f"{split}.json").read_text(encoding="utf-8"))
        oracle.update(data["cases"])
    return oracle


def phase_cases(program, cases, phase):
    spec = program["phases"][phase]
    selected = sorted((c for c in cases.values() if c["split"] == spec["split"]), key=lambda c: c["case_id"])
    return [(c, r) for c in selected for r in range(1, spec["repeat"] + 1)]


def worst_micro_per_request(program, model):
    p = program["parameters"]
    return micro_cost(p["max_prompt_bytes"] + p["framing_tokens"], model["max_completion_tokens"], model["price"])


def rub(micro):
    return str((Decimal(micro) / Decimal(1_000_000)).quantize(Decimal("0.01"), rounding=ROUND_CEILING))


def estimate(program, cases):
    """Finite program volume, worst-case caps and expected cost per (phase, model)."""
    a = program["estimate_assumptions"]
    rows, totals = [], dict(max_requests=0, expected_requests=0, cap_micro=0, expected_micro=0)
    for model in program["models"]:
        completion = a["mean_completion_tokens_per_request"]["reasoning_model" if model["reasoning_model"] else "other"]
        per_request = micro_cost(a["mean_prompt_tokens_per_request"], completion, model["price"])
        worst = worst_micro_per_request(program, model)
        for phase in program["phases"]:
            runs = phase_cases(program, cases, phase)
            max_requests = sum(c["limits"]["max_model_steps"] for c, _ in runs)
            expected_requests = sum(min(a["mean_requests_per_case_run"], c["limits"]["max_model_steps"]) for c, _ in runs)
            row = dict(model=model["id"], phase=phase, case_runs=len(runs), max_requests=max_requests,
                       expected_requests=expected_requests, worst_micro_per_request=worst,
                       money_cap_micro=max_requests * worst, expected_micro=expected_requests * per_request)
            row["headroom_ratio"] = round(row["money_cap_micro"] / row["expected_micro"], 2)
            row["money_cap_rub"], row["expected_rub"] = rub(row["money_cap_micro"]), rub(row["expected_micro"])
            rows.append(row)
            totals["max_requests"] += max_requests
            totals["expected_requests"] += expected_requests
            totals["cap_micro"] += row["money_cap_micro"]
            totals["expected_micro"] += row["expected_micro"]
    totals.update(cap_rub=rub(totals["cap_micro"]), expected_rub=rub(totals["expected_micro"]),
                  basis="published RUB prices incl. 22% VAT (models.json); caps reserve every allowed request at "
                        "max_prompt_bytes+framing input tokens and max_completion_tokens output; expected cost uses "
                        "estimate_assumptions. Billing is not visible to the runner: actual cost NOT_MEASURED.")
    return dict(rows=rows, totals=totals)


def code_files():
    files = sorted((ROOT / "tools/autonomous_mvp").glob("*.py")) + sorted((ROOT / "src/agent_graph").glob("*.py"))
    files.append(ROOT / ".github/workflows/autonomous-mvp-model.yml")
    return {str(p.relative_to(ROOT)).replace("\\", "/"): text_sha256(p) for p in files if p.exists()}


def protocol_fingerprints(program):
    from tools.autonomous_mvp import protocol
    out = {}
    for phase, protocol_id in sorted(program["protocol"].items()):
        if phase == "note":
            continue
        try:
            out[phase] = protocol.load(protocol_id).fingerprint()
        except protocol.ProtocolUnavailable as exc:
            out[phase] = dict(protocol_id=protocol_id, available=False, code=exc.code)
    return out


def manifest(name="2b-r1"):
    base, program, cases = load(name)
    files = {str(p.relative_to(base)).replace("\\", "/"): text_sha256(p) for p in sorted(base.rglob("*.json"))
             if p.name != "manifest.json"}
    by_split = {s: sorted(k for k, c in cases.items() if c["split"] == s) for s in SPLITS}
    packet = dict(schema="amvp-manifest-1", program=program, program_files_sha256=files, cases=by_split,
                  code_sha256=code_files(), protocols=protocol_fingerprints(program),
                  volume_and_cost=estimate(program, cases),
                  oracle_scope="evaluator only; never passed to the protocol, the model or its configuration")
    return dict(packet, manifest_digest=digest(packet))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--program", default="2b-r1")
    parser.add_argument("--check", action="store_true", help="fail if the committed manifest is stale")
    args = parser.parse_args()
    data = manifest(args.program)
    path = PROGRAMS / args.program / "manifest.json"
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.check:
        if not path.exists() or json.loads(path.read_text(encoding="utf-8"))["manifest_digest"] != data["manifest_digest"]:
            raise SystemExit("MANIFEST_STALE " + data["manifest_digest"])
        print("MANIFEST_CURRENT " + data["manifest_digest"])
        return
    path.write_bytes(text.encode("utf-8"))
    t = data["volume_and_cost"]["totals"]
    print(f"MANIFEST {data['manifest_digest']} max_requests={t['max_requests']} expected_requests="
          f"{t['expected_requests']} cap_rub={t['cap_rub']} expected_rub={t['expected_rub']}")


if __name__ == "__main__":
    main()
