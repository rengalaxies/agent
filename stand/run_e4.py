"""Reproducible synthetic engineering E4; never reads evaluation/scoring data."""
import argparse
import copy
import itertools
import json
import random
import time
from datetime import datetime,timezone,timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
import yaml
from datamesh_release_protocol.knowledge import KnowledgeStore,digest
from datamesh_release_protocol.models import Decision
from datamesh_release_protocol.stand.policy import project
from datamesh_release_protocol.stand.fixtures import catalog,ROUTES
from datamesh_release_protocol.stand.launcher import LocalStand
from datamesh_release_protocol.stand.coordinator import CoordinatorRun,post
from datamesh_release_protocol.stand.protocol import SignedMessage,sign
from datamesh_release_protocol.stand.adapters import from_yaml,from_events


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--profile',choices=['fast','standard'],default='fast');parser.add_argument('--output',type=Path,default=Path('results/e4-local-fast.json'));args=parser.parse_args()
    ttl=.15 if args.profile=='fast' else 10.;count=30 if args.profile=='fast' else 1
    results=[];started=time.monotonic()
    with TemporaryDirectory(prefix='datamesh-e4-') as temp:
        root=Path(temp);base,snapshots=catalog(root/'ledger.json');payload=json.loads((root/'ledger.json').read_text())
        (root/'registry.yaml').write_text(yaml.safe_dump(payload))
        records={(r['record_id'],r['version']):r for r in payload['records']}
        events=[dict(operation=e['operation'],actor=e['actor'],record=records[(e['record_id'],e['version'])]) for e in payload['events']]
        (root/'events.json').write_text(json.dumps(events))
        with LocalStand(root/'nodes',base,snapshots) as stand:
            def fresh():
                store=KnowledgeStore(list(base.authorities),domain_public_keys=stand.public_keys,domain_routes=ROUTES);store._restore(copy.deepcopy(payload));return store
            def run_case(case,outcome,seed,permutation=None):
                store=fresh();snapshot=snapshots[outcome];run=CoordinatorRun(store,snapshot.snapshot_id,f'{args.profile}:{case}:{outcome}:{seed}:{permutation}',ttl)
                rng=random.Random(seed);domains=list(run.projection()['required_domains']);rng.shuffle(domains)
                if permutation is not None:domains=list(permutation)
                messages={d:post(stand.peers[d],'/check',run.work('check:'+run.run_id+d)) for d in domains if not (case in ('E4-04','E4-06','E4-11') and d=='analytics')}
                fences={d:post(stand.peers[d],'/fence',run.work('fence:'+run.run_id+d)) for d in messages}
                if case=='E4-07':
                    bad=copy.deepcopy(messages['risk']);vote=SignedMessage.model_validate(bad).vote
                    field=('run_id','snapshot_id','new_contract_version')[seed%3];setattr(vote,field,'stale-or-wrong');vote.event_id=digest(vote.model_dump(mode='json',exclude={'event_id'}));messages['risk']=sign(vote,stand.private_keys['risk']).model_dump(mode='json')
                if case=='E4-09':
                    vote=SignedMessage.model_validate(messages['risk']).vote;vote.decision=Decision.NEEDS_REVIEW;vote.issues=['fault_injected_conflicting_sender'];vote.event_id=digest(vote.model_dump(mode='json',exclude={'event_id'}));run.receive(sign(vote,stand.private_keys['risk']).model_dump(mode='json'))
                for domain in domains:
                    if domain not in messages:continue
                    if case=='E4-05':time.sleep(.01 if args.profile=='fast' else .2)
                    for _ in range(rng.randint(1,5) if case=='E4-02' else 1):run.receive(messages[domain])
                    run.receive(fences[domain])
                if case=='E4-08':
                    kinds=('coverage','constitution','product');kind=kinds[seed%3];record=next(r for r in snapshot.records if r.kind==kind)
                    actor='producer' if kind=='product' else 'registry';store.revoke_record(record.record_id,actor,'e4-context-change',datetime.now(timezone.utc))
                if case=='E4-10':
                    projections=[post(peer,'/finalize',{'work':run.work('independent-finalization'),'messages':run.messages,'deadline_expired':False}) for peer in stand.peers.values()]
                    assert all(p==projections[0] for p in projections),'domain finalization differs'
                if not run.ready():run.wait_deadline()
                result=run.finish();elapsed=time.monotonic()-run.started
                if case in ('E4-04','E4-06','E4-07','E4-09','E4-11'):assert result.terminal_state!='COMMITTED',result
                elif case=='E4-08':assert result.terminal_state=='ABORTED',result
                else:assert result.decision.value==outcome,result
                if case=='E4-06':
                    late=post(stand.peers['analytics'],'/check',run.work('late:'+run.run_id));before=result.model_dump(mode='json');assert not run.receive(late);assert run.finish().model_dump(mode='json')==before
                limit=ttl+1 if case in ('E4-04','E4-06','E4-07','E4-09','E4-11') else (8 if args.profile=='standard' else ttl+1)
                assert elapsed<=limit,(case,elapsed,limit)
                results.append({'case':case,'outcome':outcome,'seed':seed,'permutation':permutation,'elapsed_s':elapsed,'limit_s':limit,'passed':True,'result':result.model_dump(mode='json'),'projection':run.projection(),'messages':run.messages,'audit':run.audit})
            for case in ('E4-01','E4-02','E4-03','E4-05','E4-10'):
                for outcome in ('ACCEPT','REJECT','NEEDS_REVIEW'):
                    if case=='E4-03':
                        for i,perm in enumerate(itertools.permutations(['analytics','risk','sales'])):run_case(case,outcome,i,perm)
                    else:
                        for seed in range(count):run_case(case,outcome,seed)
                print(case,'passed',flush=True)
            for case in ('E4-04','E4-06','E4-07','E4-08','E4-09'):
                for seed in range(count):run_case(case,'ACCEPT',seed)
                print(case,'passed',flush=True)
            # Adapter equivalence covers records, reconstructed snapshots and distributed decisions.
            a=from_yaml(root/'registry.yaml',list(base.authorities));b=from_events(root/'events.json',list(base.authorities))
            for seed in range(count):
                for outcome in ('ACCEPT','REJECT','NEEDS_REVIEW'):
                    s=snapshots[outcome];sa=a.build_snapshot(s.proposal_id,s.old_contract,s.new_contract,s.as_of,persist=False);sb=b.build_snapshot(s.proposal_id,s.old_contract,s.new_contract,s.as_of,persist=False);assert sa.model_dump()==sb.model_dump()==s.model_dump()
                    run_id='adapter:'+str(seed)+outcome
                    work=CoordinatorRun(fresh(),s.snapshot_id,run_id,10)
                    messages=[]
                    for domain in work.projection()['required_domains']:
                        messages.append(post(stand.peers[domain],'/check',work.work(run_id+domain)))
                        messages.append(post(stand.peers[domain],'/fence',work.work('fence:'+run_id+domain)))
                    pa=project(sa,run_id,[],messages,stand.public_keys,ROUTES,False);pb=project(sb,run_id,[],messages,stand.public_keys,ROUTES,False)
                    assert pa==pb and pa['decision'].value==outcome
                results.append({'case':'E4-12','seed':seed,'passed':True,'equivalent_outcomes':['ACCEPT','REJECT','NEEDS_REVIEW'],'canonical_snapshot_hashes':{k:v.snapshot_id for k,v in snapshots.items()}})
            print('E4-12 passed',flush=True)
            # Real process outage; independent product never contacts the unavailable domain.
            stand.stop('analytics')
            for seed in range(count):
                store=fresh();s=snapshots['INDEPENDENT'];run=CoordinatorRun(store,s.snapshot_id,'independent:'+str(seed),ttl)
                for domain in run.projection()['required_domains']:
                    run.receive(post(stand.peers[domain],'/check',run.work('independent-check:'+str(seed)+domain)));run.receive(post(stand.peers[domain],'/fence',run.work('independent-fence:'+str(seed)+domain)))
                assert run.finish().terminal_state=='COMMITTED';run_case('E4-11','ACCEPT',seed)
                results[-1]['independent_product_committed']=True
            print('E4-11 passed',flush=True)
            output={'suite':'E4 synthetic local engineering','profile':args.profile,'ttl_s':ttl,'seeds_per_class':count,'cloud_run':False,'confirmatory_E3_run':False,'domain_pids':{d:p['pid'] for d,p in stand.peers.items()},'public_keys':stand.public_keys,'elapsed_s':time.monotonic()-started,'trial_count':len(results),'passed':len(results),'trials':results}
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(output,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in output.items() if k!='trials'}),flush=True)

if __name__=='__main__':main()
