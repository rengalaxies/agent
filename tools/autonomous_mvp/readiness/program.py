"""Freeze program 6-r1 into a manifest before any run; ``--check`` refuses a stale one.

The manifest pins ``program.json`` (units, splits, outcome rules, thresholds,
configurations), every change and oracle file, the code that runs or scores
(this package, the service, the core, the stand plumbing, the constitution)
and the baseline protocol fingerprint. Text is hashed with LF line endings so a
Windows checkout and a Linux runner agree. Ledgers in ``results/`` are outputs
and are not part of the manifest.

The held-out runner refuses to start unless the committed manifest equals the
recomputed one, and never overwrites a held-out ledger.

Usage:
  python -m tools.autonomous_mvp.readiness.program            # write manifest.json
  python -m tools.autonomous_mvp.readiness.program --check    # MANIFEST_CURRENT <digest> or exit 1
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
PROGRAM_DIR = ROOT / "experiments/autonomous_mvp/programs/6-r1"
SPLITS = ("development", "heldout")


def text_sha256(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
                          ).hexdigest()


def load(base=None):
    base = Path(base or PROGRAM_DIR)
    program = json.loads((base / "program.json").read_text(encoding="utf-8"))
    changes = {}
    for split in SPLITS:
        for path in sorted((base / "changes" / split).glob("*.json")):
            changes[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return base, program, changes


def load_oracle(split, base=None):
    """Evaluator only: the scorer and the corpus tests read this, nothing that runs the service or baseline."""
    base = Path(base or PROGRAM_DIR)
    return json.loads((base / "oracle" / f"{split}.json").read_text(encoding="utf-8"))["changes"]


def code_files():
    files = sorted((ROOT / "tools/autonomous_mvp/readiness").glob("*.py"))
    files += [ROOT / "tools/autonomous_mvp/scorer.py", ROOT / "tools/autonomous_mvp/transport.py"]
    files += sorted((ROOT / "src/agent_service").rglob("*.py")) + sorted((ROOT / "src/agent_graph").glob("*.py"))
    files += [ROOT / "examples/orders_reporting/stand.py", ROOT / "constitutions/agent-service-v1.yaml"]
    return {p.relative_to(ROOT).as_posix(): text_sha256(p) for p in files if p.exists()}


def manifest(base=None):
    from tools.autonomous_mvp.readiness import baseline

    base, program, changes = load(base)
    files = {p.relative_to(base).as_posix(): text_sha256(p) for p in sorted(base.rglob("*.json"))
             if p.name != "manifest.json" and p.relative_to(base).parts[0] != "results"}
    packet = dict(schema="readiness-manifest-1", program=program, program_files_sha256=files,
                  changes={s: sorted(k for k, c in changes.items() if c["split"] == s) for s in SPLITS},
                  code_sha256=code_files(), baseline_protocol=baseline.fingerprint(),
                  oracle_scope="evaluator only; never passed to the service, the baseline, a model or its configuration")
    return dict(packet, manifest_digest=digest(packet))


def status(base=None):
    """(committed manifest equals the recomputed one, recomputed digest)."""
    data = manifest(base)
    path = Path(base or PROGRAM_DIR) / "manifest.json"
    stored = json.loads(path.read_text(encoding="utf-8")).get("manifest_digest") if path.exists() else None
    return stored == data["manifest_digest"], data["manifest_digest"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="fail if the committed manifest is stale")
    args = parser.parse_args()
    if args.check:
        current, value = status()
        if not current:
            raise SystemExit("MANIFEST_STALE " + value)
        print("MANIFEST_CURRENT " + value)
        return
    data = manifest()
    (PROGRAM_DIR / "manifest.json").write_bytes(
        (json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"))
    print("MANIFEST " + data["manifest_digest"])


if __name__ == "__main__":
    main()
