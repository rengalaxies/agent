"""Fail-closed web projections. Persisted raw output is not a grant receipt."""
from dataclasses import dataclass
from pathlib import Path

from agent_graph.contracts import Policy
from agent_graph.output_contracts import AnalysisRequest, parse_document
from .diagnostics import resource_diagnostics
from .envelope import canonical, digest


@dataclass(frozen=True)
class UIScope:
    installation_id: str
    environment: str
    view_id: str
    repositories: tuple[str,...]
    runtime_sources: tuple[str,...]
    database: str

    def receipt(self):
        return {'installation_id':self.installation_id,'environment':self.environment,
                'access_scope':{'view_id':self.view_id,'repositories':sorted(self.repositories),
                                'runtime_sources':sorted(self.runtime_sources)}}

    @property
    def identity(self):return digest({'grants':self.receipt(),'database':self.database})


def scope_for_service(service):
    policy=getattr(service.analyzer,'policy',None)
    if not isinstance(policy,Policy) or 'read_context' not in policy.capabilities:
        raise ValueError('ui_core_grants_required')
    if (policy.installation_id,policy.environment)!=(service.installation_id,service.environment):
        raise ValueError('ui_scope_mismatch')
    return UIScope(policy.installation_id,policy.environment,policy.view_id(),
                   tuple(sorted(r.id for r in policy.repositories)),
                   tuple(sorted(s.id for s in service.analyzer.runtime_sources)),
                   str(service.store.path.resolve()))


def scope_for_config(config):
    from .config import _document
    from types import SimpleNamespace
    if config.core is None:raise ValueError('ui_core_grants_required')
    policy=Policy.model_validate(_document(config.core.policy_path))
    return scope_for_service(SimpleNamespace(installation_id=config.installation_id,environment=config.environment,
        store=SimpleNamespace(path=config.state_path),
        analyzer=SimpleNamespace(policy=policy,runtime_sources=[SimpleNamespace(id=s['id']) for s in config.core.runtime_sources])))


def validate_private_locations(settings,service,config_path=None):
    """Credentials cannot be placed inside a source tree the analyzer reads."""
    for repo in service.analyzer.policy.repositories:
        root=Path(repo.root).resolve()
        for path in (settings.database,config_path):
            if path is not None and Path(path).resolve().is_relative_to(root):
                raise ValueError('ui_secrets_inside_analyzed_root')
    if settings.database.resolve()==service.store.path.resolve():raise ValueError('ui_separate_database_required')


def request_receipt(request):
    parsed=parse_document(request)
    if not isinstance(parsed,AnalysisRequest):raise ValueError('ui_request_required')
    return canonical({'installation_id':parsed.installation_id,'environment':parsed.environment,
        'access_scope':{'view_id':parsed.access_scope.view_id,'repositories':sorted(parsed.access_scope.repositories),
                        'runtime_sources':sorted(parsed.access_scope.runtime_sources)}})


def _output_within_scope(raw,scope):
    allowed=set(scope.repositories)|set(scope.runtime_sources)|{'installation_mapping','codeowners','service_catalog'}
    def visit(value,nullable_gap_repository=False):
        if isinstance(value,list):return all(visit(v) for v in value)
        if not isinstance(value,dict):return True
        if 'installation_id' in value and value['installation_id']!=scope.installation_id:return False
        if 'environment' in value and value['environment']!=scope.environment:return False
        if ('repository' in value and value['repository'] not in scope.repositories
                and not (nullable_gap_repository and value['repository'] is None)):return False
        if 'visibility' in value and not set(value['visibility'])<=allowed:return False
        if value.get('origin')=='runtime' and value.get('source') not in scope.runtime_sources:return False
        if value.get('source_kind')=='git' and value.get('source_id') not in scope.repositories:return False
        if value.get('source_kind')=='runtime' and value.get('source_id') not in scope.runtime_sources:return False
        return all(all(visit(g,nullable_gap_repository=True) for g in v) if k=='gaps' and isinstance(v,list)
                   else visit(v) for k,v in value.items())
    return visit(raw)


def ui_result(connection,scope,resource_id):
    data=resource_diagnostics(connection,resource_id)
    if data is None:return None
    expected=canonical(scope.receipt())
    def receipt(generation):
        return connection.execute('SELECT s.* FROM ui_scope_receipts s JOIN jobs j USING(job_id) WHERE j.resource_id=? AND j.generation=? AND s.scope=?',
                                  (resource_id,generation,expected)).fetchone()
    if receipt(data['resource']['generation']) is None:return None
    analysis=data['analysis']
    if analysis is not None:
        trusted=receipt(analysis['generation'])
        if trusted is None:return None
        raw=analysis.pop('raw')
        if raw is not None:
            if (not _output_within_scope(raw,scope) or
                (raw.get('request_id'),raw.get('event_id'),raw.get('resource_version'),raw.get('trigger_kind')) !=
                (trusted['request_id'],trusted['event_id'],trusted['resource_version'],trusted['trigger_kind'])):
                return None
        # Explicit fields only: no costs/model/HTTP receipt, arbitrary snapshot or publisher document.
        fields=('status','reason_code','summary','profile','schema_version','affected','claims','checks','findings',
                'unknowns','gaps','impact_paths','evidence','deltas','relationships')
        analysis['result']={key:raw[key] for key in fields if key in raw} if raw is not None else None
    return {'schema':'impactmap-ui-1','resource':data['resource'],'current_job':data['current_job'],
            'analysis':analysis,'publication':data['publication'],'coverage':'STAMPED_SCOPE_ONLY'}


def _listing_details(connection,scope,limit):
    if type(limit) is not int or not 1<=limit<=100:raise ValueError('invalid_limit')
    candidates=connection.execute('''SELECT r.resource_id FROM resources r
      JOIN jobs j ON j.resource_id=r.resource_id AND j.generation=r.generation
      JOIN ui_scope_receipts s USING(job_id) WHERE s.scope=?
      ORDER BY r.updated_at DESC,r.resource_id LIMIT 1001''',(canonical(scope.receipt()),)).fetchall()
    items=[]
    for row in candidates[:1000]:
        data=ui_result(connection,scope,row['resource_id'])
        if data is not None:
            # List rendering needs state metadata, never retain100 full analyses in memory.
            summary={k:v for k,v in (data['analysis'] or {}).items() if k!='result'}
            items.append({'resource':data['resource'],'current_job':data['current_job'],
                          'analysis':summary if data['analysis'] is not None else None,'publication':data['publication']})
            if len(items)>limit:break
    return {'schema':'impactmap-ui-1','items':items[:limit],'limit':limit,
            'has_more':len(items)>limit,'coverage':'STAMPED_SCOPE_ONLY','scan_budget':1000}


def ui_listing(connection,scope,limit):
    data=_listing_details(connection,scope,limit)
    return {**data,'items':[item['resource'] for item in data['items']]}


def ui_workspace(connection,scope,resource_id=None):
    selected=ui_result(connection,scope,resource_id) if resource_id is not None else None
    if resource_id is not None and selected is None:return None
    return {'listing':_listing_details(connection,scope,100),'selected':selected}
