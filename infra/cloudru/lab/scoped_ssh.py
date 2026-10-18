"""One temporary runner /32 SSH rule, exact-state plan guard, pinned read-only SSH.

Never replaces an existing rule or compute resource. Removes only its own new rule.
Raw state, Terraform logs/plans and credentials stay in private runner storage.
"""
import base64
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile
from datetime import datetime, timezone
from preflight import PROJECT, TENANT, select_state, live_zone_name, ssh_probe

ADDRESS = 'cloudru_evolution_compute_security_group_rule.lab_runner_access[0]'
GROUP = '4dde92a5-23a7-4c97-b48f-361d248b5af3'
ROOT = Path(__file__).resolve().parents[1] / 'deploy'


def guard(plan, cidr, opening):
    changes = [c for c in plan.get('resource_changes', []) if c['change']['actions'] != ['no-op']]
    if len(changes) != 1 or changes[0]['address'] != ADDRESS:
        raise ValueError('UNEXPECTED_RESOURCE_PLAN')
    change = changes[0]['change']
    expected = ['create'] if opening else ['delete']
    if change['actions'] != expected:
        raise ValueError('EXISTING_RESOURCE_MUTATION_FORBIDDEN')
    value = change['after'] if opening else change['before']
    network = ipaddress.ip_network(cidr, strict=True)
    if network.version != 4 or network.prefixlen != 32 or not network.network_address.is_global:
        raise ValueError('RUNNER_ADDRESS_INVALID')
    if not (value['security_group_id'] == GROUP and value['remote_ip_prefix'] == cidr
            and value['port_range'] == '22:22' and value['direction'] == 'TRAFFIC_DIRECTION_INGRESS'
            and value['ip_protocol'] == 'IP_PROTOCOL_TCP' and value['ether_type'] == 'ETHER_TYPE_IPV4'):
        raise ValueError('RULE_SCOPE_MISMATCH')
    return {'address': ADDRESS, 'actions': expected, 'source': 'current_runner_only_/32', 'port': 22}


