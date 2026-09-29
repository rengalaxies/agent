from pathlib import Path
from tempfile import TemporaryDirectory
from datamesh_release_protocol.stand.fixtures import catalog
from datamesh_release_protocol.stand.launcher import LocalStand
from datamesh_release_protocol.stand.coordinator import CoordinatorRun,post
with TemporaryDirectory() as d:
    store,snapshots=catalog(Path(d)/'ledger.json')
    with LocalStand(Path(d)/'nodes',store,snapshots) as stand:
        print('domain_processes', {domain:peer['pid'] for domain,peer in stand.peers.items()})
        for outcome in ('ACCEPT','REJECT','NEEDS_REVIEW'):
            run=CoordinatorRun(store,snapshots[outcome].snapshot_id,'smoke:'+outcome,10)
            for domain,peer in stand.peers.items():
                run.receive(post(peer,'/check',run.work('check:'+outcome+domain)))
                run.receive(post(peer,'/fence',run.work('fence:'+outcome+domain)))
            print(outcome,run.finish().model_dump_json())
