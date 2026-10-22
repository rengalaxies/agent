"""Run tests/graph of a checkout on Windows through bench_shim.

usage: run_tests_shim.py REPO_ROOT [pattern]
Tests that need Linux openat/O_NOFOLLOW/flock semantics can fail here; compare
the failing set between two checkouts rather than reading it as absolute.
"""
import os
import sys
import unittest

repo = os.path.abspath(sys.argv[1])
sys.path[:0] = [os.path.join(repo, "src"), repo]
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
import bench_shim  # noqa: E402,F401
import agent_graph  # noqa: E402

assert agent_graph.__file__.startswith(repo), agent_graph.__file__
os.chdir(repo)
suite = unittest.defaultTestLoader.discover(os.path.join(repo, "tests", "graph"),
                                            pattern=sys.argv[2] if len(sys.argv) > 2 else "test*.py",
                                            top_level_dir=repo)
result = unittest.TextTestRunner(verbosity=0).run(suite)
for kind, items in (("FAIL", result.failures), ("ERROR", result.errors)):
    for test, _ in items:
        print(kind, test.id())
print("PROFILE", agent_graph.PROFILE, "ran", result.testsRun)
