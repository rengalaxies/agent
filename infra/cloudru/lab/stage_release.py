"""Stage only the exact previously verified source; never starts services or SQL.

Uses the existing state-bound VM, independently pinned SSH host key and recovery
credential matching metadata. SFTP owns a new private directory; no sudo/apply.
"""
import base64,hashlib,io,json,logging,os,stat,subprocess,socket
from pathlib import Path
from datetime import datetime,timezone
from preflight import PROJECT,TENANT,select_state,console_pin,live_zone_name,open_ssh_socket
SOURCE='107dfd14292a5ab06593d424bf0b94f1cccb0b90'
ROOT='/home/dmadmin/agent-lab-staging/'+SOURCE

def main():
    import boto3,requests,paramiko
    from botocore.config import Config
    from cryptography.hazmat.primitives import serialization
    report={'status':'FAIL','project_id':PROJECT,'source_commit':SOURCE,'controller_commit':os.getenv('GITHUB_SHA'),'actions_run':'https://github.com/'+os.environ['GITHUB_REPOSITORY']+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],'checked_at':datetime.now(timezone.utc).isoformat(),'services_started':False,'sql_executed':False,'cloud_api_mutations':[],'apply_gate':'BLOCKED','staging_directory':ROOT}
    logging.getLogger('paramiko').disabled=True
    try:
        bundle=Path(os.environ['RELEASE_BUNDLE']);size=bundle.stat().st_size
        if not 0<size<=50*1024*1024:raise ValueError('BUNDLE_SIZE_LIMIT')
        source_root=Path('release-source');actual=subprocess.check_output(['git','rev-parse','HEAD'],cwd=source_root,text=True).strip()
        if actual!=SOURCE:raise ValueError('LOCAL_SOURCE_MISMATCH')
        tree=subprocess.check_output(['git','rev-parse','HEAD^{tree}'],cwd=source_root,text=True).strip();checksum=hashlib.sha256(bundle.read_bytes()).hexdigest()
        sse=base64.b64decode(os.environ['CLOUDRU_STATE_SSE_CUSTOMER_KEY'].strip(),validate=True)
        if len(sse)!=32:raise ValueError('INVALID_SSE_KEY')
        access=os.getenv('CLOUDRU_STATE_ACCESS_KEY_ID') or TENANT+':'+os.environ['CLOUDRU_KEY_ID'];secret=os.getenv('CLOUDRU_STATE_SECRET_ACCESS_KEY') or os.environ['CLOUDRU_SECRET']
        s3=boto3.client('s3',endpoint_url='https://s3.cloud.ru',region_name='ru-central-1',aws_access_key_id=access,aws_secret_access_key=secret,config=Config(s3={'addressing_style':'path'},connect_timeout=15,read_timeout=30))
        def state():return json.loads(s3.get_object(Bucket='test-bucket-ds',Key='terraform/p1/daniil-smirnov.tfstate',SSECustomerAlgorithm='AES256',SSECustomerKey=sse)['Body'].read())
        before=state();selected=select_state(before)
        auth=requests.post('https://iam.api.cloud.ru/api/v1/auth/token',json={'keyId':os.environ['CLOUDRU_KEY_ID'],'secret':os.environ['CLOUDRU_SECRET']},timeout=25);auth.raise_for_status()
        response=requests.get('https://compute.api.cloud.ru/api/v1/vms/'+selected['ui']['id'],headers={'Authorization':'Bearer '+auth.json()['access_token']},timeout=25);response.raise_for_status();vm=response.json().get('vm',response.json())
        if vm.get('name')!='dm-p1-ui' or vm.get('project',{}).get('id')!=PROJECT or vm.get('state')!='running' or live_zone_name(vm)!='ru.AZ-2' or not any(n.get('id')==selected['ui_nic_id'] for n in vm.get('interfaces',[])):raise ValueError('LIVE_VM_SCOPE_MISMATCH')
        key=s3.get_object(Bucket='test-bucket-ds',Key='deployment/p1/ui-recovery-key.pem',SSECustomerAlgorithm='AES256',SSECustomerKey=sse)['Body'].read()
        public=serialization.load_ssh_private_key(key,password=None).public_key().public_bytes(serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH).decode();expected=(selected['ui'].get('image_metadata',{}).get('public_key') or {}).get('string_value','')
        if public.split()[:2]!=expected.split()[:2]:raise ValueError('RECOVERY_METADATA_MISMATCH')
        host=selected['ui_ip'];transport=paramiko.Transport(open_ssh_socket(host,timeout=8));transport.get_security_options().key_types=('ssh-ed25519',);transport.start_client(timeout=10);observed=transport.get_remote_server_key();transport.close()
        if observed.get_name()!='ssh-ed25519' or hashlib.sha256(observed.asbytes()).hexdigest()!=console_pin():raise ValueError('HOST_PIN_MISMATCH')
        with paramiko.SSHClient() as client:
            client.get_host_keys().add(host,'ssh-ed25519',observed);client.set_missing_host_key_policy(paramiko.RejectPolicy())
            client.connect(host,sock=open_ssh_socket(host,timeout=10),username='dmadmin',pkey=paramiko.Ed25519Key.from_private_key(io.StringIO(key.decode())),timeout=10,banner_timeout=10,auth_timeout=10,look_for_keys=False,allow_agent=False)
            report.update(host_key='CONSOLE_SHA256_PIN_MATCH',authentication='PASS')
            with client.open_sftp() as sftp:
                for directory in ['/home/dmadmin/agent-lab-staging',ROOT]:
                    try:sftp.mkdir(directory,mode=0o700)
                    except IOError:
                        a=sftp.lstat(directory)
                        if not stat.S_ISDIR(a.st_mode) or a.st_uid!=1000 or a.st_mode&0o077:raise ValueError('UNSAFE_EXISTING_STAGING_DIRECTORY')
                target=ROOT+'/release-'+checksum+'.bundle'
                try:
                    sftp.stat(target);report['upload']='EXISTING_BUNDLE_RECHECKED'
                except FileNotFoundError:
                    temporary=target+'.upload-'+os.environ['GITHUB_RUN_ID'];sftp.put(str(bundle),temporary);sftp.chmod(temporary,0o600);sftp.rename(temporary,target);report['upload']='SFTP_NEW_PRIVATE_BUNDLE'
            config={'directory':ROOT,'source':SOURCE,'tree':tree,'sha256':checksum,'bundle_name':'release-'+checksum+'.bundle'}
            code='''import hashlib,json,os,subprocess,pathlib,socket,shutil
c=CONFIG
root=pathlib.Path(c['directory']);bundle=root/c['bundle_name'];work=root/'checkout'
assert os.getuid()==1000 and socket.gethostname()=='dm-p1-ui'
assert hashlib.sha256(bundle.read_bytes()).hexdigest()==c['sha256'],'TRANSFER_CHECKSUM_MISMATCH'
assert shutil.disk_usage(root).free>2*1024**3,'INSUFFICIENT_STAGING_DISK'
env=dict(os.environ,GIT_CONFIG_GLOBAL='/dev/null',GIT_CONFIG_SYSTEM='/dev/null',GIT_TERMINAL_PROMPT='0')
def git(args,cwd):
 p=subprocess.run(['git','-c','core.hooksPath=/dev/null']+args,cwd=cwd,env=env,capture_output=True,text=True,timeout=60)
 assert p.returncode==0,'FIXED_GIT_STEP_FAILED'
 return p.stdout.strip()
if not work.exists():
 work.mkdir(mode=0o700);git(['init','--quiet'],work);git(['fetch','--quiet','--no-tags',str(bundle),'HEAD'],work);git(['checkout','--quiet','--detach',c['source']],work)
assert git(['rev-parse','HEAD'],work)==c['source'],'REMOTE_SOURCE_MISMATCH'
assert git(['rev-parse','HEAD^{tree}'],work)==c['tree'],'REMOTE_TREE_MISMATCH'
assert not git(['status','--porcelain'],work),'REMOTE_CHECKOUT_DIRTY'
result={'source_commit':c['source'],'tree_sha':c['tree'],'bundle_sha256':c['sha256'],'transferred_bytes':bundle.stat().st_size,'checkout':str(work),'observed_ssh_client_ip':os.environ.get('SSH_CONNECTION','').split()[0] if os.environ.get('SSH_CONNECTION') else None,'clean_checkout':True,'services_started':False,'sql_executed':False}
(root/'delivery-manifest.json').write_text(json.dumps(result,indent=2)+'\\n');print(json.dumps(result))
'''.replace('CONFIG',repr(config),1)
            stdin,stdout,stderr=client.exec_command('python3 -',timeout=180);stdin.write(code);stdin.channel.shutdown_write();raw=stdout.read(8192);exit_code=stdout.channel.recv_exit_status()
            if exit_code:
                error=stderr.read(8192).decode(errors='replace')
                report['remote_error_categories']=[v for v in ('TRANSFER_CHECKSUM_MISMATCH','INSUFFICIENT_STAGING_DISK','FIXED_GIT_STEP_FAILED','REMOTE_SOURCE_MISMATCH','REMOTE_TREE_MISMATCH','REMOTE_CHECKOUT_DIRTY') if v in error]
                raise ValueError('REMOTE_STAGING_VALIDATION_FAILED')
            report['delivery']=json.loads(raw)
        after=state();report['state_unchanged']=before['serial']==after['serial'] and before['lineage']==after['lineage'];report['state_serial']=after['serial']
        if not report['state_unchanged']:raise ValueError('CONCURRENT_STATE_CHANGE')
        report['status']='PASS_SOURCE_STAGED_NOT_DEPLOYED'
    except Exception as e:
        report['error_class']=type(e).__name__
        if isinstance(e,ValueError):report['error_code']=str(e)
    Path('lab-source-delivery.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2));return 0 if report['status']=='PASS_SOURCE_STAGED_NOT_DEPLOYED' else 1
if __name__=='__main__':raise SystemExit(main())
