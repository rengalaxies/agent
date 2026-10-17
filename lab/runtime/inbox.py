"""Single-writer local CLI inbox. Cards/decisions are data, never execution grants."""
import argparse
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from .core import Stop, digest, tree_digest

REPLAY='lab/reports/agent-ci-39066354050/agent-evidence'
STATUSES={'требуется решение','исправление подготовлено','проверено','заблокировано','устарело'}


def load(path):
    p=Path(path)
    return json.loads(p.read_text()) if p.exists() else {'format':1,'cards':[],'decisions':[],'local_notifications':[],'changes':[],'execution_permission':False}


def save(path, store):
    p=Path(path);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_name(p.name+'.tmp');tmp.write_text(json.dumps(store,indent=2,ensure_ascii=False)+'\n');tmp.replace(p)


def collect(source, source_commit):
    """Supported literal references only; ownership is a separate declared catalog."""
    source=Path(source);path=source/'lab/app/service.py';raw=path.read_text();module=ast.parse(raw)
    catalog=json.loads((source/'lab/catalog/owners.json').read_text())
    evidence=[]
    for function in [n for n in ast.walk(module) if isinstance(n,ast.FunctionDef)]:
        for node in ast.walk(function):
            relation=None;object_ref=None
            if (isinstance(node,ast.Call) and getattr(node.func,'attr','')=='basic_get'
                    and any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='event_minor' for n in ast.walk(function))):
                kwargs={k.arg:k.value.value for k in node.keywords if isinstance(k.value,ast.Constant)}
                if isinstance(kwargs.get('queue'),str):relation='STATIC_BROKER_READ';object_ref='rabbitmq:queue:'+kwargs['queue']
            if isinstance(node,ast.Constant) and isinstance(node.value,str):
                refs=re.findall(r'\bFROM\s+(analytics\.orders_v[12])\b',node.value,re.I)
                if refs:relation='STATIC_SQL_READ';object_ref='postgres:'+refs[0]
            if relation:
                target='lab/app/service.py#'+function.name
                owners=[b for b in catalog.get('bindings',[]) if b.get('environment_id')=='lab' and b.get('object_ref')==target]
                teams=sorted({b['team_id'] for b in owners if b.get('team_id')})
                owner=teams[0] if len(teams)==1 else ('CONFLICT' if teams else 'UNKNOWN')
                basis={'target':target,'dependency_object':object_ref,'relation':relation,
                       'source_path':'lab/app/service.py','line':node.lineno,
                       'source_fragment':ast.get_source_segment(raw,node),
                       'source_sha256':hashlib.sha256(raw.encode()).hexdigest(),'source_commit':source_commit,
                       'freshness':'HISTORICAL_REPLAY_SNAPSHOT; deployed state NOT_VERIFIED',
                       'owner':owner,'owner_basis':owners,'owner_origin':'DECLARED_CATALOG_NOT_AUTO_DISCOVERY',
                       'owner_freshness':'UNKNOWN; requires coordinator/team confirmation',
                       'owner_catalog_sha256':hashlib.sha256((source/'lab/catalog/owners.json').read_bytes()).hexdigest()}
                basis['evidence_id']=digest(basis);evidence.append(basis)
    return evidence


def replay(root):
    p=Path(root)/REPLAY;summary=json.loads((p/'summary.json').read_text());report=json.loads((p/'model-attempt-1/report.json').read_text())
    candidate=p/'model-attempt-1/candidate';change=json.loads((p/'input.json').read_text())
    negative=json.loads((p/'negative-control.json').read_text())
    if tree_digest(candidate)!=report['candidate']['candidate_digest'] or digest(change['proposed_diff'])!=report['diff_digest']:
        raise Stop('Replay artifact integrity mismatch.')
    patch=candidate/'lab/sql/expand.sql'
    if hashlib.sha256(patch.read_bytes()).hexdigest()!=report['candidate']['patches'][0]['after_digest']:
        raise Stop('Replay patch digest mismatch.')
    return {'directory':p,'source':candidate,'input':change,'report':report,'run':summary['actions_run'],
            'source_commit':summary['source_commit'],'negative':negative,'kind':'SAVED_REAL_AGENT_REPLAY; NO_NEW_INFERENCE_OR_VERIFICATION'}


