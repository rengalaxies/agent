import pathlib,sys,json,subprocess
release=pathlib.Path('/opt/impactmap-ui-pilot/releases/agent-service-0.1.0-g29ed2ad8fc2e-linux-x86_64-cp312');sys.path[:0]=[str(release/'app/src'),str(release/'app')]
from agent_service.config import ServiceConfig,build_connectors
cfg=ServiceConfig.load('/etc/agent-bitbucket/service.json')
pid=subprocess.check_output(['systemctl','show','agent-bitbucket','-p','MainPID','--value'],text=True).strip()
env=dict(x.split('=',1) for x in pathlib.Path('/proc/'+pid+'/environ').read_text().split('\0') if '=' in x)
out=dict(legacy_pid=pid,namespace=[cfg.installation_id,cfg.environment],jira=dict(base_url=cfg.jira.base_url,project_keys=cfg.jira.project_keys,bot_id=cfg.jira.bot_account_id,comment_format=cfg.jira.comment_format),bitbucket_mode=cfg.bitbucket.mode)

import time
from agent_service.connectors.jira import JiraConnector,BasicAuth,BearerAuth
from agent_service.http import HttpClient
jc=cfg.jira
api=JiraConnector(HttpClient(jc.base_url,timeout=12),BasicAuth(env[jc.auth.email_env],env[jc.auth.token_env]) if jc.auth.kind=='basic' else BearerAuth(env[jc.auth.token_env]),project_keys=jc.project_keys,bot_account_id=jc.bot_account_id,webhook_secret=b'probe-unused',clock=time.time,fields=jc.semantic_fields,comment_format=jc.comment_format)
snapshot=api.resolve_key('KAN-9')
out.update(read_only_jira='PASS',resource=snapshot.resource_id,version=snapshot.version,closed=snapshot.closed);print(json.dumps(out))
