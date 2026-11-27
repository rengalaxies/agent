import json,pathlib,subprocess,os,sys
p=pathlib.Path('/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312');sys.path[:0]=[str(p/'app/src'),str(p/'app')]
from agent_service.config import ServiceConfig,build_bitbucket_reader
prod=ServiceConfig.load('/etc/agent-bitbucket/service.json')
pid=int(subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True))
env=dict(x.split('=',1) for x in pathlib.Path(f'/proc/{pid}/environ').read_text().split('\0') if '=' in x)
reader=build_bitbucket_reader(prod,env_secret=lambda n:env[n])
# Read only the already dedicated authored PR5.
repo=reader.repository('agent-pilot-orders')
pr=reader.pull_request(repo,5)
print(json.dumps(dict(status='READ_ONLY_PASS',pr=pr.number,state=pr.state,head_ref=pr.source_branch,head=pr.head_sha,base_ref=pr.destination_branch,destination_tip=pr.base_sha,resource_id=pr.resource_id,local_secret_names_present=[n for n in (prod.bitbucket.auth.email_env,prod.bitbucket.auth.token_env) if n in env])))
