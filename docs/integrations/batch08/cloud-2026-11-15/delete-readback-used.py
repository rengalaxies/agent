import importlib.util,json
s=importlib.util.spec_from_file_location('c','/tmp/impactmap08-cloud-control.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
r=json.loads((m.PRIVATE/'session.json').read_text());code='ROOT_PATH='+repr(r['root'])+'\n'+m.PRELUDE+r'''
from agent_service.http import HttpClient,ConnectorError
scope=json.loads((root/'scope.json').read_text());creds=json.loads((root/'secrets.json').read_text())
api=HttpClient(scope['kaiten_origin']);headers={'Authorization':'Bearer '+creds['IM_KAITEN_TOKEN']}
report={'pending_delete_recorded':(root/'pending-delete-card.json').exists()}
try:
 response=api.request('GET','/api/v1/cards/'+scope['secondary_card'],headers=headers);card=response.json()
 report.update(http_status=response.status,card_id=str(card.get('id')),condition=card.get('condition'),deleted=card.get('deleted'),archived=card.get('archived'),board_id=str(card.get('board_id')))
except ConnectorError as exc:report.update(http_status=exc.status,classification=exc.code)
(root/'delete-card-observation.json').write_text(json.dumps(report));print(json.dumps(report))
'''
print(json.dumps(m.remote(code,timeout=60)))