def assess(store, change, root, initiator, coordinator, source=None):
    if any(not isinstance(change.get(k),str) or not change[k].strip() for k in ['change_id','intent','proposed_diff']):raise Stop('Change ID, intent and proposed diff must be nonempty strings.')
    if type(change.get('revision')) is not int or change['revision']<1 or change.get('environment_id')!='lab':raise Stop('Exact positive lab revision required.')
    if not initiator or not coordinator:raise Stop('Explicit initiator and coordinator required.')
    r=replay(root);source=Path(source or r['source'])
    # Altered app/contracts cannot borrow a historical financial PASS.
    same_code=all((source/folder).exists() and tree_digest(source/folder)==tree_digest(r['source']/folder) for folder in ['lab/app','lab/contracts','lab/sql'])
    eligible=digest(change)==digest(r['input']) and same_code
    found=collect(source,r['source_commit'] if same_code else 'UNVERIFIED_LOCAL_SOURCE_NOT_REPLAY_COMMIT');binding=digest({'change':change,'evidence':found,'initiator':initiator,'coordinator':coordinator,
        'replay_candidate':r['report']['candidate']['candidate_digest'],'replay_eligible':eligible})
    history=[x for x in store['changes'] if x['change_id']==change['change_id']]
    if history:
        latest=max(x['revision'] for x in history)
        if change['revision']<latest:raise Stop('Cannot restore an obsolete revision.')
        if any(x['revision']==change['revision'] and x['input_digest']!=digest(change) for x in history):raise Stop('Changed input requires a new revision.')
        if history[-1].get('context_digest')==binding:return store
    context_digest=binding
    binding=digest({'context':context_digest,'assessment_number':len(history)+1})
    old_ids={c['card_id'] for c in store['cards'] if c['change_id']==change['change_id'] and c['active']}
    for c in store['cards']:
        if c['card_id'] in old_ids:c.update(active=False,status='устарело',next_action='Повторно оценить новую ревизию; старое решение неприменимо.',invalidated_by_revision=change['revision'])
    for d in store['decisions']:
        if d['card_id'] in old_ids:d.update(valid=False,invalidation='REVISION_OR_ASSESSMENT_CHANGED')
    store['changes'].append({'change_id':change['change_id'],'revision':change['revision'],'input_digest':digest(change),
        'assessment_digest':binding,'context_digest':context_digest,'initiator':initiator,'coordinator':coordinator,'intent':change['intent'],
        'replay':r['kind'],'replay_run':r['run'],'replay_eligible':eligible,'coverage':'literal supported references only; no general graph completeness or deployed freshness'})
    groups={}
    for item in found:
        team=item['owner'] if item['owner'] not in ['UNKNOWN','CONFLICT'] else 'COORDINATOR'
        groups.setdefault(team,[]).append(item)
    for team,grounds in sorted(groups.items()):
        unknown=team=='COORDINATOR';responsible=coordinator if unknown else team
        verified=eligible and r['report']['verification']['outcome']=='PASS'
        has_patch=eligible and bool(r['report'].get('candidate'))
        status='заблокировано' if unknown else ('проверено' if verified else ('исправление подготовлено' if has_patch else 'требуется решение'))
        card_id=digest({'assessment':binding,'team':team})[:24]
        card={'card_id':card_id,'change_id':change['change_id'],'revision':change['revision'],'assessment_digest':binding,
            'team':team,'initiator':initiator,'responsible':responsible,'active':True,'status':status,
            'affected_services':sorted({g['target'] for g in grounds}),'grounds':grounds,
            'risk':{'status':'INFERRED_RISK','description':('Billing читает события из очереди: нужно сохранить единицы суммы старого контракта. Неверный backfill блокирует S1; порча расчётных записей этим replay не воспроизведена.' if any(g['relation']=='STATIC_BROKER_READ' for g in grounds) else 'Аналитика читает представления orders_v1/v2: нужно сохранить смысл суммы в обоих путях. Неверный backfill блокирует S1; порча аналитического результата этим replay не воспроизведена.')},
            'reproduction':{'status':'REPLAY_BROKEN_MIGRATION_REJECTED' if eligible and r['negative']['outcome']=='FAIL' else 'NOT_RUN_FOR_THIS_REVISION',
                'result':{'negative_verifier_outcome':r['negative']['outcome'],'S0_S5_check':r['negative']['checks']['compatible_S0_S5'],'downstream_corruption':'NOT_REPRODUCED by this replay'} if eligible else None,
                'evidence':REPLAY+'/negative-control.json' if eligible else None},
            'repair':{'status':'PREPARED_IN_REPLAY' if has_patch else 'NOT_PREPARED_FOR_THIS_REVISION',
                'patch_ref':REPLAY+'/model.patch' if has_patch else None,
                'candidate_digest':r['report']['candidate']['candidate_digest'] if has_patch else None},
            'independent_verification':{'status':'PASS_IN_HISTORICAL_REPLAY' if verified else 'NOT_RUN_FOR_THIS_REVISION',
                'scope':'R1-R5 isolated financial candidate; not team approval or deployment freshness',
                'evidence':REPLAY+'/model-attempt-1/report.json' if verified else None,'actions_run':r['run'] if eligible else None},
            'next_action':('Координатору определить и подтвердить владельца перечисленных объектов, затем повторить оценку.' if unknown else
                ('Команде изучить patch и независимые результаты, записать решение по этой ревизии; для применения нужен отдельный мандат.' if verified else
                 'Инициатору запустить повторный анализ и независимую проверку этой ревизии; команде уточнить требования.')),
            'next_action_owner':responsible if verified or unknown else initiator,
            'decision':None,'execution_permission':False,'notification_kind':'LOCAL_INBOX_ONLY','replay':r['kind']}
        assert status in STATUSES
        store['cards'].append(card)
        store['local_notifications'].append({'notification_id':card_id,'card_id':card_id,'recipient':responsible,'channel':'LOCAL_JSON','external_sent':False})
    return store


