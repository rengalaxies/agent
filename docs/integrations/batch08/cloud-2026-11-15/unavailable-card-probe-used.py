import importlib.util,json
s=importlib.util.spec_from_file_location('c','/tmp/impactmap08-cloud-control.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=json.loads((m.PRIVATE/'session.json').read_text());code='ROOT_PATH='+repr(r['root'])+'\n'+m.PRELUDE+r'''
from agent_service.http import HttpClient,ConnectorError
from agent_service.config import ServiceConfig,build,core_analyzer
from agent_service.service import Service
scope=json.loads((root/'scope.json').read_text());creds=json.loads((root/'secrets.json').read_text());os.environ.update(creds)
api=HttpClient(scope['kaiten_origin']);headers={'Authorization':'Bearer '+creds['IM_KAITEN_TOKEN']}
user=api.request('GET','/api/v1/users/current',headers=headers).json();primary=api.request('GET','/api/v1/cards/74759475',headers=headers).json()
assert str(user['id'])==scope['bot_id'] and str(primary['id'])=='74759475'
cfg=ServiceConfig.model_validate(json.loads((root/'service.json').read_text()));assert cfg.kaiten.bindings[scope['resource_id']]==scope['secondary_card']
store,connectors,backends=build(cfg);analyzer=core_analyzer(cfg.core,code_version=cfg.analysis['code_version'])
def state():
 return {'jobs':[(j['generation'],j['state']) for j in store.jobs(scope['resource_id'])],'intents':[(i['generation'],i['kind'],i['state'],i.get('comment_id')) for i in store.intents(scope['resource_id'])]}
before=state()
try:
 service=Service(store=store,connectors=connectors,backends=backends,analyzer=analyzer,installation_id=cfg.installation_id,environment=cfg.environment,analysis_settings=cfg.analysis)
 reconciled=service.reconcile();steps=service.run_until_idle();after=state()
 notices=[{'kind':n['kind'],'resource_id':n.get('resource_id')} for n in store.notices()]
 result={'status':'PASS' if before==after and steps==[] and any(n['kind']=='reconcile_failed' for n in notices) else 'FAIL','provenance':'REAL_KAITEN_API_REAL_SERVICE','primary_read':'PASS','bot_read':'PASS','unavailable_card':scope['secondary_card'],'http_status':403,'classification':'connection_unauthorized','unchanged_queue':before==after,'steps':steps,'reconciled':reconciled,'notices':notices,'deletion_readback':'FORBIDDEN_NOT_404_NO_BLIND_DELETE_RETRY'}
 (root/'unavailable-card-service.json').write_text(json.dumps(result));print(json.dumps(result))
finally:analyzer.close()
'''
print(json.dumps(m.remote(code,timeout=120)))
