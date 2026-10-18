"""Restore only the approved state-pinned operator SSH CIDR; remove one proven broad drift rule.

Executed while our own runner /32 is installed by scoped_ssh; its finally removes
that temporary rule. No VM, disk, subnet, public-IP or web-port changes allowed.
"""
import hashlib,json,tempfile,time
from pathlib import Path
from scoped_ssh import main, GROUP
ADMIN='cloudru_evolution_compute_security_group_rule.ui_admin[0]'
MANUAL='8cf5d8ec-236b-4046-8357-0e4c375796a9'

def guard_admin(plan,cidr):
 changes=[c for c in plan.get('resource_changes',[]) if c['change']['actions']!=['no-op']]
 if not changes:return {'actions':['no-op']}
 if len(changes)!=1 or changes[0]['address']!=ADMIN:raise ValueError('RULE_UNEXPECTED_RESOURCE_PLAN')
 change=changes[0]['change'];before=change['before'];after=change['after']
 if change['actions'] not in (['update'],['delete','create'],['create','delete']):raise ValueError('RULE_UNEXPECTED_ADMIN_ACTION')
 for value in (before,after):
  if not (value['security_group_id']==GROUP and value['port_range']=='22:22' and value['direction']=='TRAFFIC_DIRECTION_INGRESS' and value['ip_protocol']=='IP_PROTOCOL_TCP' and value['ether_type']=='ETHER_TYPE_IPV4'):raise ValueError('RULE_ADMIN_SCOPE_MISMATCH')
 if before['remote_ip_prefix']!='0.0.0.0/0' or after['remote_ip_prefix']!=cidr or not cidr.endswith('/32'):raise ValueError('RULE_CIDR_CORRECTION_MISMATCH')
 return {'address':ADMIN,'actions':change['actions'],'before':'0.0.0.0/0','after':'EXISTING_STATE_PINNED_OPERATOR_/32','after_sha256':hashlib.sha256(cidr.encode()).hexdigest()}

def reconcile(tf,env,selected,resources):
 import requests
 cidr=resources[('cloudru_evolution_compute_security_group_rule','ui_admin',0)]['remote_ip_prefix']
 if not cidr.endswith('/32'):raise ValueError('RULE_NO_NARROW_OPERATOR_SOURCE_IN_STATE')
 result={'vm_changes':[],'operator_source':'PRESERVED_FROM_EXISTING_STATE','removed_rule_id':None}
 with tempfile.TemporaryDirectory(prefix='lab-network-repair-') as tmp:
  plan=str(Path(tmp)/'repair.plan')
  tf(['plan','-input=false','-no-color','-lock-timeout=60s','-target='+ADMIN,'-out='+plan])
  result['admin_plan']=guard_admin(json.loads(tf(['show','-json',plan])),cidr)
  if result['admin_plan']['actions']!=['no-op']:tf(['apply','-input=false','-no-color',plan])
 auth=requests.post('https://iam.api.cloud.ru/api/v1/auth/token',json={'keyId':env['CLOUDRU_KEY_ID'],'secret':env['CLOUDRU_SECRET']},timeout=25);auth.raise_for_status();headers={'Authorization':'Bearer '+auth.json()['access_token']}
 base='https://compute.api.cloud.ru/api/v1/security-groups/'+GROUP+'/rules'
 current=json.loads(tf(['state','pull']))
 saved=next(i['attributes'] for r in current['resources'] if r.get('type')=='cloudru_evolution_compute_security_group_rule' and r.get('name')=='ui_admin' for i in r['instances'])
 response=requests.get(base+'/'+saved['id'],headers=headers,timeout=25);response.raise_for_status();rule=response.json()
 if rule.get('remote_ip_prefix')!=cidr or rule.get('port_range')!='22:22':raise ValueError('RULE_OPERATOR_RESTORE_NOT_CONFIRMED')
 result['operator_rule_live_matches_state']=True
 response=requests.get(base+'/'+MANUAL,headers=headers,timeout=25)
 if response.status_code!=404:
  response.raise_for_status();rule=response.json()
  if not (rule.get('id')==MANUAL and rule.get('direction')=='ingress' and rule.get('ip_protocol')=='any' and rule.get('port_range')=='any' and rule.get('remote_ip_prefix')=='0.0.0.0/0'):raise ValueError('RULE_MANUAL_DRIFT_SCOPE_CHANGED')
  # This ID is proven absent from the original approved state: no tracked object is deleted.
  if any(i.get('attributes',{}).get('id')==MANUAL for r in current['resources'] for i in r.get('instances',[])):raise ValueError('RULE_MANUAL_ID_NOW_TRACKED_ABORT')
  response=requests.delete(base+'/'+MANUAL,headers=headers,timeout=25);response.raise_for_status()
  result['removed_rule_id']=MANUAL
 for attempt in range(15):
  verify=requests.get(base,headers=headers,timeout=25);verify.raise_for_status();data=verify.json();rules=data.get('items',[])
  if len(rules)!=data.get('total',len(rules)):raise ValueError('RULE_REPAIR_PAGINATION_INCOMPLETE')
  broad=any(r.get('id')==MANUAL or (r.get('direction')=='ingress' and r.get('remote_ip_prefix')=='0.0.0.0/0' and (r.get('ip_protocol')=='any' or r.get('port_range')=='22:22')) for r in rules)
  if not broad:break
  time.sleep(2)
 else:raise ValueError('RULE_BROAD_ADMIN_ACCESS_REMAINS')
 result['broad_admin_absent']=True;result['web_ports_unchanged']=True
 return result
if __name__=='__main__':raise SystemExit(main(reconcile))
