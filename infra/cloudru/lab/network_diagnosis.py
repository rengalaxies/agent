"""Exact existing-resource network diagnosis. GET-only cloud API; no infrastructure mutation.

Credentials/state remain in memory. Output is an allowlist; operator admin CIDRs
are hashed, while ephemeral runner and target public addresses identify the test.
"""
import base64, hashlib, ipaddress, json, os, socket, time
from datetime import datetime, timezone
from pathlib import Path
from preflight import PROJECT, TENANT, select_state, live_zone_name, ssh_probe

BASE='https://compute.api.cloud.ru/api/v1'
def now():return datetime.now(timezone.utc).isoformat()
def ident(value):return value.get('id') if isinstance(value,dict) else value

def safe_network(doc):
    allowed={'id','name','state','status','ip_address','fixed_ip_address','private_ip','public_ip','mac_address','mac','cidr','gateway','gateway_ip','gateway_ip_address','dhcp_enabled','enable_dhcp','interface_security_enabled','port_security_enabled','type','mtu','is_default','availability_zone','zone','project','project_id','subnet','vpc','vpc_id','vm','vm_id','device_id','network_interface','network_interface_id','interface_id','floating_ip','floating_ip_id','security_groups','interfaces','routes','route_table','route_table_id','nat_gateway','nat_gateway_id','floating_ip_address','external_ip','external_ip_address','fixed_ips','interface','default_gateway','dhcp_default_gateway','subnet_address','routed_network','nat_rules','destination','destination_cidr','next_hop','nexthop','created_time','modified_time','default','nat_type'}
    if isinstance(doc,list):return [safe_network(x) for x in doc]
    if isinstance(doc,dict):return {k:safe_network(v) if isinstance(v,(dict,list)) else v for k,v in doc.items() if k in allowed}
    return doc

def rule_match(rule,source,port):
    direction=str(rule.get('direction','')).upper()
    if direction not in ('INGRESS','TRAFFIC_DIRECTION_INGRESS'):return False
    proto=str(rule.get('ip_protocol',rule.get('protocol',''))).upper()
    if proto not in ('TCP','6','IP_PROTOCOL_TCP','ANY','IP_PROTOCOL_ANY','-1'):return False
    prefix=rule.get('remote_ip_prefix')
    if not prefix:return None  # remote group / unrecognized selector is not proof of access
    try:
        if ipaddress.ip_address(source) not in ipaddress.ip_network(prefix,strict=False):return False
    except ValueError:return None
    span=rule.get('port_range')
    if span in ('any','ANY') or proto in ('ANY','IP_PROTOCOL_ANY','-1'):return True
    if span:
        try:
            bits=str(span).split(':');low=int(bits[0]);high=int(bits[-1]);return low<=port<=high
        except ValueError:return None
    low=rule.get('port_range_min');high=rule.get('port_range_max')
    if low is None or high is None:return None
    return int(low)<=port<=int(high)

def public_rule(r,source):
    result={k:r[k] for k in ('id','direction','ether_type','ip_protocol','protocol','port_range','port_range_min','port_range_max','remote_security_group','state','status','created_time','modified_time') if k in r}
    prefix=r.get('remote_ip_prefix')
    if prefix:
        net=ipaddress.ip_network(prefix,strict=False)
        result.update(source_prefix=prefix if net.is_private or net.prefixlen==0 else 'OPERATOR_CIDR_WITHHELD',source_prefix_sha256=hashlib.sha256(prefix.encode()).hexdigest(),source_prefix_length=net.prefixlen)
    result['runner_tcp22_match']=rule_match(r,source,22)
    result['runner_tcp80_match']=rule_match(r,source,80)
    result['runner_tcp443_match']=rule_match(r,source,443)
    return result

