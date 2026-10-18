"""Pinned, scoped runtime survey. No source delivery or service mutation."""
import base64,hashlib,io,json,os,logging
from pathlib import Path
from scoped_ssh import main
from preflight import TENANT,console_pin,open_ssh_socket

def connect(env,selected):
 import boto3,paramiko
 from botocore.config import Config
 from cryptography.hazmat.primitives import serialization
 logging.getLogger('paramiko').disabled=True
 sse=base64.b64decode(env['CLOUDRU_STATE_SSE_CUSTOMER_KEY'],validate=True)
 s3=boto3.client('s3',endpoint_url='https://s3.cloud.ru',region_name='ru-central-1',aws_access_key_id=env.get('CLOUDRU_STATE_ACCESS_KEY_ID') or TENANT+':'+env['CLOUDRU_KEY_ID'],aws_secret_access_key=env.get('CLOUDRU_STATE_SECRET_ACCESS_KEY') or env['CLOUDRU_SECRET'],config=Config(s3={'addressing_style':'path'},connect_timeout=15,read_timeout=30))
 key=s3.get_object(Bucket='test-bucket-ds',Key='deployment/p1/ui-recovery-key.pem',SSECustomerAlgorithm='AES256',SSECustomerKey=sse)['Body'].read()
 public=serialization.load_ssh_private_key(key,password=None).public_key().public_bytes(serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH).decode()
 expected=selected['ui']['image_metadata']['public_key']['string_value']
 if public.split()[:2]!=expected.split()[:2]:raise ValueError('RECOVERY_METADATA_MISMATCH')
 host=selected['ui_ip'];transport=paramiko.Transport(open_ssh_socket(host,timeout=10));transport.get_security_options().key_types=('ssh-ed25519',);transport.start_client(timeout=10);observed=transport.get_remote_server_key();transport.close()
 if hashlib.sha256(observed.asbytes()).hexdigest()!=console_pin():raise ValueError('HOST_PIN_MISMATCH')
 client=paramiko.SSHClient();client.get_host_keys().add(host,'ssh-ed25519',observed);client.set_missing_host_key_policy(paramiko.RejectPolicy());client.connect(host,sock=open_ssh_socket(host,timeout=10),username='dmadmin',pkey=paramiko.Ed25519Key.from_private_key(io.StringIO(key.decode())),timeout=10,banner_timeout=10,auth_timeout=10,look_for_keys=False,allow_agent=False)
 return client

def action(tf,env,selected,resources):
 code=Path('infra/cloudru/lab/runtime_survey.py').read_text()
 with connect(env,selected) as client:
  stdin,stdout,stderr=client.exec_command('python3 -',timeout=90);stdin.write(code);stdin.channel.shutdown_write();raw=stdout.read(60000);status=stdout.channel.recv_exit_status()
  if status:raise ValueError('RULE_RUNTIME_SURVEY_FAILED')
  result=json.loads(raw)
 if result['observed_source']+'/32'!=env['TF_VAR_lab_runner_cidr']:raise ValueError('RULE_SERVER_SOURCE_MISMATCH')
 Path('lab-runtime-survey.json').write_text(json.dumps(result,indent=2)+'\n')
 return {'action':'READ_ONLY_RUNTIME_SURVEY','source_matches':True,'services_started':False}
if __name__=='__main__':raise SystemExit(main(action))
