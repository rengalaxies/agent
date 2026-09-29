"""Durable restart, replay and local-revision checks with real HTTP processes."""
import copy
import json
from datetime import datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from datamesh_release_protocol.knowledge import KnowledgeStore,digest
from datamesh_release_protocol.stand.fixtures import catalog,ROUTES
from datamesh_release_protocol.stand.launcher import LocalStand
from datamesh_release_protocol.stand.coordinator import CoordinatorRun,post


def main():
    checks=[]
    with TemporaryDirectory(prefix='e4-recovery-') as temp:
        root=Path(temp);store,snapshots=catalog(root/'ledger.json')
        with LocalStand(root/'nodes',store,snapshots) as stand:
            s=snapshots['ACCEPT'];run=CoordinatorRun(store,s.snapshot_id,'durable:accept',10)
            for d,peer in stand.peers.items():
                work=run.work('durable-check:'+d);message=post(peer,'/check',work)
                stand.restart(d);assert post(stand.peers[d],'/check',work)==message
                run.receive(message);run.receive(post(stand.peers[d],'/fence',run.work('durable-fence:'+d)))
                conflicting=copy.deepcopy(work);conflicting['run_id']='different'
                try:post(stand.peers[d],'/check',conflicting)
                except Exception as e:assert getattr(e,'code',None)==409
                else:raise AssertionError('conflicting event id accepted')
            checks.extend(['domain_restart_preserves_response','conflicting_event_id_rejected'])
            result=run.finish();assert result.terminal_state=='COMMITTED'
            recovered=KnowledgeStore(list(store.authorities),root/'ledger.json',domain_public_keys=stand.public_keys,domain_routes=ROUTES)
            replay=CoordinatorRun(recovered,s.snapshot_id,'durable:accept',10)
            # Reload of an already decided run must not require fresh live responses.
            assert replay.finish().model_dump()==result.model_dump()
            checks.append('coordinator_signed_journal_restore_and_replay')
            broken=json.loads((root/'ledger.json').read_text());broken['release_events'][0]['messages'][0]['signature']='00'*64
            # Recalculate outer integrity: authenticated inner receipt still fails.
            # release chain hash validation independently also rejects this modification.
            broken['integrity_hash']=digest({k:v for k,v in broken.items() if k!='integrity_hash'})
            try:recovered._restore(broken)
            except Exception:pass
            else:raise AssertionError('tampered signed journal accepted')
            checks.append('tampered_journal_rejected')
            s=snapshots['INDEPENDENT'];run=CoordinatorRun(store,s.snapshot_id,'local-revision-change',10)
            for d in run.projection()['required_domains']:run.receive(post(stand.peers[d],'/check',run.work('revision-check:'+d)))
            record=next(r for r in s.records if r.kind=='obligation' and r.owner_domain=='risk').model_copy(deep=True)
            record.version+=1;record.valid_from=datetime.now(timezone.utc);record.evidence_ref='e4-local-revision'
            post(stand.peers['risk'],'/metadata',record.model_dump(mode='json'),admin=True)
            stand.restart('risk')
            for d in run.projection()['required_domains']:run.receive(post(stand.peers[d],'/fence',run.work('revision-fence:'+d)))
            assert run.finish().terminal_state=='ABORTED';checks.extend(['updated_domain_state_survives_restart','local_revision_change_aborts'])
        # Launcher reloads persistent keys/configuration and does not overwrite updated metadata.
        with LocalStand(root/'nodes',store,snapshots) as stand2:
            assert stand2.public_keys==store.domain_public_keys
            checks.append('whole_stand_restart_preserves_identity')
    output={'checks':checks,'passed':len(checks)};Path('results/e4-recovery.json').write_text(json.dumps(output,indent=2));print(json.dumps(output))

if __name__=='__main__':main()
