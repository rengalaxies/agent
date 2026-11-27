"""Read-only operator DTOs. No connector access, secret resolution or config serialization."""
from collections import Counter
from dataclasses import dataclass
import json
import math
import re
from agent_graph.output_contracts import REASONS
from .ui_scope import _listing_details,ui_result

PROVIDERS={'github','bitbucket','jira','kaiten'}
NOTICES={'connection_unauthorized','provider_rejected','reconcile_failed','rate_limited',
         'duplicate_service_comments','postsend_check_failed','analysis_not_connected'}
CODES=set().union(*REASONS.values())|NOTICES|{'outcome_unknown','lease_expired','analysis_unavailable',
    'superseded_by_new_version','resource_closed','analysis_basis_changed','core_changed','replaced_by_result',
    'provider_unavailable','connector_error','not_found','kaiten_binding_required','exactly_one_linked_jira_required',
    'linked_jira_unavailable','publication_source_changed','publication_intent_changed','bitbucket_kaiten_snapshot_changed'}
JOB_STATES={'QUEUED','RUNNING','ANALYZED','DONE','FAILED','SUPERSEDED'}
INTENT_STATES={'PENDING','SENDING','UNKNOWN','BLOCKED','DELIVERED','FAILED','SUPERSEDED'}


@dataclass(frozen=True)
class OperatorMetadata:
    publication: str
    providers: tuple[str,...]
    repository_providers: tuple[tuple[str,str],...]
    trackers: tuple[tuple[str,tuple[str,...],str|None],...]
    bindings: tuple[tuple[str,str,str,str],...]


def metadata_for_config(config):
    providers=[];repos=[];trackers=[];bindings=[]
    bb=config.bitbucket;gh=config.github
    if bb:
        providers.append('bitbucket');repos.extend((r.repository_id,'bitbucket') for r in bb.repositories.values())
    if gh:
        providers.append('github')
        mapping={k.lower():v for k,v in gh.repository_ids.items()}
        repos.extend((mapping.get(r.lower(),r.lower().replace('/','.')),'github')
                     for r in sorted(set(gh.repositories)|set(gh.read_repositories)))
    if config.jira:
        route='bitbucket' if bb and bb.mode=='jira_delivery' else 'jira'
        if route=='jira':providers.append('jira')
        trackers.append(('jira',tuple(config.jira.project_keys),route))
    if config.kaiten:
        trackers.append(('kaiten',tuple(config.kaiten.board_ids),'bitbucket'))
        mapping={str(r.uuid):r.repository_id for r in bb.repositories.values()} if bb else {}
        for rid,target in config.kaiten.bindings.items():
            repository=mapping.get(rid.split('/',1)[-1].split('#',1)[0])
            if repository and rid.split(':',1)[-1].split('/',1)[0]==str(bb.workspace_uuid):
                bindings.append((rid,repository,'kaiten',target))
    return OperatorMetadata(config.publication,tuple(providers),tuple(sorted(set(repos))),tuple(trackers),tuple(bindings))


def code(value,allowed=CODES):return value if value in allowed else 'UNKNOWN' if value is not None else None


def timestamp(value):
    try:
        number=float(value)
        return number if math.isfinite(number) and 0<=number<=253402300799 else None
    except (TypeError,ValueError,OverflowError):return None


def _notices(connection,scope,metadata,ids):
    from .envelope import canonical
    subjects=set(ids)|(set(metadata.providers)&PROVIDERS)|{t[0] for t in metadata.trackers}
    if not subjects:return []
    placeholders=','.join('?' for _ in subjects)
    kinds=','.join('?' for _ in NOTICES)
    rows=connection.execute(f'SELECT kind,subject,count,last_at FROM ui_notice_observations WHERE scope=? AND subject IN ({placeholders}) AND kind IN ({kinds}) ORDER BY last_at DESC,key LIMIT 100',(canonical(scope.receipt()),)+tuple(subjects)+tuple(NOTICES)).fetchall()
    return [{'kind':r['kind'],'subject':r['subject'],'count':r['count'],'last_at':timestamp(r['last_at'])} for r in rows]


def _operations(connection,listing,metadata,notices):
    rows=[]
    for item in listing['items']:
        r=item['resource'];job=dict(item['current_job'] or {})
        if job:
            job['state']=code(job['state'],JOB_STATES);job['reason']=code(job['reason'])
        from .envelope import canonical
        intents=connection.execute('''SELECT generation,kind,state,reason,operation,attempts,updated_at FROM intents i WHERE resource_id=?
            AND EXISTS(SELECT 1 FROM ui_scope_receipts s JOIN jobs j USING(job_id) WHERE j.resource_id=i.resource_id AND j.generation=i.generation AND s.scope=?)
            ORDER BY generation DESC,created_at DESC LIMIT 10''',(r['resource_id'],canonical(listing['scope_receipt']))).fetchall()
        # Each historical generation needs its own receipt before its outbox can be shown.
        outbox=[]
        for intent in intents:
            owned=connection.execute('SELECT 1 FROM ui_scope_receipts s JOIN jobs j USING(job_id) WHERE j.resource_id=? AND j.generation=? AND s.scope=?',
                (r['resource_id'],intent['generation'],canonical(listing['scope_receipt']))).fetchone()
            if owned:
                outbox.append({'generation':intent['generation'],'kind':code(intent['kind'],{'result','failure','stale'}),
                    'state':code(intent['state'],INTENT_STATES),'reason':code(intent['reason']),
                    'operation':code(intent['operation'],{'create','update'}),'attempts':intent['attempts'],'updated_at':timestamp(intent['updated_at'])})
        resource={key:r[key] for key in ('resource_id','provider','kind','generation','closed','updated_at')}
        analysis=item['analysis']
        safe_analysis=({'generation':analysis['generation'],'freshness':analysis['freshness'],'compatible':analysis['compatible'],
                        'job_state':code(analysis['job_state'],JOB_STATES),'reason':code(analysis['reason'])} if analysis else None)
        rows.append({'resource':resource,'current_job':job or None,'analysis':safe_analysis,'outbox':outbox})
    return {'items':rows,'counts':{'jobs':dict(Counter(r['current_job']['state'] for r in rows if r['current_job'])),
        'outbox':dict(Counter(i['state'] for r in rows for i in r['outbox']))},'notices':notices,
        'worker':{'state':'NOT_OBSERVED','last_observed_at':None},'publication_mode':metadata.publication}


