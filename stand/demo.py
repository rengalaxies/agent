"""Persisted three-process V2 demo, portable to a Linux VM."""
import argparse
import json
from pathlib import Path
from datamesh_release_protocol.knowledge import KnowledgeStore
from datamesh_release_protocol.stand.fixtures import catalog,ROUTES
from datamesh_release_protocol.stand.launcher import LocalStand
from datamesh_release_protocol.stand.coordinator import CoordinatorRun,post


def main():
    p=argparse.ArgumentParser();p.add_argument('--state',type=Path,required=True);p.add_argument('--outcome',choices=['ACCEPT','REJECT','NEEDS_REVIEW'],default='ACCEPT');p.add_argument('--run-id',required=True);p.add_argument('--ttl',type=float,default=10);a=p.parse_args();a.state=a.state.resolve();a.state.mkdir(parents=True,exist_ok=True)
    base,snapshots=catalog();ledger=a.state/'ledger.json'
    if ledger.exists():
        config=json.loads((a.state/'nodes'/'sales.json').read_text())
        store=KnowledgeStore(list(base.authorities),ledger,domain_public_keys=config['public_keys'],domain_routes=ROUTES)
    else:
        store,snapshots=catalog(ledger)
    with LocalStand(a.state/'nodes',store,snapshots) as stand:
        run=CoordinatorRun(store,snapshots[a.outcome].snapshot_id,a.run_id,a.ttl)
        if a.run_id not in store._release_runs:
            for domain in run.projection()['required_domains']:
                try:
                    remaining=lambda:max(.01,min(2,run.deadline-__import__('time').monotonic()))
                    run.receive(post(stand.peers[domain],'/check',run.work('check:'+a.run_id+domain),remaining()))
                    run.receive(post(stand.peers[domain],'/fence',run.work('fence:'+a.run_id+domain),remaining()))
                except (OSError,ValueError):pass
            if not run.ready():run.wait_deadline()
        print(json.dumps(run.finish().model_dump(mode='json'),ensure_ascii=False,sort_keys=True,indent=2))

if __name__=='__main__':main()
