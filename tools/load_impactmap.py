"""Pinned offline load: real graph/event memory and service queue, local transport only.

Sources/state/absolute input remain private. New output required. No network,
source execution, simulated clock, scheduler changes or external publication.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import time
from unittest.mock import patch

from agent_graph.contracts import GraphError, Limits, Policy
from agent_graph.engine import Graph
from agent_graph.graph_store import GraphStore
from agent_graph.graph_store_sync import GraphMaintainer
from agent_graph.store import Store
from agent_service.connectors.base import Prepared, Snapshot
from agent_service.core_analyzer import CoreAnalyzer
from agent_service.envelope import EventEnvelope
from agent_service.publisher import DirectorySink
from agent_service.queue import ServiceStore
from agent_service.service import Service
from tools.benchmark_impactmap import (SpanRecorder, canonical, context_counts, digest,
                                      instrument, public_manifest)
from tools.prepare_impactmap_corpora import load_benchmark_input


def _write(output, result):
    (output/'result.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    return result


def _input(corpus, limits=None):
    manifest=load_benchmark_input(corpus)
    if limits:
        manifest['policy']['limits'].update(limits)
    return manifest


def probe_limits(corpus, output, *, limits=None):
    """Accepted file bytes before collection failure; no partial analysis claimed."""
    from agent_graph.git_sources import GitReader
    from agent_graph.sources import collect
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    inp=_input(corpus);inp['policy']['limits']=Limits().model_dump()
    if limits:inp['policy']['limits'].update(limits)
    expected=json.loads((Path(corpus)/'corpus-manifest.json').read_text())['totals']
    accepted=dict(files=0,bytes=0,python_lines=0)
    original=GitReader.files
    def counted(reader,*args,**kwargs):
        for relative,blob,raw in original(reader,*args,**kwargs):
            accepted['files']+=1;accepted['bytes']+=len(raw)
            accepted['python_lines']+=sum(bool(l.strip()) and not l.lstrip().startswith('#') for l in raw.decode().splitlines())
            yield relative,blob,raw
    meter=SpanRecorder();error=None;c=None
    with patch.object(GitReader,'files',counted):
        try:
            with meter.span('default_collection'):
                c=collect(Policy.model_validate(inp['policy']),inp['base_revisions'])
        except GraphError as exc:error=exc.code
    return _write(output,dict(kind='collection_limit_probe',passed=error is None and c is not None and not c['gaps'] and accepted['bytes']==expected['bytes'],error_code=error,
        limits=inp['policy']['limits'],accepted=accepted,expected_bytes=expected['bytes'],
        expected_python_lines=expected['python_nonblank_noncomment_lines'],
        collection_fraction=accepted['bytes']/expected['bytes'],analyzed_fraction=0,
        fraction_scope='accepted bytes before collector abort; no returned partial context or analysis',
        gap_codes=sorted({g['code'] for g in c['gaps']}) if c else [],spans=meter.spans))


def run_graph_equivalence(corpus, output):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    inp=_input(corpus);policy=Policy.model_validate(inp['policy'])
    recipe=json.loads((Path(corpus)/'corpus-manifest.json').read_text())
    expected_facts=recipe['parameters']['operations']+recipe['known_dependency_callsites']
    meter=SpanRecorder();cases=[]
    persistent=Store(output/'private/incremental');gs=GraphStore(persistent)
    graph=Graph(policy,persistent);maintainer=GraphMaintainer(graph,gs)
    try:
        with meter.span('incremental_initial'):
            maintainer.on_code_event(inp['base_revisions'])
        for scenario in ['baseline','new_consumer','removed_consumer','operation_removed']:
            revisions=load_benchmark_input(corpus,scenario)['head_revisions']
            with meter.span('event_'+scenario):
                inc=maintainer.on_code_event(revisions)
                context=graph.context(inc['context_id'])
                incremental=gs.canonical_facts(graph.scope)
            fresh=Store(output/('private/full-'+scenario))
            try:
                full_graph=Graph(policy,fresh);full_gs=GraphStore(fresh)
                with meter.span('full_'+scenario):
                    full=GraphMaintainer(full_graph,full_gs).reconcile(revisions)
                    facts=full_gs.canonical_facts(full_graph.scope)
                equal=incremental==facts
                counts=context_counts(context)
                active=recipe['parameters']['active_consumers']
                expected_gaps={'unmapped_call':active} if scenario=='operation_removed' else {}
                expected_count=expected_facts+{'baseline':0,'new_consumer':1,'removed_consumer':-1,'operation_removed':-(1+active)}[scenario]
                complete=(counts['repositories_available']==counts['repositories_configured']
                          and counts['gap_counts']==expected_gaps and len(facts)==expected_count)
                cases.append(dict(scenario=scenario,equal=equal,coverage=counts['coverage'],counts=counts,
                    expected_gap_counts=expected_gaps,expected_facts_count=expected_count,source_access_complete=counts['repositories_available']==counts['repositories_configured'],
                    facts_count=len(facts),full_sha256=digest(facts),incremental_sha256=digest(incremental),
                    full_errors=[x['error'] for x in full if 'error' in x],passed=equal and complete and bool(facts) and not any('error' in x for x in full)))
            finally:fresh.close()
    except GraphError as exc:
        cases.append(dict(scenario='error',equal=False,coverage='NOT_RETURNED',error_code=exc.code,passed=False))
    finally:persistent.close()
    return _write(output,dict(kind='full_event_equivalence',passed=bool(cases) and len(cases)==4 and all(x['passed'] for x in cases),
        meaning='existing persisted event memory vs fresh full reconcile at identical complete pins; event path currently rescans corpus',
        cases=cases,spans=meter.spans,manifest=public_manifest(inp)))


class PinnedConnector:
    """Controlled input transport. Not a network/authentication/API benchmark."""
    provider='bitbucket'
    def __init__(self,manifest):
        self.manifest=manifest;self.snapshots={}

    def select(self,event):
        provider=self.manifest['provider_repository'];rid=f'bitbucket:scale/{provider}#{event["pr_id"]}'
        data=dict(provider='bitbucket',repository_id=provider,repository='scale/'+provider,pr_id=event['pr_id'],
                  base_sha=event['base_sha'],head_sha=event['head_sha'])
        snapshot=Snapshot(rid,'pr',digest(data),data);self.snapshots[rid]=snapshot
        return snapshot

    def parse_webhook(self,headers,body):
        e=json.loads(body)
        return EventEnvelope(provider='bitbucket',source='scale',event_id=e['event_id'],event_kind='controlled.pr',
            resource_id=e['resource_id'],resource_version_hint=e['version'],payload_digest=hashlib.sha256(body).hexdigest(),received_at=time.time())

    def fetch(self,rid):return self.snapshots[rid]

    def prepare(self,snapshot):
        m=self.manifest;subject=snapshot.data
        revisions={**m['head_revisions'],subject['repository_id']:subject['head_sha']}
        return Prepared(subject,revisions,attachments={'mainline_revisions':m['base_revisions']})


class MeasuredSink(DirectorySink):
    def __init__(self,root,meter):
        super().__init__(root);self.meter=meter;self.creates=Counter();self.updates=Counter()

    def create_comment(self,rid,doc,marker):
        self.creates[rid]+=1
        with self.meter.span('local_create'):return DirectorySink.create_comment(self,rid,doc,marker)

    def update_comment(self,rid,comment_id,doc,marker):
        self.updates[rid]+=1
        with self.meter.span('local_update'):return DirectorySink.create_comment(self,rid,doc,marker)


def run_queue(corpus, output, *, size, family, delivery, limits=None):
    if size not in (1,5,10) or family not in ('head_updates','independent_prs') or delivery not in ('burst','sequential'):
        raise ValueError('invalid_workload')
    inp=_input(corpus,limits)
    events=json.loads((Path(corpus)/'corpus-manifest.json').read_text())['streams'][family][str(size)]
    return run_queue_input(inp,events,output,family=family,delivery=delivery)


def run_queue_input(inp,events,output,*,family='independent_prs',delivery='burst',
                    expected_status='USEFUL',expected_findings=3,expected_reason='impact_found_within_profile'):
    """Run approved pinned input; expected abstention is explicit, not a useful finding."""
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    policy=Policy.model_validate(inp['policy']);size=len(events)
    meter=SpanRecorder();contexts=[];steps=[];waits=[];duplicates=0
    queue=ServiceStore(output/'private/queue.sqlite3');connector=PinnedConnector(inp)
    analyzer=CoreAnalyzer(policy.model_dump(),output/'private/core',code_version='load-static')
    sink=MeasuredSink(output/'private/comments',meter)
    def hook(phase,item):
        if phase=='claimed':waits.append(max(0,time.time()-item['created_at']))
    def service(store):return Service(store=store,connectors={'bitbucket':connector},analyzer=analyzer,
        installation_id=policy.installation_id,environment=policy.environment,backends={'bitbucket':sink},hook=hook,worker_id='load-worker')
    runner=service(queue)
    def drain():
        for _ in range(500):
            started=time.perf_counter()
            with meter.span('service_step'):outcome=runner.step()
            if outcome is None:return
            steps.append(dict(outcome=outcome,wall_s=time.perf_counter()-started))
        raise RuntimeError('load_step_limit')
    started=time.perf_counter()
    try:
        with instrument(meter,contexts):
            with meter.span('initial_index'):initial=analyzer.reconcile_graph(inp['base_revisions'])
            with meter.span('workload'):
                for event in events:
                    snapshot=connector.select(event)
                    body=canonical(dict(event_id=event['event_id'],resource_id=snapshot.resource_id,version=snapshot.version)).encode()
                    with meter.span('receive'):
                        code,response=runner.receive('bitbucket',{},body)
                        code2,duplicate=runner.receive('bitbucket',{},body)
                    if code!=202 or code2!=200 or not duplicate['duplicate']:raise RuntimeError('load_delivery_contract')
                    duplicates+=1
                    if delivery=='sequential':drain()
                if delivery=='burst':drain()
        # Restart the actual queue connection/writer and ensure nothing re-runs.
        queue=ServiceStore(output/'private/queue.sqlite3');runner=service(queue)
        restart_checked=runner.step() is None
        resources=[];all_jobs=[]
        for resource in queue.resources():
            rid=resource['resource_id'];jobs=queue.jobs(rid);all_jobs+=jobs
            current=[j for j in jobs if j['generation']==resource['generation']]
            result=current[-1]['result'] if current else None
            comments=sink.list_comments(rid)
            latest=(resource['version']==connector.fetch(rid).version and resource['published_generation']==resource['generation']
                    and len(comments)==1 and comments[0].generation==resource['generation'])
            resources.append(dict(resource_id=rid,generation=resource['generation'],head_sha=resource['snapshot']['head_sha'],
                latest_published=latest,job_states=dict(Counter(j['state'] for j in jobs)),
                result_status=result.get('status') if result else None,reason_code=result.get('reason_code') if result else None,
                findings=len(result.get('findings',[])) if result else None,
                gaps=dict(Counter(g['code'] for g in result.get('gaps',[]))) if result else {},
                comments=len(comments)))
        expected_resources=size if family=='independent_prs' else 1
        expected_jobs=size if family=='independent_prs' or delivery=='sequential' else 1
        completed=[j for j in all_jobs if j['result'] is not None]
        def expected_result(document):
            return (document['status']==expected_status and len(document['findings'])==expected_findings
                    and document['reason_code']==expected_reason and not document['gaps'])
        all_results_expected=(len(completed)==expected_jobs and all(expected_result(j['result']) for j in completed))
        result_verdicts=[dict(resource_id=j['resource_id'],generation=j['generation'],status=j['result']['status'],
                             reason_code=j['result']['reason_code'],findings=len(j['result']['findings']),
                             gap_counts=dict(Counter(g['code'] for g in j['result']['gaps'])),
                             expected=expected_result(j['result'])) for j in completed]
        status=queue.status()
        idle=(not any(s in ('RECEIVED','FAILED') for s in status['events'])
              and not any(s in ('QUEUED','RUNNING','FAILED','ANALYZED') for s in status['jobs'])
              and not any(s in ('PENDING','BLOCKED','SENDING','UNKNOWN','FAILED') for s in status['intents']))
        complete=bool(contexts) and all(c['coverage']=='COMPLETE_WITHIN_PROFILE' for c in contexts)
        valid=(len(resources)==expected_resources and len(completed)==expected_jobs and all(r['latest_published']
               and r['result_status']==expected_status and r['findings']==expected_findings
               and r['reason_code']==expected_reason and not r['gaps'] for r in resources))
        passed=idle and valid and all_results_expected and complete and restart_checked and all(v==1 for v in sink.creates.values())
        return _write(output,dict(kind='service_queue',passed=passed,
            expectation=dict(status=expected_status,findings=expected_findings,reason=expected_reason),family=family,delivery=delivery,offered_events=size,
            duplicates_ignored=duplicates,analyzed_jobs=len(completed),creates=sum(sink.creates.values()),updates=sum(sink.updates.values()),
            resources=resources,status=status,idle=idle,restart_checked=restart_checked,queue_wait_seconds=waits,
            contexts=contexts,steps=steps,spans=meter.spans,wall_s=time.perf_counter()-started,
            all_results_expected=all_results_expected,result_verdicts=result_verdicts,
            processed_fraction=sum(x['expected'] for x in result_verdicts)/expected_jobs if complete else 0,
            fraction_scope='expected complete successful job results / expected analyses; collector fraction reported separately by default probe',
            initial_index=initial,manifest=public_manifest(inp),queue_limits=vars(queue.limits),
            history_counts=dict(Counter(x['entry'] for x in queue.history())),
            network='NOT_RUN_LOCAL_PINNED_TRANSPORT',polling='NOT_RUN',clock='real wall time',worker_count=1))
    except Exception as exc:
        return _write(output,dict(kind='service_queue',passed=False,error_code='queue_run_failed',
            error_type=type(exc).__name__,spans=meter.spans,contexts=contexts,steps=steps,
            offered_events=size,family=family,delivery=delivery,processed_fraction=0))
    finally:analyzer.close()


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--corpus',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--equivalence',action='store_true')
    p.add_argument('--probe-defaults',action='store_true');p.add_argument('--queue-size',type=int,default=1,choices=(1,5,10))
    p.add_argument('--family',default='independent_prs',choices=('head_updates','independent_prs'))
    p.add_argument('--delivery',default='burst',choices=('burst','sequential'));args=p.parse_args(argv)
    try:
        if args.equivalence:r=run_graph_equivalence(args.corpus,args.output)
        elif args.probe_defaults:r=probe_limits(args.corpus,args.output)
        else:r=run_queue(args.corpus,args.output,size=args.queue_size,family=args.family,delivery=args.delivery)
        print(canonical(dict(passed=r['passed'],kind=r['kind'])))
        return 0 if r['passed'] else 1
    except Exception as exc:
        print(canonical(dict(error_code='load_runner_failed',error_type=type(exc).__name__)))
        return 2


if __name__=='__main__':raise SystemExit(main())
