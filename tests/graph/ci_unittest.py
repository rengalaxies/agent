"""Run unittest like `python -m unittest ...` and report failures as GitHub annotations.

Job logs need a signed-in viewer, annotations are public. For each failed or errored
test (at most MAX) this prints `::error title=<test id>::<last traceback lines>` so a
red run is readable from the check-run annotations API. Runs no secrets: CI test jobs
receive none. Exit status is 1 when any test fails, as with unittest.

Usage: python tests/graph/ci_unittest.py discover -s tests/graph -t . -v
"""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

# Run as a script, Python puts tests/graph first on sys.path; its test_*.py names would
# then shadow same-named modules elsewhere under tests/ during discovery.
if sys.path and Path(sys.path[0]).resolve() == Path(__file__).resolve().parent:
    sys.path.pop(0)

MAX = 10
LINES = 8


def _escape(text: str) -> str:
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def annotations(result, limit=MAX, lines=LINES):
    items = [("ERROR", t, tb) for t, tb in result.errors] + [("FAIL", t, tb) for t, tb in result.failures]
    out = []
    for kind, test, traceback in items[:limit]:
        tail = "\n".join(traceback.strip().splitlines()[-lines:])
        title = _escape(f"{kind} {test.id()}").replace(",", "%2C").replace(":", "%3A")
        out.append(f"::error title={title}::{_escape(tail)}")
    if len(items) > limit:
        out.append(f"::error title=more failures::{len(items) - limit} more not shown; total {len(items)}")
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    program = unittest.main(module=None, argv=["python -m unittest", *argv], exit=False)
    result = program.result
    for line in annotations(result):
        print(line, flush=True)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