def tcp(host,port):
    result={'started_at':now(),'port':port,'tcp':'NOT_ATTEMPTED','host_key':'NOT_REACHED','ssh_authentication':'NOT_REACHED'}
    started=time.monotonic()
    try:
        with socket.create_connection((host,port),timeout=8) as sock:
            result.update(tcp='CONNECTED',runner_local_port=sock.getsockname()[1]);sock.settimeout(5)
            if port==22:
                banner=sock.recv(128)
                result['ssh_banner_valid']=banner.startswith(b'SSH-')
                result['ssh_banner']=banner.decode('ascii',errors='replace').strip()[:100] if banner.startswith(b'SSH-') else 'NO_VALID_SSH_BANNER'
    except Exception as e:result.update(tcp='FAILED',error_class=type(e).__name__,errno=getattr(e,'errno',None))
    result.update(finished_at=now(),elapsed_seconds=round(time.monotonic()-started,3));return result

def main():
    import boto3,requests
    from botocore.config import Config
    report={'project_id':PROJECT,'source_commit':os.getenv('GITHUB_SHA'),'actions_run':'https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],'started_at':now(),'read_only':True,'cloud_mutations':[],'apply_gate':'BLOCKED','api':{},'checks':{}}
    try:
        sse=base64.b64decode(os.environ['CLOUDRU_STATE_SSE_CUSTOMER_KEY'].strip(),validate=True)
        if len(sse)!=32:raise ValueError('INVALID_SSE_KEY')
        access=os.getenv('CLOUDRU_STATE_ACCESS_KEY_ID') or TENANT+':'+os.environ['CLOUDRU_KEY_ID']
        secret=os.getenv('CLOUDRU_STATE_SECRET_ACCESS_KEY') or os.environ['CLOUDRU_SECRET']
        s3=boto3.client('s3',endpoint_url='https://s3.cloud.ru',region_name='ru-central-1',aws_access_key_id=access,aws_secret_access_key=secret,config=Config(s3={'addressing_style':'path'},connect_timeout=15,read_timeout=30))
        def read_state():return json.loads(s3.get_object(Bucket='test-bucket-ds',Key='terraform/p1/daniil-smirnov.tfstate',SSECustomerAlgorithm='AES256',SSECustomerKey=sse)['Body'].read())
        state=read_state();selected=select_state(state);report['state_serial']=state['serial']
        resources={(r['type'],r['name'],i.get('index_key')):i['attributes'] for r in state['resources'] if r.get('mode')=='managed' for i in r.get('instances',[])}
        auth=requests.post('https://iam.api.cloud.ru/api/v1/auth/token',json={'keyId':os.environ['CLOUDRU_KEY_ID'],'secret':os.environ['CLOUDRU_SECRET']},timeout=25);auth.raise_for_status();headers={'Authorization':'Bearer '+auth.json()['access_token']}
        def get(label,path):
            r=requests.get(BASE+path,headers=headers,timeout=25,allow_redirects=False)
            report['api'][label]={'http_status':r.status_code,'checked_at':now(),'request_id':r.headers.get('x-request-id') or r.headers.get('x-trace-id')}
            r.raise_for_status();doc=r.json()
            report['api'][label]['response_fields']=sorted(doc) if isinstance(doc,dict) else ['LIST']
            if isinstance(doc,dict):
                project=ident(doc.get('project')) or doc.get('project_id')
                if project and project!=PROJECT:raise ValueError('API_PROJECT_MISMATCH')
            return doc
        runner=requests.get('https://api.ipify.org',timeout=15);runner.raise_for_status();source=str(ipaddress.ip_address(runner.text.strip()));report['runner_public_ipv4']=source
        report['vms']={}
        for label in ('ui','core'):
            expected=selected[label];vm=get('vm_'+label,'/vms/'+expected['id']);vm=vm.get('vm',vm)
            if vm.get('name')!=expected['name'] or ident(vm.get('project'))!=PROJECT or live_zone_name(vm)!='ru.AZ-2':raise ValueError('VM_IDENTITY_MISMATCH')
            report['vms'][label]={k:vm.get(k) for k in ('id','name','state','guest_agent_state')};report['vms'][label]['interfaces']=safe_network(vm.get('interfaces',[]))
        nic=get('ui_interface','/interfaces/'+selected['ui_nic_id']);nic=nic.get('interface',nic);report['ui_interface']=safe_network(nic)
        fip=get('ui_floating_ip','/floating-ips/33a27f64-e474-49ed-a17b-15f67dd16400');fip=fip.get('floating_ip',fip);report['ui_floating_ip']=safe_network(fip)
        report['checks']['vm_has_expected_nic']=any(ident(n)==selected['ui_nic_id'] for n in report['vms']['ui']['interfaces'])
        report['checks']['fip_targets_expected_nic']=ident(fip.get('interface'))==selected['ui_nic_id'] or ident(fip.get('network_interface'))==selected['ui_nic_id'] or fip.get('interface_id')==selected['ui_nic_id']
        report['checks']['fip_address_matches_state']=fip.get('ip_address')==selected['ui_ip']
        subnet_id=ident(nic.get('subnet'))
        if subnet_id:
            subnet=get('subnet','/subnets/'+subnet_id);report['subnet']=safe_network(subnet)
        groups=nic.get('security_groups',[]);report['security_groups']=[]
        for value in groups:
            gid=ident(value);sg=get('security_group_'+gid,'/security-groups/'+gid);raw=get('security_group_rules_'+gid,'/security-groups/'+gid+'/rules')
            rules=raw if isinstance(raw,list) else raw.get('items',raw.get('rules',raw.get('security_group_rules',[])))
            if not isinstance(rules,list):raise ValueError('RULE_SCHEMA_UNRECOGNIZED')
            if isinstance(raw,dict) and raw.get('total',len(rules))!=len(rules):raise ValueError('RULE_PAGINATION_INCOMPLETE')
            report['security_groups'].append({'group':safe_network(sg),'rule_count':len(rules),'total':raw.get('total',len(rules)) if isinstance(raw,dict) else len(rules),'rules':[public_rule(r,source) for r in rules]})
        for (kind,name,index),value in resources.items():
            if kind=='cloudru_evolution_compute_nat_gateway':report['nat_gateway']=safe_network(get('existing_nat_gateway','/nat-gateways/'+value['id']))
        report['state_ui_rules']=[{'terraform_resource':name,'rule':public_rule(v,source)} for (kind,name,index),v in resources.items() if kind=='cloudru_evolution_compute_security_group_rule' and v.get('security_group_id')=='4dde92a5-23a7-4c97-b48f-361d248b5af3']
        live_ids={r['id'] for g in report['security_groups'] for r in g['rules']}
        state_ids={x['rule']['id'] for x in report['state_ui_rules']}
        report['security_rule_inventory_difference']={'live_only_ids':sorted(live_ids-state_ids),'state_only_ids':sorted(state_ids-live_ids),'note':'Difference is not automatically repaired; existing rules may be operator-managed.'}
        report['checks']['runner_tcp22_authorized_by_attached_sg']=any(r['runner_tcp22_match'] is True for sg in report['security_groups'] for r in sg['rules'])
        report['tcp_probes']=[tcp(selected['ui_ip'],port) for port in (22,80,443)]
        if report['tcp_probes'][0]['tcp']=='CONNECTED':
            key=s3.get_object(Bucket='test-bucket-ds',Key='deployment/p1/ui-recovery-key.pem',SSECustomerAlgorithm='AES256',SSECustomerKey=sse)['Body'].read()
            from cryptography.hazmat.primitives import serialization
            public=serialization.load_ssh_private_key(key,password=None).public_key().public_bytes(serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH).decode()
            expected=(selected['ui'].get('image_metadata',{}).get('public_key') or {}).get('string_value','')
            if public.split()[:2]!=expected.split()[:2]:raise ValueError('RECOVERY_KEY_METADATA_MISMATCH')
            report['pinned_ssh']=ssh_probe(selected['ui_ip'],key)
        after=read_state();report['checks']['state_unchanged']=after['serial']==state['serial'] and after['lineage']==state['lineage']
        report['status']='COLLECTED'
    except Exception as e:
        report.update(status='PARTIAL',error_class=type(e).__name__)
        if isinstance(e,ValueError):report['error_code']=str(e)
    report['finished_at']=now();Path('lab-network-diagnosis.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
    return 0 if report['status']=='COLLECTED' else 1
if __name__=='__main__':raise SystemExit(main())
