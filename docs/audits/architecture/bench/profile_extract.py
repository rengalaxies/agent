"""cProfile of discovery.extract on one corpus: where does extraction time go?

usage: profile_extract.py POLICY
"""
import cProfile
import io
import pstats
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE / "core" / "src"), str(HERE)]
import bench_shim  # noqa: E402,F401
from agent_graph import discovery  # noqa: E402
from agent_graph.contracts import Policy, load_json  # noqa: E402
from agent_graph.sources import collect  # noqa: E402

policy_path = Path(sys.argv[1])
policy = Policy.model_validate(load_json(policy_path.read_text()))
for repo in policy.repositories:
    repo.root = str((policy_path.parent / repo.root).absolute())
c = collect(policy)
prof = cProfile.Profile()
prof.enable()
discovery.extract(policy, c)
prof.disable()
out = io.StringIO()
stats = pstats.Stats(prof, stream=out)
total = stats.total_tt
stats.sort_stats("cumulative").print_stats(25)
print(f"total {total:.2f}s")
print(out.getvalue()[:6000])