def decide(store, card_id, revision, assessment, team, actor, decision, comment=''):
    card=next((c for c in store['cards'] if c['card_id']==card_id),None)
    if not card or not card['active'] or card['revision']!=revision or card['assessment_digest']!=assessment:raise Stop('Decision refers to stale or mismatched revision/assessment.')
    if card['team']!=team or not actor:raise Stop('Exact team and actor required; CLI identities are operator-declared, not authenticated users.')
    if decision not in ['acknowledged','reviewed','request_changes','rejected']:raise Stop('Unsupported team decision.')
    payload={'card_id':card_id,'revision':revision,'assessment_digest':assessment,'team':team,'actor':actor,'decision':decision,'comment':comment}
    key=digest(payload)
    if any(d['decision_id']==key for d in store['decisions']):return store
    for d in store['decisions']:
        if d['card_id']==card_id and d['valid']:d.update(valid=False,invalidation='SUPERSEDED_TEAM_DECISION')
    record={**payload,'decision_id':key,'recorded_at':datetime.now(timezone.utc).isoformat(),'valid':True,'grants_execution':False}
    store['decisions'].append(record);card['decision']=key
    if decision in ['request_changes','rejected']:
        card.update(status='заблокировано',next_action='Инициатору устранить замечания команды и представить новую ревизию.',next_action_owner=card['initiator'])
    return store


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--store',required=True)
    commands=parser.add_subparsers(dest='command',required=True)
    a=commands.add_parser('assess');a.add_argument('--change',required=True);a.add_argument('--root',default='.');a.add_argument('--source');a.add_argument('--initiator',required=True);a.add_argument('--coordinator',required=True)
    d=commands.add_parser('decide')
    for name in ['card-id','assessment','team','actor','decision']:d.add_argument('--'+name,required=True)
    d.add_argument('--revision',type=int,required=True);d.add_argument('--comment',default='')
    commands.add_parser('list');args=vars(parser.parse_args());path=args.pop('store');command=args.pop('command');store=load(path)
    try:
        if command=='assess':args['change']=json.loads(Path(args['change']).read_text());assess(store,**args)
        elif command=='decide':decide(store,**args)
        if command!='list':save(path,store)
        print(json.dumps(store,indent=2,ensure_ascii=False))
    except Stop as exc:parser.exit(2,str(exc)+'\n')

if __name__=='__main__':main()
