"""Fresh CoreAnalyzer runs on saved author-pilot pins; no tracker/SCM API.

Run as the isolated service user with the installed release argument. Creates
only new state, never re-stamps or imports results from an older service DB.
"""
from pathlib import Path
import json,os,secrets,sys,time
release=Path(sys.argv[1]);state=Path('/var/lib/impactmap-ui-pilot');etc=Path('/etc/impactmap-ui-pilot')
sys.path[:0]=[str(release/'app/src'),str(release/'app')]
from agent_service.__main__ import _service
from types import SimpleNamespace
from agent_service.analysis import build_request
from agent_service.config import ServiceConfig
from agent_service.envelope import iso,digest
from agent_service.ui_auth import AuthStore,UISettings
from agent_service.ui_scope import scope_for_service

service,cfg=_service(SimpleNamespace(config=str(etc/'service.json'),analyzer=None))
settings=UISettings.load(cfg.ui_config_path);auth=AuthStore(settings.database)
scope=scope_for_service(service);rows=[]
base='5d405f22a0d919dd395fa02339c9170de20a89f7'
reporting='6ebf07174eb9ef4018a98ccf14da1cb94b6a69e3'
for label,head in [('change','3386e00625bbed290957f7e384f8c5858ee56fe6'),('fixed','3883320d4725479f944298c322fa493dfc836457')]:
 rid='bitbucket:offline-pilot/orders#5-'+label;version='offline-pinned:'+head
 snapshot=dict(provider='bitbucket',repository_id='bb.orders',pr_id=5,base_sha=base,head_sha=head,
               title='Offline authored pilot: '+label)
 service.store.apply_snapshot(resource_id=rid,provider='bitbucket',kind='pr',version=version,
                              snapshot=snapshot,event_id='offline-pinned-analysis',closed=False)
 job=service.store.claim_job('offline-pilot-seed')
 assert job and job['resource_id']==rid
 request=build_request(installation_id=cfg.installation_id,environment=cfg.environment,
      request_id=job['job_id'],trigger_kind='pr',event_id='offline-pinned-analysis',resource_version=version,
      subject=snapshot,repository_revisions={'bb.orders':head,'bb.reporting':reporting},
      settings=service.analyzer.request_settings(),deadline=iso(time.time()+120))
 assert service.store.stamp_ui_scope(job,request)
 raw=service.analyzer.analyze(request,attachments={},cancelled=lambda:False)
 service.store.complete_job(job,state='ANALYZED',result=raw,reason=raw['reason_code'],intent=None)
 rows.append(dict(resource_id=rid,head=head,status=raw['status'],reason=raw['reason_code'],raw_sha256=digest(raw)))
access={}
for username,role in [('owner','operator'),('qa-operator','operator'),('qa-reviewer','reviewer')]:
 password=secrets.token_urlsafe(24);auth.create_user(username,password,role,scope.identity)
 access[username]=dict(password=password,role=role)
p=state/'ui/initial-access.json'
fd=os.open(p,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
with os.fdopen(fd,'w') as f:json.dump(access,f)
service.analyzer.close()
print(json.dumps(dict(profile='OFFLINE_SAVED_AUTHOR_PINS_NOT_LIVE',scope=scope.identity,results=rows,accounts_created=list(access))))
