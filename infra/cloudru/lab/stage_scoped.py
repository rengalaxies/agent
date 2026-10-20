"""Use only a temporary current-runner /32 for fixed-source staging, then remove it."""
import json
from pathlib import Path
from scoped_ssh import main, GROUP
from stage_release import main as stage

def deliver(tf,env,selected,resources):
 import requests,ipaddress
 auth=requests.post('https://iam.api.cloud.ru/api/v1/auth/token',json={'keyId':env['CLOUDRU_KEY_ID'],'secret':env['CLOUDRU_SECRET']},timeout=25);auth.raise_for_status()
 response=requests.get('https://compute.api.cloud.ru/api/v1/security-groups/'+GROUP+'/rules',headers={'Authorization':'Bearer '+auth.json()['access_token']},timeout=25);response.raise_for_status();data=response.json();rules=data.get('items',[])
 if len(rules)!=data.get('total',len(rules)):raise ValueError('RULE_SOURCE_PAGINATION_INCOMPLETE')
 if any(r.get('direction')=='ingress' and r.get('remote_ip_prefix')=='0.0.0.0/0' and (r.get('ip_protocol')=='any' or r.get('port_range')=='22:22') for r in rules):raise ValueError('RULE_BROAD_ADMIN_ACCESS_REAPPEARED')
 if stage()!=0:raise ValueError('RULE_EXACT_SOURCE_STAGING_FAILED')
 delivery=json.loads(Path('lab-source-delivery.json').read_text())
 source=delivery['delivery'].get('observed_ssh_client_ip')
 if not source or source+'/32'!=env['TF_VAR_lab_runner_cidr']:raise ValueError('RULE_OBSERVED_SSH_SOURCE_DOES_NOT_MATCH_RUNNER_PIN')
 return {'action':'EXACT_SOURCE_STAGING','broad_admin_absent':True,'server_observed_source_matches_temporary_runner_rule':True,'services_started':False,'sql_executed':False}
if __name__=='__main__':raise SystemExit(main(deliver))
