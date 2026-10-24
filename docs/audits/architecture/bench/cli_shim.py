"""Run the core CLI as a subprocess would, plus peak working set on exit."""
import atexit
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "core", "src"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def _peak():
    out = os.environ.get("BENCH_PEAK_FILE")
    if out:
        import psutil
        with open(out, "w") as f:
            f.write(str(psutil.Process().memory_info().peak_wset))


atexit.register(_peak)
import bench_shim  # noqa: E402,F401
from agent_graph.__main__ import main  # noqa: E402

code = main(sys.argv[1:])
sys.stdout.flush()
sys.exit(code)
