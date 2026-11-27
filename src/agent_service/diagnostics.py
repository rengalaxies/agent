"""Read-only operator projections from a consistent queue snapshot.

The operator sees this installation's stored results, including stale ones.
This is not an end-user/tenant authorization boundary or a publication action.
"""
import json
from agent_graph.output_contracts import display_verdict

RESOURCE_FIELDS=('resource_id','provider','kind','generation','version','closed','updated_at','published_generation','comment_id')
JOB_FIELDS=('generation','state','reason','attempts','updated_at')
PUBLICATION_FIELDS=('generation','kind','state','reason','operation','comment_id')

def project(row,fields):
    return {key:row[key] for key in fields} if row is not None else None

def resource_listing(connection,limit):
    rows=connection.execute('SELECT '+','.join(RESOURCE_FIELDS)+' FROM resources ORDER BY updated_at DESC,resource_id LIMIT ?', (limit+1,)).fetchall()
    return dict(schema='impactmap-diagnostics-1',items=[project(r,RESOURCE_FIELDS) for r in rows[:limit]],
                limit=limit,has_more=len(rows)>limit)

def resource_diagnostics(connection,resource_id):
    resource=connection.execute('SELECT '+','.join(RESOURCE_FIELDS)+' FROM resources WHERE resource_id=?',(resource_id,)).fetchone()
    if resource is None:return None
    current=connection.execute('SELECT '+','.join(JOB_FIELDS)+' FROM jobs WHERE resource_id=? AND generation=?',(resource_id,resource['generation'])).fetchone()
    result=connection.execute('SELECT generation,resource_version,state,result,reason FROM jobs WHERE resource_id=? AND result IS NOT NULL ORDER BY generation DESC LIMIT 1',(resource_id,)).fetchone()
    analysis=publication=document=None
    if result is not None:
        raw=json.loads(result['result'])
        # Queue revocation changes a job's lifecycle reason after a valid result was saved.
        # It does not change that result's contract. Arbitrary mismatches still fail closed.
        revoked=(result['state']=='SUPERSEDED' and result['reason'] in
                 {'superseded_by_new_version','resource_closed','analysis_basis_changed','core_changed'}
                 and (resource['closed'] or result['generation']<resource['generation']))
        compatible=(display_verdict(raw)['display']!='INCOMPATIBLE' and isinstance(raw,dict)
                    and (result['reason']==raw.get('reason_code') or revoked))
        freshness='CLOSED' if resource['closed'] else 'CURRENT' if result['generation']==resource['generation'] else 'STALE'
        analysis=dict(generation=result['generation'],resource_version=result['resource_version'],job_state=result['state'],
            reason=raw.get('reason_code') if compatible else result['reason'],freshness=freshness,compatible=compatible,raw=raw if compatible else None)
        intent=connection.execute("SELECT "+','.join(PUBLICATION_FIELDS)+",body FROM intents WHERE resource_id=? AND generation=? AND kind='result' ORDER BY created_at DESC,intent_id DESC LIMIT 1",
                                  (resource_id,result['generation'])).fetchone()
        publication=project(intent,PUBLICATION_FIELDS)
        if intent is not None and compatible:
            try:document=json.loads(intent['body'])
            except (ValueError,TypeError):pass
    return dict(schema='impactmap-diagnostics-1',resource=project(resource,RESOURCE_FIELDS),current_job=project(current,JOB_FIELDS),
                analysis=analysis,publication=publication,document=document)