def _snapshot(connection,rid):
    row=connection.execute('SELECT snapshot FROM resources WHERE resource_id=?',(rid,)).fetchone()
    try:
        value=json.loads(row['snapshot']) if row else {}
        return value if isinstance(value,dict) else {}
    except (ValueError,TypeError):return {}


def _connections(connection,scope,listing,metadata,notices):
    ids={item['resource']['resource_id'] for item in listing['items']}
    intake=[]
    for provider in metadata.providers:
        if provider not in PROVIDERS:continue
        last=connection.execute('SELECT value FROM checkpoints WHERE name=?',('reconcile:'+provider,)).fetchone()
        intake.append({'id':provider,'state':'ATTENTION' if any(n['subject']==provider for n in notices) else 'NOT_CHECKED',
                       'last_inventory_at':timestamp(last['value']) if last else None})
    sources=[]
    # Only structured gaps of an individually authorized saved analysis identify a source.
    issues={repo:[] for repo in scope.repositories}
    for item in listing['items']:
        data=ui_result(connection,scope,item['resource']['resource_id'])
        analysis=data['analysis'];raw=(analysis or {}).get('result') or {}
        for gap in raw.get('gaps',[]):
            repo=gap.get('repository')
            if repo in issues and len(issues[repo])<10:
                issues[repo].append({'code':gap['code'],'resource_id':data['resource']['resource_id'],
                                    'generation':analysis['generation'],'freshness':analysis['freshness']})
    for repo in scope.repositories:
        providers=sorted({provider for rid,provider in metadata.repository_providers if rid==repo and provider in PROVIDERS})
        sources.append({'id':repo,'providers':providers,'state':'RECORDED_GAPS' if issues[repo] else 'NOT_CHECKED','issues':issues[repo]})
    sources.extend({'id':name,'providers':['runtime'],'state':'NOT_CHECKED','issues':[]} for name in scope.runtime_sources)
    trackers=[];configured={name:(targets,route) for name,targets,route in metadata.trackers}
    for name in ('jira','kaiten','yandex'):
        spec=configured.get(name)
        related=[n for n in notices if spec and n['subject'] in (name,spec[1])]
        trackers.append({'id':name,'configured':spec is not None,'scope':list(spec[0]) if spec else [],
                         'route':spec[1] if spec else None,'state':'ATTENTION' if related else 'NOT_CHECKED' if spec else 'NOT_CONNECTED',
                         'notices':related})
    bindings=[]
    for rid,repo,tracker,target in metadata.bindings:
        if repo not in scope.repositories or tracker not in configured:continue
        saved=_snapshot(connection,rid) if rid in ids else {}
        current=saved.get('_tracker_target')
        state='CONFLICT' if current is not None and current!=target else 'MATCHED_SNAPSHOT' if current==target else 'CONFIGURED_UNVERIFIED'
        bindings.append({'resource_id':rid,'repository':repo,'tracker':tracker,'target':target,'state':state})
        if len(bindings)==100:break
    if 'jira' in configured:
        allowed=set(configured['jira'][0])
        for rid in sorted(ids):
            if len(bindings)>=100:break
            value=_snapshot(connection,rid).get('linked_jira_keys')
            valid=isinstance(value,list) and 1<=len(value)<=32 and all(isinstance(k,str) and re.fullmatch(r'[A-Z][A-Z0-9_]{0,30}-[1-9][0-9]{0,9}',k) for k in value)
            if valid:
                keys=sorted({k for k in value if k.rsplit('-',1)[0] in allowed})
                if keys:bindings.append({'resource_id':rid,'tracker':'jira','targets':keys,'state':'CONFLICT' if len(set(value))>1 else 'RECORDED_UNVERIFIED'})
    return {'intake':intake,'sources':sources,'trackers':trackers,'bindings':bindings,'binding_limit':100,'notices':notices}


def operator_projection(connection,scope,metadata,section):
    if section not in ('operations','connections'):raise ValueError('invalid_operator_section')
    if not isinstance(metadata,OperatorMetadata):return {'available':False,'reason':'operator_metadata_unavailable'}
    listing=_listing_details(connection,scope,100);ids={item['resource']['resource_id'] for item in listing['items']}
    notices=_notices(connection,scope,metadata,ids)
    listing['scope_receipt']=scope.receipt()
    data=_operations(connection,listing,metadata,notices) if section=='operations' else _connections(connection,scope,listing,metadata,notices)
    return {'schema':'impactmap-operator-1','available':True,'coverage':'STAMPED_SCOPE_ONLY','limit':100,
            'scan_budget':1000,'has_more':listing['has_more'],**data}
