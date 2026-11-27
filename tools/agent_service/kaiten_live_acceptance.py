"""Isolated real-cloud acceptance worker. No credential discovery or mutations of SCM.

Run only in the prepared sandbox with scope.json and pinned candidate source.
Uses existing application queue/publisher; --fault=after_send pauses for an
external SIGKILL after verified remote write and before local delivery commit.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import fcntl
import json
import os
from pathlib import Path
import re
import signal


def _inside(value, root):
    path=Path(value).resolve()
    if path==root or not path.is_relative_to(root): raise ValueError('nonisolated_path')
    return path


def validate_isolation(config, scope, root):
    root=Path(root).resolve()
    if config.get('publication')!='live' or config.get('allow_loopback_http') or config.get('jira') or config.get('github') or config.get('confluence'):
        raise ValueError('nonisolated_provider_config')
    bb=config['bitbucket'];kc=config['kaiten'];core=config['core']
    if bb.get('mode')!='kaiten_delivery' or bb.get('api_base','https://api.bitbucket.org/2.0')!='https://api.bitbucket.org/2.0': raise ValueError('real_bitbucket_required')
    if bb['workspace_uuid']!=scope['workspace_uuid'] or sorted(str(r['uuid']) for r in bb['repositories'].values())!=sorted(scope['repository_uuids']): raise ValueError('source_scope_changed')
    if kc['base_url']!=scope['kaiten_origin'] or kc['bot_id']!=scope['bot_id'] or sorted(kc['board_ids'])!=sorted(scope['board_ids']): raise ValueError('target_scope_changed')
    if set(kc['bindings'])!={scope['resource_id']} or any(c not in scope['card_ids'] for c in kc['bindings'].values()): raise ValueError('target_binding_changed')
    _inside(config['state_path'],root);_inside(core['state_dir'],root)
    for key in ('constitution_path','ownership_path'):
        if core.get(key): _inside(core[key],root)
    if core.get('runtime_sources') or core.get('model_qualification'): raise ValueError('external_context_not_allowed')
    policy=json.loads(_inside(core['policy_path'],root).read_text())
    for key in ('installation_id','environment'):
        if config.get(key)!=scope[key] or policy.get(key)!=scope[key]: raise ValueError('scope_identity_changed')
    if policy.get('model'): raise ValueError('model_must_be_off')
    for repo in policy['repositories']: _inside(repo['root'],root)
    return policy


def assess_report(report, *, expected_head, expected_status=None, expected_finding=None, expect_closed=False):
    errors=[]
    if report['head']!=expected_head: errors.append('wrong_head')
    if report['closed']!=expect_closed: errors.append('expected_closed' if expect_closed else 'resource_closed')
    if any(j['state']=='FAILED' for j in report['jobs']): errors.append('failed_job')
    if any(i['state']=='FAILED' for i in report['intents']): errors.append('failed_intent')
    if report.get('history_failures'): errors.append('historical_failure')
    if report.get('reconcile_errors'): errors.append('reconcile_failed')
    if report.get('target_card_id')!=report.get('expected_card_id'): errors.append('wrong_phase_target')
    if expect_closed:
        if not report.get('stored_closed'): errors.append('closure_not_persisted')
        if any(i['state'] in {'PENDING','SENDING','UNKNOWN'} for i in report['intents']): errors.append('pending_closed_write')
        return errors
    if len(report['owned_comments'])!=1: errors.append('not_one_owned_comment')
    jobs=[j for j in report['jobs'] if j['generation']==report['generation']]
    intents=[i for i in report['intents'] if i['generation']==report['generation'] and i.get('kind')=='result']
    if not jobs or jobs[-1]['state']!='DONE': errors.append('current_job_not_done')
    if not intents or intents[-1]['state']!='DELIVERED': errors.append('current_intent_not_delivered')
    if jobs and expected_status and jobs[-1].get('status')!=expected_status: errors.append('wrong_status')
    if jobs and expected_finding and expected_finding not in jobs[-1].get('findings',[]): errors.append('missing_finding')
    if jobs and expected_status=='ABSTAINED' and (jobs[-1].get('findings') or jobs[-1].get('reason')!='no_supported_delta'): errors.append('unexpected_corrected_result')
    snapshots=jobs[-1].get('snapshots',[]) if jobs else []
    pins={(v['repository'],v['role']):v['commit'] for v in snapshots}
    provider=report.get('provider_repository')
    if pins.get((provider,'head'))!=expected_head or pins.get((provider,'base'))!=report.get('destination_tip'): errors.append('missing_snapshot_proof')
    if any(pins.get((repo,'consumer'))!=sha for repo,sha in report.get('expected_consumer_pins',{}).items()): errors.append('wrong_consumer_pins')
    if len(report['owned_comments'])==1 and intents:
        comment=report['owned_comments'][0];intent=intents[-1]
        if (comment.get('id')!=intent.get('comment_id') or comment.get('id')!=report.get('comment_id')
            or comment.get('digest')!=intent.get('body_digest') or comment.get('digest')!=report.get('comment_digest')
            or comment.get('generation')!=report['generation'] or report.get('published_generation')!=report['generation']
            or not (intent.get('receipt') or {}).get('current_at_delivery')): errors.append('comment_not_current_result')
    return errors


def durable_json(path, data):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_suffix('.tmp')
    with tmp.open('w') as f:
        json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    os.replace(tmp,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def run(root, *, expected_head, expected_status, expected_finding, run_id, manifest_sha, expected_card, fault='none', expect_closed=False):
    from agent_service.config import ServiceConfig,build,core_analyzer
    from agent_service.publisher import resource_marker
    from agent_service.service import Service
    root=Path(root).resolve()
    if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',run_id) or not re.fullmatch(r'[0-9a-f]{40}',expected_head): raise ValueError('invalid_acceptance_arguments')
    lock=(root/'acceptance.lock').open('a')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    cfgdoc=json.loads((root/'service.json').read_text());scope=json.loads((root/'scope.json').read_text())
    validate_isolation(cfgdoc,scope,root)
    # A path named app/src is not sufficient: hash every candidate component
    # against the local-source manifest transmitted before the run.
    raw_manifest=(root/'candidate-files.json').read_bytes()
    if hashlib.sha256(raw_manifest).hexdigest()!=manifest_sha: raise ValueError('unregistered_candidate_manifest')
    manifest=json.loads(raw_manifest)
    required={'src/agent_graph/engine.py','src/agent_service/config.py','src/agent_service/core_analyzer.py','src/agent_service/publisher.py','tools/agent_service/kaiten_live_acceptance.py'}
    if not required.issubset(manifest): raise ValueError('incomplete_candidate_manifest')
    actual={str(p.relative_to(root/'app')) for p in (root/'app').rglob('*') if p.is_file()}
    if actual!=set(manifest): raise ValueError('unregistered_app_files')
    for name,sha in manifest.items():
        path=_inside(root/'app'/name,root/'app')
        if hashlib.sha256(path.read_bytes()).hexdigest()!=sha: raise ValueError('candidate_source_changed')
    import agent_service.config as config_module
    import agent_service.publisher as publisher_module
    import agent_service.core_analyzer as analyzer_module
    import agent_graph.engine as graph_module
    for module in (config_module,publisher_module,analyzer_module,graph_module):
        if not Path(module.__file__).resolve().is_relative_to(root/'app'/'src'): raise ValueError('wrong_loaded_candidate')
    if not Path(__file__).resolve().is_relative_to(root/'app'): raise ValueError('wrong_acceptance_helper')
    output=root/'receipts'/(run_id+'.json')
    if output.exists(): raise ValueError('run_receipt_exists')
    cfg=ServiceConfig.model_validate(cfgdoc)
    store,connectors,backends=build(cfg)
    connector=connectors['bitbucket'];rid=scope['resource_id']
    from agent_service.http import ClientError
    original_fetch=connector.fetch
    def pinned_fetch(resource_id):
        current=original_fetch(resource_id);d=current.data
        if (resource_id!=rid or d.get('head_sha')!=expected_head or d.get('head_ref')!=scope['head_ref']
            or d.get('base_ref')!=scope['base_ref'] or d.get('destination_tip_sha')!=scope['destination_tip']
            or d.get('state')!='OPEN' or d.get('_tracker_target')!=expected_card
            or (current.closed and not expect_closed)): raise ClientError('acceptance_source_or_target_changed')
        return current
    connector.fetch=pinned_fetch
    connector.fetch(rid)
    analyzer=core_analyzer(cfg.core,code_version=cfg.analysis.get('code_version','candidate'))
    def hook(phase,intent):
        if fault=='after_send' and phase=='after_send' and intent['kind']=='result':
            row=next(i for i in store.intents(rid) if i['intent_id']==intent['intent_id'])
            owned=[c for c in backends['bitbucket'].list_comments(rid) if c.marker==intent['marker'] and c.author==cfg.kaiten.bot_id]
            if row['state']!='SENDING' or len(owned)!=1 or owned[0].digest!=intent['body_digest'] or owned[0].generation!=intent['generation']: raise ValueError('fault_point_not_verified')
            db=Path(cfg.state_path).stat()
            durable_json(root/'fault-ready.json',{'pid':os.getpid(),'start_ticks':Path('/proc/self/stat').read_text().split()[21],
                'run_id':run_id,'phase':phase,'kind':intent['kind'],'generation':intent['generation'],'intent_id':intent['intent_id'],
                'db_device':db.st_dev,'db_inode':db.st_ino,'state':'SENDING','lease_expires':row['lease_expires'],
                'comment_id':owned[0].comment_id,'digest':owned[0].digest})
            signal.pause()
    try:
        service=Service(store=store,connectors=connectors,backends=backends,analyzer=analyzer,
            installation_id=cfg.installation_id,environment=cfg.environment,analysis_settings=cfg.analysis,hook=hook)
        recovered=service.recover();reconciled=service.reconcile();steps=service.run_until_idle()
        resource=store.resource(rid);after=connector.fetch(rid)
        marker=resource_marker(cfg.installation_id,rid)
        owned=[] if after.closed else [c for c in backends['bitbucket'].list_comments(rid) if c.marker==marker and c.author==cfg.kaiten.bot_id]
        jobs=[]
        for job in store.jobs(rid):
            result=job.get('result') or {}
            jobs.append({'generation':job['generation'],'state':job['state'],'status':result.get('status'),'reason':result.get('reason_code'),
                'findings':[f.get('code') for f in result.get('findings',[])],
                'snapshots':[{'repository':s['repository'],'role':s['role'],'commit':s['commit']} for s in result.get('snapshots',[])]})
        report={'provenance':'REAL_BITBUCKET_CLOUD_REAL_GIT_REAL_CORE_REAL_KAITEN','pid':os.getpid(),'observed_utc':datetime.now(timezone.utc).isoformat(),
            'candidate_manifest_sha256':hashlib.sha256((root/'candidate-files.json').read_bytes()).hexdigest(),'code_version':cfg.analysis.get('code_version'),
            'run_id':run_id,'resource_id':rid,'head':after.data['head_sha'],'destination_tip':after.data['destination_tip_sha'],'closed':after.closed,
            'generation':resource['generation'],'resource_version':resource['version'],'target_card_id':after.data['_tracker_target'],
            'expected_card_id':expected_card,'stored_closed':bool(resource['closed']),'published_generation':resource['published_generation'],
            'comment_id':resource['comment_id'],'comment_digest':resource['comment_digest'],'provider_repository':scope['provider_repository'],
            'expected_consumer_pins':scope['consumer_pins'],
            'history_failures':[{'entry':h['entry'],'generation':h['detail'].get('generation')} for h in store.history(rid)
                if h['entry'] in {'job_failed','intent_failed','event_failed'} or (h['entry']=='job_recovered' and h['detail'].get('failed'))],
            'reconcile_errors':[n['kind'] for n in store.notices() if n['kind'] in {'reconcile_failed','provider_rejected','connection_unauthorized','postsend_check_failed'}],
            'marker':marker,'owned_comments':[{'id':c.comment_id,'digest':c.digest,'generation':c.generation} for c in owned],
            'jobs':jobs,'intents':[{'generation':i['generation'],'state':i['state'],'kind':i['kind'],'reason':i.get('reason'),'comment_id':i.get('comment_id'),'body_digest':i['body_digest'],'receipt':i.get('receipt')} for i in store.intents(rid)],
            'recovered':recovered,'reconciled':reconciled,'steps':steps,'model':'OFF','db_device':Path(cfg.state_path).stat().st_dev,'db_inode':Path(cfg.state_path).stat().st_ino}
        report['errors']=assess_report(report,expected_head=expected_head,expected_status=expected_status,expected_finding=expected_finding,expect_closed=expect_closed)
        report['status']='PASS' if not report['errors'] else 'FAIL'
        durable_json(output,report)
        return report
    finally:analyzer.close()


def validate_control_request(action, name=None):
    allowed={'bootstrap','linux-tests','tests-status','run','receipt','fault-ready','kill-ready','postflight','relink','archive','restore','delete-result','delete-card','recovery-proof'}
    if action not in allowed: raise ValueError('unsupported_control_action')
    if action in {'run','receipt','kill-ready','recovery-proof'} and (not isinstance(name,str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',name)):
        raise ValueError('invalid_run_id')


def safe_test_summary(log):
    match=re.search(r'Ran (\d+) tests? in ([0-9.]+)s',log)
    failed=re.findall(r'^(?:FAIL|ERROR): (test_[a-zA-Z0-9_]+) \(([a-zA-Z0-9_.]+)\)',log,re.M)
    complete=bool(match and (re.search(r'^OK(?: \(.*\))?$',log,re.M) or re.search(r'^FAILED ',log,re.M)))
    return {'complete':complete,'success':bool(complete and re.search(r'^OK(?: \(.*\))?$',log,re.M)),
            'run':int(match[1]) if match else None,'seconds':float(match[2]) if match else None,
            'failures':[{'test':a,'module':b} for a,b in failed],
            'linux_sigkill_ok':len(re.findall(r'^test_sigkill_[a-z_]+ .* \.\.\. ok$',log,re.M)),
            'skipped':len(re.findall(r' \.\.\. skipped ',log))}


def recovery_errors(ready,killed,report):
    errors=[]
    if (ready.get('state')!='SENDING' or killed.get('run_id')!=ready.get('run_id')
        or killed.get('killed_pid')!=ready.get('pid') or killed.get('start_ticks')!=ready.get('start_ticks')
        or killed.get('signal')!=9 or killed.get('not_running') is not True): errors.append('unproven_kill')
    if report.get('pid')==ready.get('pid'): errors.append('same_process')
    if any(report.get(k)!=ready.get(k) for k in ('db_device','db_inode')): errors.append('different_database')
    if report.get('recovered',{}).get('sending',0)<1: errors.append('unknown_not_recovered')
    if report.get('comment_id')!=ready.get('comment_id') or report.get('comment_digest')!=ready.get('digest'): errors.append('different_comment')
    intents=[i for i in report.get('intents',[]) if i.get('kind')=='result' and i.get('state')=='DELIVERED' and i.get('generation')==report.get('generation')]
    if not intents or (intents[-1].get('receipt') or {}).get('wrote') is not False: errors.append('recovery_wrote_again')
    return errors


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--expected-head',required=True);p.add_argument('--manifest-sha256',required=True);p.add_argument('--expected-card',required=True)
    p.add_argument('--expected-status',choices=['USEFUL','PARTIAL','ABSTAINED']);p.add_argument('--expected-finding');p.add_argument('--run-id',required=True)
    p.add_argument('--fault',choices=['none','after_send'],default='none');p.add_argument('--expect-closed',action='store_true')
    a=p.parse_args(argv)
    try:
        r=run(a.root,expected_head=a.expected_head,expected_status=a.expected_status,expected_finding=a.expected_finding,run_id=a.run_id,manifest_sha=a.manifest_sha256,expected_card=a.expected_card,fault=a.fault,expect_closed=a.expect_closed)
        print(json.dumps(r,ensure_ascii=False));return 0 if r['status']=='PASS' else 1
    except Exception as exc:
        # No config/provider exception text, credential-bearing stdout or source.
        print(json.dumps({'status':'FAIL','error_type':type(exc).__name__,'run_id':a.run_id}));return 2


if __name__=='__main__':raise SystemExit(main())
