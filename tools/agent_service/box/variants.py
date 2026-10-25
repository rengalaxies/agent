"""Test-only release variants for update/rollback acceptance. Never shipped as a product change.

    python variants.py patch-version REPO 0.1.1      a newer release with the same state schema
    python variants.py schema-bump REPO              service store schema 1 -> 2 with an additive migration

Each command edits a scratch checkout (a ``git worktree`` of the commit under
test) so the acceptance can build a real second release from it. The edits
are exact text replacements: if the source they expect has changed, the
command fails instead of building a variant that tests nothing.
"""

from __future__ import annotations

import argparse
from pathlib import Path

QUEUE = Path("src/agent_service/queue.py")
OLD_CHECK = """            elif row[0] != str(SCHEMA_VERSION):
                raise ValueError("unsupported_state_schema")"""
NEW_CHECK = """            elif row[0] == "1" and SCHEMA_VERSION == 2:  # box acceptance variant: additive v1 -> v2
                c.execute("CREATE TABLE IF NOT EXISTS box_variant(note TEXT)")
                c.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
            elif row[0] != str(SCHEMA_VERSION):
                raise ValueError("unsupported_state_schema")"""


def _replace(path: Path, old: str, new: str):
    text = path.read_bytes().decode("utf-8")
    if text.count(old) != 1:
        raise SystemExit(f"{path}: expected exactly one occurrence of the text to replace")
    path.write_bytes(text.replace(old, new).encode("utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["patch-version", "schema-bump"])
    parser.add_argument("repo", type=Path)
    parser.add_argument("version", nargs="?")
    args = parser.parse_args(argv)
    if args.command == "patch-version":
        (args.repo / "infra/agent_service/VERSION").write_bytes(f"{args.version}\n".encode())
    else:
        _replace(args.repo / QUEUE, "SCHEMA_VERSION = 1\n", "SCHEMA_VERSION = 2\n")
        _replace(args.repo / QUEUE, OLD_CHECK, NEW_CHECK)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
