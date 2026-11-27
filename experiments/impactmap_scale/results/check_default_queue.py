"""Supplementary check: actual 10-PR queue on 5/50k with unchanged product limits.

Run from checkout root after the serial matrix, using a new output directory.
Only calls the reviewed load APIs with an explicit policy override.
"""
import argparse
import json
from pathlib import Path
from agent_graph.contracts import Limits
from tools.load_impactmap import run_queue_input
from tools.prepare_impactmap_corpora import load_benchmark_input

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--output',type=Path,required=True)
a=p.parse_args()
corpus=Path('work/batch04/corpora-v1/repos5-lines50k')
i=load_benchmark_input(corpus)
i['policy']['limits']=Limits().model_dump()
events=json.loads((corpus/'corpus-manifest.json').read_text())['streams']['independent_prs']['10']
r=run_queue_input(i,events,a.output)
print(json.dumps(dict(passed=r['passed'],kind=r['kind'])))
raise SystemExit(0 if r['passed'] else 1)