def main(after_open=None):
    report = {'project_id': PROJECT, 'source_commit': os.getenv('GITHUB_SHA'),
              'checked_at': datetime.now(timezone.utc).isoformat(),
              'status': 'BLOCKED', 'existing_compute_changes': 'NONE', 'cleanup': 'NOT_NEEDED'}
    env = dict(os.environ)
    try:
        import boto3
        import requests
        from botocore.config import Config
        sse = base64.b64decode(env['CLOUDRU_STATE_SSE_CUSTOMER_KEY'].strip(), validate=True)
        if len(sse) != 32: raise ValueError('INVALID_SSE_KEY')
        access = env.get('CLOUDRU_STATE_ACCESS_KEY_ID') or TENANT+':'+env['CLOUDRU_KEY_ID']
        secret = env.get('CLOUDRU_STATE_SECRET_ACCESS_KEY') or env['CLOUDRU_SECRET']
        client = boto3.client('s3', endpoint_url='https://s3.cloud.ru', region_name='ru-central-1',
            aws_access_key_id=access, aws_secret_access_key=secret,
            config=Config(s3={'addressing_style':'path'},connect_timeout=15,read_timeout=30))
        def state():
            return json.loads(client.get_object(Bucket='test-bucket-ds',Key='terraform/p1/daniil-smirnov.tfstate',
                SSECustomerAlgorithm='AES256',SSECustomerKey=sse)['Body'].read())
        original = state()
        selected = select_state(original)
        resources = {(r['type'],r['name'],i.get('index_key')):i['attributes']
            for r in original['resources'] if r.get('mode')=='managed' for i in r.get('instances',[])}
        if any(r['name']=='lab_runner_access' and r.get('instances') for r in original['resources']):
            raise ValueError('PRIOR_TEMPORARY_RULE_REQUIRES_RECONCILIATION')
        sg = resources[('cloudru_evolution_compute_security_group','ui',None)]
        if sg['id'] != GROUP or sg.get('project_id') != PROJECT:
            raise ValueError('SECURITY_GROUP_SCOPE_MISMATCH')
        response=requests.post('https://iam.api.cloud.ru/api/v1/auth/token',json={
            'keyId':env['CLOUDRU_KEY_ID'],'secret':env['CLOUDRU_SECRET']},timeout=30)
        response.raise_for_status()
        response=requests.get('https://compute.api.cloud.ru/api/v1/vms/'+selected['ui']['id'],
            headers={'Authorization':'Bearer '+response.json()['access_token']},timeout=30)
        response.raise_for_status(); vm=response.json().get('vm',response.json())
        if (vm.get('name')!='dm-p1-ui' or vm.get('project',{}).get('id')!=PROJECT
                or live_zone_name(vm)!='ru.AZ-2' or vm.get('state')!='running'
                or not any(n.get('id')==selected['ui_nic_id'] for n in vm.get('interfaces',[]))):
            raise ValueError('LIVE_UI_SCOPE_MISMATCH')
        response=requests.get('https://api.ipify.org',timeout=15);response.raise_for_status()
        ip=ipaddress.ip_address(response.text.strip());cidr=str(ip)+'/32'
        if ip.version!=4 or not ip.is_global:raise ValueError('RUNNER_ADDRESS_INVALID')
        for value in (access,secret,base64.b64encode(sse).decode(),str(ip),cidr,selected['ui_ip']):
            print('::add-mask::'+value)
        env.update(AWS_ACCESS_KEY_ID=access,AWS_SECRET_ACCESS_KEY=secret,
            AWS_SSE_CUSTOMER_KEY=base64.b64encode(sse).decode(),TF_IN_AUTOMATION='true',
            TF_VAR_auth_key_id=env['CLOUDRU_KEY_ID'],TF_VAR_auth_secret=env['CLOUDRU_SECRET'],
            TF_VAR_project_id=PROJECT,TF_VAR_ui_flavor='gen-2-4',TF_VAR_core_flavor='gen-2-8',
            TF_VAR_git_ref='29223626ae81cc51a97698bb77475b3640a660fa',
            TF_VAR_ubuntu_image_id='fe51a6e6-a5ad-410e-b441-1a195208a8cf',
            TF_VAR_ssh_public_key=env['CLOUDRU_SSH_PUBLIC_KEY'],
            TF_VAR_ui_basic_auth_hash=env['CLOUDRU_UI_BASIC_AUTH_HASH'],
            TF_VAR_original_ui_ip=selected['ui_ip'],TF_VAR_lab_runner_cidr=cidr)
        owner = resources.get(('cloudru_evolution_compute_security_group_rule','ui_admin',0))
        env['TF_VAR_admin_cidr'] = owner['remote_ip_prefix'] if owner else ''
        (ROOT/'backend.tf').write_text('terraform {\n  backend "s3" {}\n}\n')
        (ROOT/'lab-runner-access.tf').write_text('''variable "lab_runner_cidr" { type = string }
resource "cloudru_evolution_compute_security_group_rule" "lab_runner_access" {
  count = var.lab_runner_cidr == "" ? 0 : 1
  security_group_id = cloudru_evolution_compute_security_group.ui.id
  direction = "TRAFFIC_DIRECTION_INGRESS"
  ether_type = "ETHER_TYPE_IPV4"
  ip_protocol = "IP_PROTOCOL_TCP"
  port_range = "22:22"
  remote_ip_prefix = var.lab_runner_cidr
}
''')
        def tf(args, timeout=180):
            proc=subprocess.run(['terraform']+args,cwd=ROOT,env=env,capture_output=True,text=True,timeout=timeout)
            if proc.returncode:raise RuntimeError('TERRAFORM_'+args[0].upper()+'_FAILED')
            return proc.stdout
        report['phase']='BACKEND_INIT'
        tf(['init','-reconfigure','-input=false','-no-color']+['-backend-config='+x for x in [
            'bucket=test-bucket-ds','key=terraform/p1/daniil-smirnov.tfstate','region=ru-central-1',
            'endpoints={s3="https://s3.cloud.ru"}','use_lockfile=true','encrypt=true',
            'skip_credentials_validation=true','skip_region_validation=true','skip_requesting_account_id=true',
            'skip_metadata_api_check=true','use_path_style=true']],300)
        select_state(json.loads(tf(['state','pull'])))
        with tempfile.TemporaryDirectory(prefix='lab-ssh-') as tmp:
            plan_path=str(Path(tmp)/'scoped.plan')
            attempted=False
            try:
                report['phase']='GUARDED_PLAN'
                tf(['plan','-input=false','-no-color','-lock-timeout=60s','-target='+ADDRESS,'-out='+plan_path])
                report['opening_plan']=guard(json.loads(tf(['show','-json',plan_path])),cidr,True)
                attempted=True
                report['cleanup']='REQUIRED'
                report['phase']='OPEN_SINGLE_RUNNER_RULE'
                tf(['apply','-input=false','-no-color',plan_path])
                if after_open is not None:
                    report['phase']='BOUNDED_AUTHORIZED_ACTION'
                    report['authorized_action']=after_open(tf,env,selected,resources)
                report['phase']='PINNED_READONLY_SSH'
                from cryptography.hazmat.primitives import serialization
                key=client.get_object(Bucket='test-bucket-ds',Key='deployment/p1/ui-recovery-key.pem',
                    SSECustomerAlgorithm='AES256',SSECustomerKey=sse)['Body'].read()
                public=serialization.load_ssh_private_key(key,password=None).public_key().public_bytes(
                    serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH).decode()
                expected=(selected['ui'].get('image_metadata',{}).get('public_key') or {}).get('string_value','')
                if public.split()[:2]!=expected.split()[:2]:raise ValueError('RECOVERY_KEY_METADATA_MISMATCH')
                report['ssh']=ssh_probe(selected['ui_ip'],key)
                report['status']='PASS' if report['ssh']['status']=='PASS_READONLY_OS_INVENTORY' else 'BLOCKED'
            finally:
                if attempted:
                    report['phase']='CLEANUP_OWN_RULE'
                    current=json.loads(tf(['state','pull']))
                    present=any(r['name']=='lab_runner_access' and r.get('instances') for r in current['resources'])
                    if present:
                        env['TF_VAR_lab_runner_cidr']=''
                        tf(['plan','-input=false','-no-color','-lock-timeout=60s','-target='+ADDRESS,'-out='+plan_path])
                        report['cleanup_plan']=guard(json.loads(tf(['show','-json',plan_path])),cidr,False)
                        tf(['apply','-input=false','-no-color',plan_path])
                    after=state();select_state(after)
                    if any(r['name']=='lab_runner_access' and r.get('instances') for r in after['resources']):
                        raise ValueError('TEMPORARY_RULE_STILL_PRESENT')
                    report['cleanup']='PASS_OWN_TEMPORARY_RULE_ABSENT'
        report['phase']='DONE'
    except Exception as exc:
        report['status']='BLOCKED'
        report['error_class']=type(exc).__name__
        if str(exc).startswith(('TERRAFORM_','HOST_','LIVE_','PRIOR_','TEMPORARY_','RULE_','SECURITY_','RUNNER_','RECOVERY_','UNEXPECTED_','EXISTING_')):
            report['error_code']=str(exc)
    Path('lab-scoped-ssh.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report,indent=2))
    return 0 if report['status']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
