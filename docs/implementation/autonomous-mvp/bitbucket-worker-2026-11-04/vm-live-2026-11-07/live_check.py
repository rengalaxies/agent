"""Controlled one-shot LIVE acceptance; only PR2, never the persistent worker config."""
import sys,os,json,pathlib,base64,urllib.request
sys.path[:0]=['/opt/agent-bitbucket/current/app/src','/opt/agent-bitbucket/current/app']
from tools.agent_service.box.launch import identity
from agent_service.config import ServiceConfig,build,core_analyzer
from agent_service.service import Service
assert identity()['commit']=='c4053c6d4a959ff4d0e159c3cb1913fae87f25fb'
root=pathlib.Path('/var/lib/agent-bitbucket/live-acceptance');root.mkdir(mode=0o700,exist_ok=True)
d=json.loads(pathlib.Path('/etc/agent-bitbucket/service.json').read_text());d['publication']='live';d['state_path']=str(root/'service/service.sqlite');d['core']['state_dir']=str(root/'core')
cfg=ServiceConfig.model_validate(d);store,connectors,backends=build(cfg);a=core_analyzer(cfg.core,code_version=cfg.analysis['code_version']);s=Service(store=store,connectors=connectors,backends=backends,analyzer=a,installation_id=cfg.installation_id,environment=cfg.environment)
rid='bitbucket:e0b65402-98d3-432d-9ba0-8e92884d8bfb/ce63c558-64b3-462f-9ab9-1b954c14f5d9#2'
original=connectors['bitbucket'].reconcile_candidates
connectors['bitbucket'].reconcile_candidates=lambda since:[x for x in original(since) if x[0]==rid]
auth=base64.b64encode((os.environ['JIRA_EMAIL']+':'+os.environ['JIRA_API_TOKEN']).encode()).decode()
def call(product,path,method='GET',data=None):
 req=urllib.request.Request('https://api.atlassian.com/ex/'+product+'/d0b47b8d-4655-4cb1-9f81-30573fd372c3'+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers={'Authorization':'Basic '+auth,'Content-Type':'application/json'})
 with urllib.request.urlopen(req,timeout=30) as response:
  raw=response.read();return json.loads(raw) if raw else {}
def persist(r):
 (root/'report.json').write_text(json.dumps(r,ensure_ascii=False,indent=2)+'\n')
report={'scope':'VM_ONE_SHOT_LIVE_FILTERED_PR2','host':'dm-p1-ui','release_sha':identity()['commit'],'persistent_worker_publication':'dry_run','resource_id':rid,'model':'OFF'}
try:
 beforecomments=call('jira','/rest/api/3/issue/KAN-8/comment?maxResults=100');beforeids={x['id'] for x in beforecomments['comments']}
 baseline=s.reconcile();steps=s.run_until_idle();resource=store.resource(rid);assert store.jobs(rid)[-1]['state']=='DONE';assert resource['comment_id'].startswith('jira:10022|')
 cid=resource['comment_id'].split('|')[1];comment=call('jira','/rest/api/3/issue/KAN-8/comment/'+cid);assert '360725' in json.dumps(comment['body'])
 head=connectors['bitbucket'].fetch(rid).data['head_sha'];generation=resource['generation']
 report.update(comment_id=cid,baseline_steps=steps,baseline_reconcile=baseline,before_generation=generation,head_sha=head,comment_created=comment['created']);persist(report)
 page=call('confluence','/wiki/api/v2/pages/360725?body-format=storage');version=page['version']['number'];marker='CF-VM-LIVE-20261107'
 body=page['body']['storage']['value'];assert marker not in body,'already performed; inspect report instead of replay'
 page=call('confluence','/wiki/api/v2/pages/360725','PUT',{'id':'360725','status':'current','title':page['title'],'body':{'representation':'storage','value':body+'<p>'+marker+': контроль чтения актуальной документации агентом на Cloud.ru.</p>'},'version':{'number':version+1,'message':'Cloud.ru scoped live acceptance'}})
 reconciliation=s.reconcile();updated_steps=s.run_until_idle();after=store.resource(rid)
 assert after['generation']==generation+1;assert after['comment_id']==resource['comment_id'];assert store.jobs(rid)[-1]['state']=='DONE'
 comment=call('jira','/rest/api/3/issue/KAN-8/comment/'+cid);assert marker in json.dumps(comment['body'],ensure_ascii=False)
 assert connectors['bitbucket'].fetch(rid).data['head_sha']==head
 repeat=s.reconcile();repeat_steps=s.run_until_idle();assert repeat['enqueued']==0 and repeat_steps==[]
 comments=call('jira','/rest/api/3/issue/KAN-8/comment?maxResults=100');afterids={x['id'] for x in comments['comments']};assert afterids-beforeids=={cid}
 report.update(result='PASS',page_id='360725',before_page_version=version,after_page_version=page['version']['number'],after_generation=after['generation'],update_reconcile=reconciliation,update_steps=updated_steps,comment_updated=comment['updated'],same_comment=True,new_comments=len(afterids-beforeids),repeat_enqueued=repeat['enqueued'],repeat_steps=repeat_steps,status=store.status());persist(report);print(json.dumps(report,ensure_ascii=False,indent=2))
finally:a.close()
