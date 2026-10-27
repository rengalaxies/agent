"""Write the change corpus of a readiness revision and its evaluator-only oracle.

Output is committed. ``test_readiness_corpus`` regenerates it and requires
byte equality, so a changed scenario is always a reviewed diff. The oracle is
built by executing the fixture consumers (``oracle.build_oracle``); the service
under test, the baseline and any model never take part in it.

A historical revision is only checked (``--check --program 6-r1``): its committed
files must still be what its configuration generates, byte for byte.

Usage: python -m tools.autonomous_mvp.readiness.generate [--program REVISION] [--check]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tools.autonomous_mvp.readiness import oracle as oracle_mod, program as program_mod, world

ROOT = Path(__file__).resolve().parents[3]


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def outputs(revision=world.CURRENT) -> dict[str, str]:
    files = {}
    for split in world.SPLITS:
        oracle = {}
        for change, facts in world.changes(split, revision):
            files[f"changes/{split}/{change['change_id']}.json"] = dump(change)
            oracle[change["change_id"]] = oracle_mod.build_oracle(change, facts)
        files[f"oracle/{split}.json"] = dump(dict(
            schema="readiness-oracle-1", program=revision, split=split,
            scope="evaluator only; never passed to the service, the baseline, a model or its configuration",
            changes=oracle))
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the committed corpus differs")
    parser.add_argument("--program", default=world.CURRENT, help=f"revision (default {world.CURRENT})")
    args = parser.parse_args()
    if args.program != world.CURRENT and not args.check:
        raise SystemExit(f"REFUSED historical_revision: {args.program} is never regenerated")
    base = program_mod.program_dir(args.program)
    stale = []
    for relative, text in outputs(args.program).items():
        path = base / relative
        if args.check:
            if not path.exists() or path.read_bytes().replace(b"\r\n", b"\n") != text.encode("utf-8"):
                stale.append(relative)
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))
    if args.check:
        if stale:
            raise SystemExit("CORPUS_STALE " + ",".join(stale))
        print("CORPUS_CURRENT")
        return
    print(f"CORPUS_WRITTEN {base.relative_to(ROOT).as_posix()}")


if __name__ == "__main__":
    main()
